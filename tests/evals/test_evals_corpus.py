from __future__ import annotations

import gzip
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from slopcheck_dev.evals import corpus as C
from slopcheck_dev.evals._common import sha256_text, split_of
from slopcheck_dev.evals.budget import BudgetExceeded
from slopcheck_dev.evals.openrouter import ChatResult, ModelUnavailableError

EN_PARA = (
    "The bridge was opened in 1932 and carried trams until the line closed in 1961. It was built by a "
    "local firm with steel from a mill upriver, and the town paid for it with a loan that took thirty years "
    "to repay. In the winter of 1947 the river froze so hard that people walked across the ice beside it. "
)
DE_PARA = (
    "Die Brücke wurde 1932 eröffnet und von der Straßenbahn genutzt, bis die Linie 1961 eingestellt wurde. "
    "Sie wurde von einer Firma aus der Stadt gebaut, und die Gemeinde hat das Darlehen erst nach dreißig "
    "Jahren zurückgezahlt. Im Winter 1947 war der Fluss so fest zugefroren, dass man über das Eis ging. "
)


NOUNS = [
    "the bridge",
    "the town",
    "a farmer",
    "the river",
    "the council",
    "a teacher",
    "the mill",
    "the road",
]
VERBS = ["built", "crossed", "repaired", "watched", "sold", "painted", "measured", "closed"]
TAILS = [
    "in the spring of",
    "after the flood of",
    "before the war in",
    "during the winter of",
    "for the fair in",
]


def varied_en(n, seed):
    """Distinct English sentences (no repeats), about 26 words each."""
    import random

    rng = random.Random(seed)
    paras = []
    for i in range(n):
        sents = []
        for j in range(3):
            year = 1900 + rng.randrange(100)
            sents.append(
                f"In {year} {rng.choice(NOUNS)} {rng.choice(VERBS)} {rng.choice(NOUNS)} {rng.choice(TAILS)} "
                f"{year + 1}, and it was the {seed}th time that this had happened to them on day {i}-{j}."
            )
        paras.append(" ".join(sents))
    return "\n\n".join(paras)


# ---------------------------------------------------------------------------
# split


def test_split_rule_matches_contract():
    for doc_id in ("a", "en-web-x-1", "de-qa-y-99"):
        expected = "dev" if int(sha256_text(doc_id), 16) % 10 < 5 else "holdout"
        assert split_of(doc_id) == expected == C.split_of(doc_id)
    ids = [f"doc-{i}" for i in range(2000)]
    dev = sum(1 for i in ids if split_of(i) == "dev")
    assert 900 < dev < 1100


# ---------------------------------------------------------------------------
# adapters and filters


def src(**kw):
    base = {
        "id": "s",
        "language": "en",
        "register": "web",
        "dataset": "d",
        "config": "c",
        "split": "train",
        "adapter": "fineweb",
        "rows": 100,
        "docs": 2,
    }
    base.update(kw)
    return C.HumanSource.from_dict(base)


def test_fineweb_adapter_date_and_paragraphs():
    s = src(max_date="2020-06-01")
    row = {
        "text": "Title line\nFirst block.\n\nSecond block.",
        "date": "2019-04-19T15:22:30Z",
        "url": "https://www.example.org/a",
    }
    out = C.adapt_fineweb(row, s)
    assert out["text"] == "Title line\n\nFirst block.\n\nSecond block."
    assert out["domain"] == "example.org" and out["date"] == "2019-04-19"
    assert C.adapt_fineweb({**row, "date": "2021-01-01T00:00:00Z"}, s) is None
    assert C.adapt_fineweb({**row, "date": ""}, s) is None


def test_wiki40b_adapter_decodes_bytes_literal_and_markers():
    raw = (
        "\n_START_ARTICLE_\nDale Peck\n_START_SECTION_\nLeben\n"
        "_START_PARAGRAPH_\nEr zog nach Kansas._NEWLINE_Sp\xe4ter mehr."
    )
    as_bytes = "b" + repr(raw.encode("utf-8"))[1:]
    for value in (raw, as_bytes):
        out = C.adapt_wiki40b({"text": value}, src(adapter="wiki40b", language="de"))
        assert out["title"] == "Dale Peck"
        assert out["text"] == "Leben\n\nEr zog nach Kansas.\n\nSpäter mehr."


