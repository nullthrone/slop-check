"""Human and AI corpora (docs/architecture.md section 6.1).

Human corpus
    Pinned public datasets with text published before 2022-11-01, listed in
    ``evals/corpus/human.yaml``. Rows come from the Hugging Face datasets-server JSON API
    (no parquet dependency). Sampling is deterministic for a given seed and dataset state.
    Texts are written only to a local directory (``docs.jsonl``); ``manifest.json`` holds
    references and SHA-256 hashes and is the only file meant for branch ``data``.

AI corpus
    For each resolved generator model and each human document (up to the selector's
    ``docs_per_language``), a fixed prompt from ``evals/corpus/prompts/<lang>.yaml`` is filled
    with a topic derived from the human document (no LLM call) and a target length matched to
    it. Output: ``<out>/<canonical_slug with / as __>/<lang>.jsonl.gz``.

Split
    ``split_of(doc_id)``: sha256(doc_id) % 10 < 5 is ``dev``, else ``holdout``. AI documents
    carry the ``doc_id`` of the human document they are matched to, so both sides of a topic
    land in the same split.
"""

from __future__ import annotations

import ast
import re
import threading
import urllib.parse
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ._common import (
    count_words,
    http_get_json,
    iso,
    iter_jsonl,
    load_yaml,
    read_json,
    repo_root,
    seeded_rng,
    sha256_text,
    split_of,
    utc_now,
    write_json,
    write_jsonl,
)
from .budget import BudgetExceeded
from .openrouter import ModelUnavailableError, OpenRouterClient, OpenRouterError

ROWS_URL = "https://datasets-server.huggingface.co/rows"
HUB_API = "https://huggingface.co/api/datasets/"
MAX_ROWS_PER_REQUEST = 100
DOCS_FILE = "docs.jsonl"
MANIFEST_FILE = "manifest.json"
TOKENS_PER_WORD = {"en": 1.4, "de": 1.9}
REASONING_HEADROOM_TOKENS = 1024

__all__ = [
    "derive_topic",
    "fetch_human",
    "generate_ai",
    "load_ai_docs",
    "load_human_docs",
    "load_human_spec",
    "load_prompts",
    "split_of",
]


# ---------------------------------------------------------------------------
# specification


@dataclass
class HumanSource:
    id: str
    language: str
    register: str
    dataset: str
    config: str
    split: str
    adapter: str
    rows: int
    docs: int
    revision: str | None = None
    license: str = ""
    batch: int = 8
    max_date: str | None = None
    max_bucket: str | None = None
    max_per_domain: int | None = None
    truncate: bool = False
    text_field: str = "text"
    title_field: str | None = None
    max_requests: int | None = None
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> HumanSource:
        known = {f for f in cls.__dataclass_fields__ if f != "extra"}
        kwargs = {k: v for k, v in d.items() if k in known}
        extra = {k: v for k, v in d.items() if k not in known}
        missing = [
            k
            for k in ("id", "language", "register", "dataset", "config", "split", "adapter", "rows", "docs")
            if k not in kwargs
        ]
        if missing:
            raise ValueError(f"human corpus source {d.get('id', '?')} lacks {missing}")
        return cls(**kwargs, extra=extra)


def default_spec_path() -> Path:
    return repo_root() / "evals" / "corpus" / "human.yaml"


def load_human_spec(path: str | Path | None = None) -> dict:
    spec = load_yaml(path or default_spec_path()) or {}
    spec["sources"] = [HumanSource.from_dict(s) for s in spec.get("sources") or []]
    spec.setdefault("min_words", 150)
    spec.setdefault("max_words", 1200)
    spec.setdefault("seed", 0)
    spec.setdefault("cutoff_date", "2022-11-01")
    return spec


# ---------------------------------------------------------------------------
# datasets-server access


def fetch_rows(
    dataset: str, config: str, split: str, offset: int, length: int, *, timeout: float = 60.0
) -> list:
    """[(row_idx, row_dict)] from the datasets-server /rows endpoint."""
    length = max(1, min(int(length), MAX_ROWS_PER_REQUEST))
    query = urllib.parse.urlencode(
        {"dataset": dataset, "config": config, "split": split, "offset": int(offset), "length": length}
    )
    data = http_get_json(f"{ROWS_URL}?{query}", timeout=timeout, retries=5, backoff=2.0)
    rows = (data or {}).get("rows") or []
    out = []
    for r in rows:
        if r.get("truncated_cells"):
            continue  # incomplete text; never sample a truncated document
        out.append((int(r["row_idx"]), r.get("row") or {}))
    return out


def dataset_revision(dataset: str, *, timeout: float = 30.0) -> str | None:
    """Current Hub commit sha of a dataset (public endpoint)."""
    try:
        data = http_get_json(HUB_API + urllib.parse.quote(dataset, safe="/"), timeout=timeout, retries=2)
    except Exception:
        return None
    sha = (data or {}).get("sha")
    return str(sha) if sha else None


# ---------------------------------------------------------------------------
# text normalization and adapters

_BLANKS_RE = re.compile(r"\n{3,}")
_TRAILING_WS_RE = re.compile(r"[ \t]+\n")


def normalize_text(text: str, *, lines_are_paragraphs: bool = False) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    text = _TRAILING_WS_RE.sub("\n", text)
    if lines_are_paragraphs:
        lines = [ln.strip() for ln in text.split("\n")]
        text = "\n\n".join(ln for ln in lines if ln)
    text = _BLANKS_RE.sub("\n\n", text)
    return text.strip()


def truncate_paragraphs(text: str, max_words: int) -> str:
    """Leading paragraphs whose total word count stays within max_words."""
    kept: list[str] = []
    total = 0
    for para in text.split("\n\n"):
        n = count_words(para)
        if total + n > max_words:
            break
        kept.append(para)
        total += n
    return "\n\n".join(kept)


def _domain(url: str | None) -> str | None:
    if not url:
        return None
    host = urllib.parse.urlsplit(url).hostname or ""
    return host[4:] if host.startswith("www.") else host or None


def _decode_maybe_bytes_literal(value: str) -> str:
    """wiki40b configs differ: some serve str, some serve the repr of UTF-8 bytes (b'...')."""
    v = value.strip()
    if len(v) >= 3 and v[0] == "b" and v[1] in "'\"" and v[-1] == v[1]:
        try:
            raw = ast.literal_eval(v)
        except (ValueError, SyntaxError):
            return value
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="replace")
    return value


def adapt_fineweb(row: dict, src: HumanSource) -> dict | None:
    date = str(row.get("date") or "")
    if src.max_date and (not date or date[:10] >= src.max_date):
        return None
    text = normalize_text(str(row.get(src.text_field) or ""), lines_are_paragraphs=True)
    return {"text": text, "title": None, "domain": _domain(row.get("url")), "date": date[:10] or None}


def adapt_wiki40b(row: dict, src: HumanSource) -> dict | None:
    raw = _decode_maybe_bytes_literal(str(row.get("text") or ""))
    title = None
    paragraphs: list[str] = []
    lines = raw.split("\n")
    i = 0
    while i < len(lines):
        marker = lines[i].strip()
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if marker == "_START_ARTICLE_":
            title = nxt.strip()
            i += 2
        elif marker == "_START_SECTION_":
            if nxt.strip():
                paragraphs.append(nxt.strip())
            i += 2
        elif marker == "_START_PARAGRAPH_":
            paragraphs.extend(p.strip() for p in nxt.split("_NEWLINE_") if p.strip())
            i += 2
        else:
            i += 1
    text = normalize_text("\n\n".join(paragraphs))
    return {"text": text, "title": title, "domain": "wikipedia.org", "date": None}