def test_mqa_adapter_prefers_accepted_and_filters():
    s = src(adapter="mqa", max_bucket="2021.52")
    row = {
        "name": "How do I X? ===",
        "bucket": "2020.16",
        "domain": "forum.example",
        "answers": [
            {"text": "short", "is_accepted": False},
            {
                "text": "Accepted [link](http://x.y) ![img](data:image/gif;base64,AAAA) answer.",
                "is_accepted": True,
            },
        ],
    }
    out = C.adapt_mqa(row, s)
    assert out["text"] == "Accepted link  answer."
    assert out["title"] == "How do I X? ==="
    assert C.adapt_mqa({**row, "bucket": "2022.21"}, s) is None
    code_only = {**row, "answers": [{"text": "```\ncode\n```", "is_accepted": True}]}
    assert C.adapt_mqa(code_only, s) is None


def test_text_filters():
    assert C.language_ok(EN_PARA * 3, "en") and not C.language_ok(EN_PARA * 3, "de")
    assert C.language_ok(DE_PARA * 3, "de") and not C.language_ok(DE_PARA * 3, "en")
    assert not C.language_ok("Почти так же, как и раньше, только быстрее и проще.", "en")
    assert C.prose_ok(EN_PARA) and not C.prose_ok("\\(x^{2}+{3}{x}\\) = {5} \\\\ {7}")
    assert C.repetition_ok(EN_PARA)
    assert not C.repetition_ok("\n".join(["The same long sentence repeated here."] * 6))
    assert C.table_ok(EN_PARA) and not C.table_ok("| a | b |\n| c | d |\n| e | f |")


def test_truncate_paragraphs():
    text = "\n\n".join(["one two three"] * 5)
    assert C.truncate_paragraphs(text, 7) == "one two three\n\none two three"


# ---------------------------------------------------------------------------
# sampling


def fake_rows(rows_by_idx):
    calls = []

    def rows_fn(dataset, config, split, offset, length):
        calls.append(offset)
        return [(i, rows_by_idx[i]) for i in range(offset, offset + length) if i in rows_by_idx]

    rows_fn.calls = calls
    return rows_fn


def corpus_rows(n=60):
    rows = {}
    for i in range(n):
        if i % 5 == 0:
            text = "too short text"
        else:
            text = varied_en(3, i)
        rows[i] = {"text": text, "date": "2019-01-01T00:00:00Z", "url": f"https://site{i % 7}.example/{i}"}
    return rows


def spec_with(source, seed=1):
    return {"seed": seed, "min_words": 150, "max_words": 1200, "sources": [source]}


def test_sample_source_is_deterministic_and_filters():
    rows = corpus_rows()
    s = src(docs=5, batch=3, rows=60, max_date="2020-06-01")
    a = C.sample_source(s, spec_with(s, seed=7), rows_fn=fake_rows(rows))
    b = C.sample_source(s, spec_with(s, seed=7), rows_fn=fake_rows(rows))
    c = C.sample_source(s, spec_with(s, seed=8), rows_fn=fake_rows(rows))
    assert [d["doc_id"] for d in a] == [d["doc_id"] for d in b]
    assert [d["doc_id"] for d in a] != [d["doc_id"] for d in c]
    assert len(a) == 5
    for d in a:
        assert d["row_idx"] % 5 != 0  # short rows filtered
        assert 150 <= d["words"] <= 1200
        assert d["sha256"] == sha256_text(d["text"])
        assert d["split"] == split_of(d["doc_id"])
        assert d["doc_id"] == f"en-web-s-{d['row_idx']}"


def test_sample_source_domain_cap_and_truncation():
    rows = corpus_rows()
    s = src(docs=7, batch=5, rows=60, max_per_domain=1)
    docs = C.sample_source(s, spec_with(s), rows_fn=fake_rows(rows))
    assert len({d["row_idx"] % 7 for d in docs}) == len(docs) == 7
    long_rows = {
        i: {
            "text": "\n_START_ARTICLE_\nT\n"
            + "".join(f"_START_PARAGRAPH_\n{p}\n" for p in varied_en(30, i).split("\n\n"))
        }
        for i in range(10)
    }
    w = src(adapter="wiki40b", docs=2, batch=2, rows=10, truncate=True)
    docs = C.sample_source(w, spec_with(w), rows_fn=fake_rows(long_rows))
    assert all(d["words"] <= 1200 for d in docs) and all(d["title"] == "T" for d in docs)