_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_SETEXT_RE = re.compile(r"^\s*[=\-]{3,}\s*$", re.MULTILINE)


def strip_markdown_noise(text: str) -> str:
    """Remove images and link targets (forum markup converted to Markdown by the dataset)."""
    text = _MD_IMAGE_RE.sub("", text)
    text = _MD_LINK_RE.sub(r"\1", text)
    return _SETEXT_RE.sub("", text)


def adapt_mqa(row: dict, src: HumanSource) -> dict | None:
    bucket = str(row.get("bucket") or "")
    if src.max_bucket and (not bucket or bucket > src.max_bucket):
        return None
    answers = [
        a
        for a in (row.get("answers") or [])
        if isinstance(a, dict) and a.get("text") and "```" not in str(a["text"])  # code answers are not prose
    ]
    if not answers:
        return None
    accepted = [a for a in answers if a.get("is_accepted")]
    pool = accepted or answers
    best = max(pool, key=lambda a: count_words(str(a["text"])))
    text = normalize_text(strip_markdown_noise(str(best["text"])))
    title = strip_markdown_noise(str(row.get("name") or "")).strip()
    return {"text": text, "title": title or None, "domain": row.get("domain"), "date": bucket or None}


def adapt_plain(row: dict, src: HumanSource) -> dict | None:
    title = str(row.get(src.title_field) or "").strip() if src.title_field else None
    return {
        "text": normalize_text(str(row.get(src.text_field) or "")),
        "title": title or None,
        "domain": None,
        "date": None,
    }


_STOPWORDS = {
    "en": frozenset(
        "the of and to a in is that for it with as was on be by this are or at from have an "
        "not but they you which his her we can has had been their will would there all one".split()
    ),
    "de": frozenset(
        "der die und in den von zu das mit sich des auf für ist im dem nicht ein eine als auch "
        "es an werden aus er hat dass sie nach wird bei einer um am sind noch wie einem über".split()
    ),
}
_LETTER_RE = re.compile(r"[^\W\d_]")


def language_ok(text: str, lang: str, min_share: float = 0.08) -> bool:
    """Cheap stopword check that the text is in ``lang`` (rejects mislabeled dataset rows)."""
    letters = _LETTER_RE.findall(text)
    if not letters:
        return False
    non_latin = sum(1 for ch in letters if ord(ch) > 0x24F)
    if non_latin / len(letters) > 0.05:
        return False
    if lang not in _STOPWORDS:
        return True
    words = [w.lower() for w in re.findall(r"\w+", text)]
    if not words:
        return False
    shares = {k: sum(1 for w in words if w in sw) / len(words) for k, sw in _STOPWORDS.items()}
    target = shares[lang]
    return target >= min_share and all(target > v for k, v in shares.items() if k != lang)


def repetition_ok(text: str, max_dup_share: float = 0.3) -> bool:
    """Reject pages made of repeated lines or sentences (spam, scraped templates)."""
    units = [u.strip().lower() for u in re.split(r"\n+|(?<=[.!?])\s+", text) if len(u.strip()) > 20]
    if len(units) < 3:
        return True
    return (len(units) - len(set(units))) / len(units) <= max_dup_share


def table_ok(text: str, max_share: float = 0.2) -> bool:
    """Reject documents dominated by table rows (record listings are not prose)."""
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if not lines:
        return False
    return sum(1 for ln in lines if ln.count("|") >= 2) / len(lines) <= max_share


def prose_ok(text: str, min_letter_share: float = 0.85) -> bool:
    """Reject markup, formulas and code: letters must dominate the non-space characters."""
    chars = [ch for ch in text if not ch.isspace()]
    if not chars:
        return False
    return sum(1 for ch in chars if ch.isalpha()) / len(chars) >= min_letter_share


ADAPTERS: dict[str, Callable[[dict, HumanSource], dict | None]] = {
    "fineweb": adapt_fineweb,
    "wiki40b": adapt_wiki40b,
    "mqa": adapt_mqa,
    "plain": adapt_plain,
}