def test_sample_source_gives_up():
    s = src(docs=3, batch=2, rows=10, max_requests=5)
    with pytest.raises(RuntimeError, match="only 0/3"):
        C.sample_source(s, spec_with(s), rows_fn=lambda *a: [])


def test_fetch_human_writes_manifest_without_texts(tmp_path):
    rows = corpus_rows()
    s1 = src(id="web-en", docs=3, batch=3, rows=60, revision="abc")
    s2 = src(id="web-en-2", docs=2, batch=3, rows=60, revision="abc", register="qa")
    spec = {
        "seed": 3,
        "min_words": 150,
        "max_words": 1200,
        "cutoff_date": "2022-11-01",
        "version": 1,
        "sources": [s1, s2],
    }
    manifest = C.fetch_human(tmp_path, spec, rows_fn=fake_rows(rows), revision_fn=lambda d: "def")
    assert manifest["counts"] == {"en": {"web": 3, "qa": 2}}
    assert manifest["notices"] and "pinned abc" in manifest["notices"][0]
    raw = (tmp_path / "manifest.json").read_text()
    assert "Paragraph" not in raw  # no text in the manifest
    doc = manifest["documents"][0]
    assert set(doc) >= {"doc_id", "dataset", "revision", "row_idx", "register", "language", "sha256", "split"}
    assert doc["revision"] == "def"
    docs = C.load_human_docs(tmp_path)
    assert len(docs) == 5 and len({d["sha256"] for d in docs}) == 5  # deduplicated across sources
    with pytest.raises(RuntimeError, match="pinned"):
        C.fetch_human(
            tmp_path, spec, rows_fn=fake_rows(rows), revision_fn=lambda d: "def", strict_revision=True
        )


def test_load_human_docs_drops_tampered(tmp_path):
    rows = corpus_rows()
    s = src(docs=2, batch=3, rows=60)
    C.fetch_human(tmp_path, spec_with(s), rows_fn=fake_rows(rows), revision_fn=lambda d: None)
    lines = (tmp_path / "docs.jsonl").read_text().splitlines()
    first = json.loads(lines[0])
    first["text"] += " changed"
    (tmp_path / "docs.jsonl").write_text("\n".join([json.dumps(first), *lines[1:]]) + "\n")
    assert len(C.load_human_docs(tmp_path)) == 1
    assert len(C.load_human_docs(tmp_path, verify=False)) == 2


def test_fetch_rows_builds_url_and_skips_truncated(fake_http):
    payload = {
        "rows": [
            {"row_idx": 5, "row": {"text": "a"}, "truncated_cells": []},
            {"row_idx": 6, "row": {"text": "b"}, "truncated_cells": ["text"]},
        ]
    }
    fake_http.add("datasets-server.huggingface.co/rows", payload)
    out = C.fetch_rows("org/name", "cfg", "test", 5, 2)
    assert out == [(5, {"text": "a"})]
    q = parse_qs(urlsplit(fake_http.requests[0].full_url).query)
    assert q == {
        "dataset": ["org/name"],
        "config": ["cfg"],
        "split": ["test"],
        "offset": ["5"],
        "length": ["2"],
    }


def test_dataset_revision(fake_http):
    fake_http.add("huggingface.co/api/datasets/org/name", {"sha": "1234"})
    assert C.dataset_revision("org/name") == "1234"


def test_repository_spec_loads():
    spec = C.load_human_spec()
    langs = {}
    for s in spec["sources"]:
        langs.setdefault(s.language, {}).setdefault(s.register, 0)
        langs[s.language][s.register] += s.docs
        assert s.adapter in C.ADAPTERS and s.revision and s.license
    for lang in ("de", "en"):
        assert set(langs[lang]) == {"web", "encyclopedic", "qa"}
        assert sum(langs[lang].values()) >= 200
    assert spec["cutoff_date"] == "2022-11-01"