# ---------------------------------------------------------------------------
# human corpus


def make_doc_id(src: HumanSource, row_idx: int) -> str:
    return f"{src.language}-{src.register}-{src.id}-{row_idx}"


def sample_source(
    src: HumanSource,
    spec: dict,
    *,
    rows_fn: Callable[..., list] = fetch_rows,
    seen_hashes: set[str] | None = None,
    log: Callable[[str], None] = lambda _m: None,
    concurrency: int = 4,
) -> list[dict]:
    """Deterministically sample ``src.docs`` documents from one source.

    Offsets come from a PRNG seeded with the spec seed and the source id. Up to ``concurrency``
    requests run at once (cold datasets-server shards can take 20 s), but rows are always
    processed in offset order, so the result does not depend on response timing.
    """
    adapter = ADAPTERS.get(src.adapter)
    if adapter is None:
        raise ValueError(f"unknown adapter {src.adapter!r} for source {src.id}")
    min_w, max_w = int(spec["min_words"]), int(spec["max_words"])
    rng = seeded_rng(spec["seed"], src.id)
    seen_hashes = seen_hashes if seen_hashes is not None else set()
    per_domain: dict[str, int] = {}
    seen_rows: set[int] = set()
    docs: list[dict] = []
    max_requests = src.max_requests or max(50, src.docs * 40)
    batch = max(1, min(src.batch, MAX_ROWS_PER_REQUEST))
    upper = max(1, int(src.rows) - batch + 1)
    requests = 0
    window = max(1, int(concurrency))
    pool = ThreadPoolExecutor(max_workers=window) if window > 1 else None
    pending: list[Any] = []

    def submit() -> None:
        offset = rng.randrange(0, upper)
        if pool is None:
            pending.append(rows_fn(src.dataset, src.config, src.split, offset, batch))
        else:
            pending.append(pool.submit(rows_fn, src.dataset, src.config, src.split, offset, batch))

    try:
        while len(docs) < src.docs:
            if requests >= max_requests:
                raise RuntimeError(
                    f"source {src.id}: only {len(docs)}/{src.docs} documents after {requests} requests; "
                    "relax filters or raise max_requests"
                )
            while len(pending) < window and requests + len(pending) < max_requests:
                submit()
            head = pending.pop(0)
            rows = head if pool is None else head.result()
            requests += 1
            if requests % 50 == 0:
                log(f"{src.id}: {len(docs)}/{src.docs} documents after {requests} requests")
            _accept_rows(rows, src, adapter, min_w, max_w, seen_rows, seen_hashes, per_domain, docs)
    finally:
        if pool is not None:
            for f in pending:
                f.cancel()
            pool.shutdown(wait=True)
    log(f"{src.id}: {len(docs)} documents from {requests} requests")
    return docs


def _accept_rows(
    rows: list,
    src: HumanSource,
    adapter: Callable[[dict, HumanSource], dict | None],
    min_w: int,
    max_w: int,
    seen_rows: set[int],
    seen_hashes: set[str],
    per_domain: dict[str, int],
    docs: list[dict],
) -> None:
    for row_idx, row in rows:
        if row_idx in seen_rows or len(docs) >= src.docs:
            continue
        seen_rows.add(row_idx)
        adapted = adapter(row, src)
        if not adapted or not adapted.get("text"):
            continue
        text = adapted["text"]
        if "\ufffd" in text:
            continue  # mojibake
        if not (
            language_ok(text, src.language) and prose_ok(text) and repetition_ok(text) and table_ok(text)
        ):
            continue
        words = count_words(text)
        if words > max_w and src.truncate:
            text = truncate_paragraphs(text, max_w)
            words = count_words(text)
        if words < min_w or words > max_w:
            continue
        domain = adapted.get("domain")
        if src.max_per_domain and domain and per_domain.get(domain, 0) >= src.max_per_domain:
            continue
        digest = sha256_text(text)
        if digest in seen_hashes:
            continue
        seen_hashes.add(digest)
        if domain:
            per_domain[domain] = per_domain.get(domain, 0) + 1
        doc_id = make_doc_id(src, row_idx)
        docs.append(
            {
                "doc_id": doc_id,
                "language": src.language,
                "register": src.register,
                "source": src.id,
                "dataset": src.dataset,
                "config": src.config,
                "hf_split": src.split,
                "row_idx": row_idx,
                "title": adapted.get("title"),
                "date": adapted.get("date"),
                "words": words,
                "sha256": digest,
                "split": split_of(doc_id),
                "text": text,
            }
        )


def fetch_human(
    out_dir: str | Path,
    spec: dict | None = None,
    *,
    rows_fn: Callable[..., list] = fetch_rows,
    revision_fn: Callable[[str], str | None] = dataset_revision,
    strict_revision: bool = False,
    only: Iterable[str] | None = None,
    log: Callable[[str], None] = lambda _m: None,
) -> dict:
    """Fetch the human corpus into ``out_dir`` (docs.jsonl + manifest.json). Returns the manifest."""
    spec = spec or load_human_spec()
    out = Path(out_dir)
    only_set = set(only or [])
    sources: list[HumanSource] = [s for s in spec["sources"] if not only_set or s.id in only_set]
    notices: list[str] = []
    datasets_info = []
    observed: dict[str, str | None] = {}
    for src in sources:
        if src.dataset not in observed:
            observed[src.dataset] = revision_fn(src.dataset)
        rev = observed[src.dataset]
        if src.revision and rev and rev != src.revision:
            msg = (
                f"{src.id}: dataset {src.dataset} is at revision {rev}, pinned {src.revision}; "
                "datasets-server serves the current revision"
            )
            if strict_revision:
                raise RuntimeError(msg)
            notices.append(msg)
        datasets_info.append(
            {
                "source": src.id,
                "dataset": src.dataset,
                "config": src.config,
                "hf_split": src.split,
                "language": src.language,
                "register": src.register,
                "license": src.license,
                "pinned_revision": src.revision,
                "observed_revision": rev,
                "adapter": src.adapter,
                "rows": src.rows,
            }
        )
    seen_hashes: set[str] = set()
    all_docs: list[dict] = []
    for src in sources:
        all_docs.extend(sample_source(src, spec, rows_fn=rows_fn, seen_hashes=seen_hashes, log=log))
    revisions = {d["source"]: d["observed_revision"] or d["pinned_revision"] for d in datasets_info}
    write_jsonl(out / DOCS_FILE, all_docs)
    counts: dict[str, dict[str, int]] = {}
    for d in all_docs:
        counts.setdefault(d["language"], {}).setdefault(d["register"], 0)
        counts[d["language"]][d["register"]] += 1
    manifest = {
        "created_at": iso(utc_now()),
        "spec": {
            k: spec[k] for k in ("version", "cutoff_date", "seed", "min_words", "max_words") if k in spec
        },
        "datasets": datasets_info,
        "counts": counts,
        "notices": notices,
        "documents": [
            {
                "doc_id": d["doc_id"],
                "dataset": d["dataset"],
                "config": d["config"],
                "hf_split": d["hf_split"],
                "revision": revisions.get(d["source"]),
                "row_idx": d["row_idx"],
                "register": d["register"],
                "language": d["language"],
                "words": d["words"],
                "sha256": d["sha256"],
                "split": d["split"],
            }
            for d in all_docs
        ],
    }
    write_json(out / MANIFEST_FILE, manifest)
    for n in notices:
        log(f"notice: {n}")
    return manifest