# ---------------------------------------------------------------------------
# topics and prompts


def test_derive_topic():
    assert C.derive_topic({"title": "Faversham Abbey", "text": EN_PARA}) == "Faversham Abbey"
    doc = {"title": None, "text": "Direktflug München - Rijeka ab 96 € | Billigflug finden\n\nText."}
    assert C.derive_topic(doc) == "Direktflug München - Rijeka ab 96 €"
    long_first = {
        "text": (
            "The Northern Foundation opened its scholarship application cycle for the 2018-2019 "
            "academic year, and the director hopes this year will provide more funds. More text."
        )
    }
    topic = C.derive_topic(long_first)
    assert topic.startswith("The Northern Foundation opened") and len(topic.split()) <= 20
    noisy = {"title": "Visit https://example.com or mail info@example.com today ===", "text": EN_PARA}
    assert C.derive_topic(noisy) == "Visit or mail today"


def test_derive_topic_lemma_dateline_quotes_and_boilerplate():
    assert C.derive_topic({"title": "Tertiärquarzit", "text": DE_PARA}) == "Tertiärquarzit"
    dateline = {"text": "Eschenbach. In der Nacht zum Montag wurde ein Kind gefunden. Mehr Text folgt hier."}
    assert C.derive_topic(dateline) == "Eschenbach. In der Nacht zum Montag wurde ein Kind gefunden"
    quoted = {"title": "", "text": '> sind relativ einfach umzuziehen ")\n\nDas Display war nur geklebt.'}
    assert C.derive_topic(quoted) == "Das Display war nur geklebt"
    cookie = {
        "text": "Um alle Funktionen dieser Seite zu nutzen, aktivieren Sie bitte die Cookies in Ihrem Browser.\n\n"
        "Neue Messgeräte für die Biotechnologie\n\nText."
    }
    assert C.derive_topic(cookie) == "Neue Messgeräte für die Biotechnologie"
    plain = {"text": "Chocolate chip cookies keep for a week in a tin.\n\nMore text."}
    assert C.derive_topic(plain) == "Chocolate chip cookies keep for a week in a tin"


def test_machine_translated_pages_are_rejected():
    assert C.human_written_ok(DE_PARA) and C.human_written_ok(EN_PARA)
    assert not C.human_written_ok("Wichtig: Dieser Artikel wurde maschinell und nicht von einem Menschen übersetzt.")
    assert not C.human_written_ok("This page was machine-translated from the German original.")
    assert C.human_written_ok("The novel was translated into twelve languages by human translators.")
    rows = [(1, {"text": "Dieser Artikel wurde automatisch übersetzt.\n" + DE_PARA * 6})]
    docs: list = []
    C._accept_rows(rows, src(language="de"), C.adapt_plain, 50, 1200, set(), set(), {}, docs)
    assert docs == []


def test_target_words():
    assert C.target_words({"words": 267}) == 270
    assert C.target_words({"words": 90}) == 150
    assert C.target_words({"words": 5000}) == 1200


def test_repository_prompts_cover_all_registers():
    prompts = C.load_prompts()
    for lang in ("de", "en"):
        regs = {r for p in prompts[lang] for r in p["human_registers"]}
        assert regs >= {"web", "encyclopedic", "qa"}
        for p in prompts[lang]:
            msg = C.build_messages(p, "Topic", 300)
            assert "Topic" in msg[-1]["content"] and "300" in msg[-1]["content"]


def test_choose_prompt_deterministic():
    prompts = C.load_prompts()["en"]
    doc = {"doc_id": "en-web-x-1", "language": "en", "register": "web"}
    assert C.choose_prompt(doc, prompts)["id"] == C.choose_prompt(doc, prompts)["id"]
    assert C.choose_prompt({**doc, "register": "qa"}, prompts)["id"] == "en-explainer"
    with pytest.raises(ValueError):
        C.choose_prompt({**doc, "register": "poetry"}, prompts)


# ---------------------------------------------------------------------------
# AI generation