def load_human_docs(human_dir: str | Path, *, verify: bool = True) -> list[dict]:
    """Documents from docs.jsonl; with ``verify``, drop any whose hash differs from manifest.json."""
    base = Path(human_dir)
    path = base / DOCS_FILE
    if not path.is_file() and (base / (DOCS_FILE + ".gz")).is_file():
        path = base / (DOCS_FILE + ".gz")
    docs = list(iter_jsonl(path))
    if verify and (base / MANIFEST_FILE).is_file():
        manifest = read_json(base / MANIFEST_FILE)
        expected = {d["doc_id"]: d["sha256"] for d in manifest.get("documents") or []}
        docs = [d for d in docs if expected.get(d["doc_id"]) == sha256_text(d["text"])]
    for d in docs:
        d.setdefault("split", split_of(d["doc_id"]))
        d.setdefault("source_kind", "human")
    return docs


# ---------------------------------------------------------------------------
# topics and prompts

_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_HANDLE_RE = re.compile(r"(?<!\w)@\w+")
_PHONE_RE = re.compile(r"\+?\d[\d ()/.-]{7,}\d")
_TITLE_SITE_RE = re.compile(r"\s+(?:\||::|»|·)\s+")
_SENT_END_RE = re.compile(r"(?<=[.!?…])\s+(?=[\"'„“A-ZÄÖÜ0-9])")
_CLAUSE_RE = re.compile(r"(?<=[,;:])\s+|\s+[–—]\s+")


def clean_topic(text: str) -> str:
    t = _URL_RE.sub(" ", text or "")
    t = _EMAIL_RE.sub(" ", t)
    t = _HANDLE_RE.sub(" ", t)
    t = _PHONE_RE.sub(" ", t)
    t = _TITLE_SITE_RE.split(t)[0]
    t = re.sub(r"\(/[^)\s]*\)", " ", t)  # site-relative link targets
    t = re.sub(r"[=~^]{2,}", " ", t)
    t = re.sub(r"[#*_`>\[\]{}]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t.strip(" -–—:;,.|")


def first_sentence(text: str) -> str:
    para = next((p for p in text.split("\n\n") if p.strip()), text)
    return _SENT_END_RE.split(para.strip(), maxsplit=1)[0]


def _shorten(text: str, max_words: int) -> str:
    if count_words(text) <= max_words:
        return text
    kept: list[str] = []
    for clause in _CLAUSE_RE.split(text):
        candidate = " ".join([*kept, clause])
        if count_words(candidate) > max_words:
            break
        kept.append(clause)
    if kept:
        return " ".join(kept).strip(" ,;:")
    return " ".join(text.split()[:max_words])


def derive_topic(doc: dict, max_words: int = 20) -> str:
    """Deterministic topic: title, else a short first line, else the (shortened) first sentence."""
    text = doc.get("text") or ""
    first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    for candidate in (doc.get("title") or "", first_line):
        t = clean_topic(candidate)
        if 2 <= count_words(t) <= max_words:
            return t
    sentence = clean_topic(first_sentence(text))
    return clean_topic(_shorten(sentence, max_words)) or clean_topic(first_line)[:160]


def target_words(doc: dict, lo: int = 150, hi: int = 1200) -> int:
    n = int(doc.get("words") or count_words(doc.get("text") or ""))
    return max(lo, min(hi, round(n / 10.0) * 10))


def default_prompts_dir() -> Path:
    return repo_root() / "evals" / "corpus" / "prompts"


def load_prompts(prompts_dir: str | Path | None = None) -> dict[str, list[dict]]:
    """{language: [prompt, ...]} from prompts/*.yaml."""
    base = Path(prompts_dir) if prompts_dir else default_prompts_dir()
    out: dict[str, list[dict]] = {}
    for f in sorted(base.glob("*.yaml")):
        data = load_yaml(f) or {}
        lang = data.get("language")
        for p in data.get("prompts") or []:
            p = dict(p)
            p.setdefault("language", lang)
            if not p.get("id") or not p.get("user") or not p.get("human_registers"):
                raise ValueError(f"{f.name}: prompt needs id, user and human_registers")
            out.setdefault(p["language"], []).append(p)
    return out


def choose_prompt(doc: dict, prompts: list[dict]) -> dict:
    candidates = [p for p in prompts if doc["register"] in p["human_registers"]]
    if not candidates:
        raise ValueError(f"no prompt for language {doc['language']} and register {doc['register']}")
    candidates.sort(key=lambda p: p["id"])
    return candidates[int(sha256_text("prompt:" + doc["doc_id"]), 16) % len(candidates)]


def build_messages(prompt: dict, topic: str, words: int) -> list[dict]:
    values = {"topic": topic, "words": words}
    messages = []
    if prompt.get("system"):
        messages.append({"role": "system", "content": str(prompt["system"]).format(**values).strip()})
    messages.append({"role": "user", "content": str(prompt["user"]).format(**values).strip()})
    return messages


def slug_dir(canonical_slug: str) -> str:
    return canonical_slug.replace("/", "__").replace(":", "_")


def generation_order(docs: list[dict]) -> list[dict]:
    """Stable topic order shared by all generators, so smaller budgets use a prefix."""
    return sorted(docs, key=lambda d: sha256_text("gen:" + d["doc_id"]))


# ---------------------------------------------------------------------------
# AI corpus


@dataclass
class GenerationSummary:
    generated: int = 0
    reused: int = 0
    failed: int = 0
    aborted: bool = False
    abort_reason: str = ""
    per_model: dict = field(default_factory=dict)
    notices: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "generated": self.generated,
            "reused": self.reused,
            "failed": self.failed,
            "aborted": self.aborted,
            "abort_reason": self.abort_reason,
            "per_model": self.per_model,
            "notices": self.notices,
        }


def _existing(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    return {r["doc_id"]: r for r in iter_jsonl(path) if r.get("doc_id") and r.get("text")}


def generate_ai(
    human_docs: list[dict],
    out_dir: str | Path,
    generators: list[dict],
    client: OpenRouterClient,
    *,
    prompts: dict[str, list[dict]] | None = None,
    languages: Iterable[str] | None = None,
    limit: int | None = None,
    workers: int = 4,
    refresh: Callable[[dict, set[str]], dict | None] | None = None,
    log: Callable[[str], None] = lambda _m: None,
) -> GenerationSummary:
    """Generate (or complete) the AI corpus for every generator entry of the lock."""
    prompts = prompts if prompts is not None else load_prompts()
    out = Path(out_dir)
    langs = sorted(set(languages or {d["language"] for d in human_docs}))
    summary = GenerationSummary()
    stop = threading.Event()

    for entry in generators:
        current = entry
        failed_ids: set[str] = set()
        for lang in langs:
            if stop.is_set():
                break
            pool = generation_order([d for d in human_docs if d["language"] == lang])
            n = int(current.get("docs_per_language") or len(pool))
            if limit is not None:
                n = min(n, int(limit))
            todo_docs = pool[:n]
            while True:
                slug = current.get("canonical_slug") or current["id"]
                path = out / slug_dir(slug) / f"{lang}.jsonl.gz"
                records = _existing(path)
                todo = [d for d in todo_docs if d["doc_id"] not in records]
                summary.reused += len(todo_docs) - len(todo)
                unavailable = _generate_batch(
                    todo, current, lang, prompts, client, records, summary, stop, workers, log
                )
                ordered = [records[d["doc_id"]] for d in todo_docs if d["doc_id"] in records]
                if ordered:
                    write_jsonl(path, ordered)
                stats = summary.per_model.setdefault(
                    slug, {"id": current["id"], "family": current.get("family")}
                )
                stats[lang] = len(ordered)
                if not unavailable:
                    break
                failed_ids.add(current["id"])
                replacement = refresh(current, failed_ids) if refresh else None
                if not replacement or replacement["id"] in failed_ids:
                    summary.notices.append(
                        f"{current.get('key')}: {current['id']} unavailable; no replacement"
                    )
                    break
                summary.notices.append(
                    f"{current.get('key')}: {current['id']} unavailable; now {replacement['id']}"
                )
                current = replacement
    return summary


def _generate_batch(
    todo: list[dict],
    entry: dict,
    lang: str,
    prompts: dict[str, list[dict]],
    client: OpenRouterClient,
    records: dict[str, dict],
    summary: GenerationSummary,
    stop: threading.Event,
    workers: int,
    log: Callable[[str], None],
) -> bool:
    """Generate ``todo`` into ``records``. Returns True if the model turned out unavailable."""
    lang_prompts = prompts.get(lang) or []
    unavailable = threading.Event()
    lock = threading.Lock()
    tpw = TOKENS_PER_WORD.get(lang, 1.8)

    def one(doc: dict) -> None:
        if stop.is_set() or unavailable.is_set():
            return
        prompt = choose_prompt(doc, lang_prompts)
        topic = derive_topic(doc)
        words = target_words(doc)
        messages = build_messages(prompt, topic, words)
        max_tokens = int(words * tpw * 1.5) + REASONING_HEADROOM_TOKENS
        try:
            res = client.chat(entry, messages, max_tokens=max_tokens, role="generators")
        except BudgetExceeded as exc:
            stop.set()
            with lock:
                summary.aborted = True
                summary.abort_reason = str(exc)
            return
        except ModelUnavailableError as exc:
            unavailable.set()
            log(f"{entry['id']}: unavailable ({exc})")
            return
        except OpenRouterError as exc:
            with lock:
                summary.failed += 1
            log(f"{entry['id']} {doc['doc_id']}: {exc}")
            return
        text = (res.text or "").strip()
        if count_words(text) < 50:
            with lock:
                summary.failed += 1
            log(f"{entry['id']} {doc['doc_id']}: output too short (finish_reason={res.finish_reason})")
            return
        rec = {
            "doc_id": doc["doc_id"],
            "model": entry["id"],
            "canonical_slug": entry.get("canonical_slug") or entry["id"],
            "family": entry.get("family"),
            "tier": entry.get("tier"),
            "language": lang,
            "register": prompt.get("register"),
            "human_register": doc["register"],
            "prompt_id": prompt["id"],
            "topic": topic,
            "target_words": words,
            "words": count_words(text),
            "finish_reason": res.finish_reason,
            "served_model": res.model,
            "usd": round(res.usd, 8),
            "generated_at": iso(utc_now()),
            "text": text,
        }
        with lock:
            records[doc["doc_id"]] = rec
            summary.generated += 0 if res.cached else 1
            summary.reused += 1 if res.cached else 0

    if workers <= 1:
        for d in todo:
            one(d)
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(one, d) for d in todo]
            for f in as_completed(futures):
                f.result()
    return unavailable.is_set()


def load_ai_docs(ai_dir: str | Path, *, slugs: set[str] | None = None) -> list[dict]:
    """AI documents from ``<ai_dir>/<slug>/<lang>.jsonl(.gz)``; optionally only given canonical slugs."""
    base = Path(ai_dir)
    docs: list[dict] = []
    files = sorted([*base.glob("*/*.jsonl.gz"), *base.glob("*/*.jsonl")])
    for f in files:
        for rec in iter_jsonl(f):
            if not rec.get("text") or not rec.get("doc_id"):
                continue
            if slugs is not None and rec.get("canonical_slug") not in slugs:
                continue
            rec.setdefault("split", split_of(rec["doc_id"]))
            rec["source_kind"] = "ai"
            docs.append(rec)
    return docs


def summarize_docs(docs: list[dict]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for d in docs:
        out.setdefault(d["language"], 0)
        out[d["language"]] += 1
    return dict(sorted(out.items()))