class FakeClient:
    def __init__(self, fail_after=None, unavailable=(), text=None):
        self.calls = []
        self.fail_after = fail_after
        self.unavailable = set(unavailable)
        self.text = text or ("Generated text about the topic. " * 20)

    def chat(self, model, messages, max_tokens=1024, role="x", params=None):
        if model["id"] in self.unavailable:
            raise ModelUnavailableError("gone")
        if self.fail_after is not None and len(self.calls) >= self.fail_after:
            raise BudgetExceeded("cap", cap="run", limit=1, would_be=2)
        self.calls.append((model["id"], messages, max_tokens))
        return ChatResult(
            text=self.text,
            model=model["id"],
            canonical_slug=model.get("canonical_slug"),
            usd=0.001,
            finish_reason="stop",
        )


def human_docs(n=6):
    docs = []
    for i in range(n):
        lang = "en" if i % 2 == 0 else "de"
        docs.append(
            {
                "doc_id": f"{lang}-web-s-{i}",
                "language": lang,
                "register": "web",
                "title": f"Topic {i}",
                "text": EN_PARA * 3,
                "words": 240,
                "split": split_of(f"{lang}-web-s-{i}"),
            }
        )
    return docs


GEN = {
    "key": "generators/acme/cheap",
    "family": "acme",
    "tier": "cheap",
    "id": "acme/a",
    "canonical_slug": "acme/a-1",
    "docs_per_language": 2,
}


def test_generate_ai_writes_records_and_resumes(tmp_path):
    fc = FakeClient()
    s = C.generate_ai(human_docs(), tmp_path, [GEN], fc, workers=1)
    assert s.generated == 4 and not s.aborted
    path = tmp_path / "acme__a-1" / "en.jsonl.gz"
    recs = [json.loads(line) for line in gzip.open(path, "rt", encoding="utf-8")]
    assert len(recs) == 2
    r = recs[0]
    for key in ("doc_id", "model", "canonical_slug", "family", "language", "register", "prompt_id", "text"):
        assert r[key]
    assert r["model"] == "acme/a" and r["family"] == "acme" and r["target_words"] == 240
    assert r["topic"].startswith("Topic")
    assert "about 240 words" in fc.calls[0][1][-1]["content"] or "240" in fc.calls[0][1][-1]["content"]
    fc2 = FakeClient()
    s2 = C.generate_ai(human_docs(), tmp_path, [GEN], fc2, workers=2)
    assert fc2.calls == [] and s2.reused == 4
    docs = C.load_ai_docs(tmp_path)
    assert len(docs) == 4 and all(d["source_kind"] == "ai" for d in docs)
    assert C.load_ai_docs(tmp_path, slugs={"other"}) == []


def test_generate_ai_shared_topic_order(tmp_path):
    fc = FakeClient()
    big = dict(GEN, id="acme/b", canonical_slug="acme/b-1", docs_per_language=3)
    C.generate_ai(human_docs(), tmp_path, [GEN, big], fc, workers=1)
    small = {d["doc_id"] for d in C.load_ai_docs(tmp_path, slugs={"acme/a-1"})}
    large = {d["doc_id"] for d in C.load_ai_docs(tmp_path, slugs={"acme/b-1"})}
    assert small < large


def test_generate_ai_budget_abort(tmp_path):
    s = C.generate_ai(human_docs(), tmp_path, [GEN], FakeClient(fail_after=1), workers=1)
    assert s.aborted and "cap" in s.abort_reason
    assert len(C.load_ai_docs(tmp_path)) == 1


def test_generate_ai_replaces_unavailable_model(tmp_path):
    replacement = dict(GEN, id="acme/c", canonical_slug="acme/c-1")
    seen = []

    def refresh(entry, failed):
        seen.append(set(failed))
        return replacement

    s = C.generate_ai(
        human_docs(), tmp_path, [GEN], FakeClient(unavailable={"acme/a"}), workers=1, refresh=refresh
    )
    assert seen and "acme/a" in seen[0]
    assert {d["canonical_slug"] for d in C.load_ai_docs(tmp_path)} == {"acme/c-1"}
    assert any("now acme/c" in n for n in s.notices)


def test_generate_ai_rejects_short_output(tmp_path):
    s = C.generate_ai(human_docs(), tmp_path, [GEN], FakeClient(text="Sorry."), workers=1)
    assert s.failed == 4 and C.load_ai_docs(tmp_path) == []
