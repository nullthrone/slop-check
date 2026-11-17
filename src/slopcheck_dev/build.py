"""``slopcheck-dev build``: compile the catalog and package the skill (sections 4.4 and 7).

Output below ``--out`` (default ``dist``)::

    slop-check/SKILL.md                          copied from skill/SKILL.md
    slop-check/references/*.md                   copied from skill/references/*.md
    slop-check/references/text-patterns.md       generated
    slop-check/references/image-patterns.md      generated
    slop-check/references/prevention-rules-text.md   generated
    slop-check/references/prevention-rules-image.md  generated
    slop-check/scripts/catalog.json              generated (section 4.4)
    slop-check/scripts/slopcheck/                copy of src/slopcheck
    slop-check/scripts/slopcheck.py              shim: python scripts/slopcheck.py audit ...
    slop-check.zip                               folder slop-check/ at the zip root
    exports/system-prompt.md                     SKILL.md body plus every reference

The package is checked against section 7 before the zip is written. Generated Markdown is
deterministic for the same inputs: patterns are ordered by fixed keys and no timestamps
appear in it (``catalog.json`` carries ``generated_at``; set ``SOURCE_DATE_EPOCH`` for a
reproducible value).
"""

from __future__ import annotations

import copy
import datetime as _dt
import json
import os
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .patterns import LoadError, load_patterns, load_thresholds, repo_root
from .status import derive, measurement_for

SKILL_NAME = "slop-check"
ALLOWED_EXTENSIONS = (".md", ".py", ".json", ".yaml", ".txt")
ARCHIVE_EXTENSIONS = (".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".jar", ".whl", ".egg")
WARN_BYTES = 5 * 1024 * 1024
MAX_BYTES = 100 * 1024 * 1024
HANDWRITTEN_REFERENCES = (
    "audit-procedure.md",
    "report-format.md",
    "rewrite-procedure.md",
    "prevention-procedure.md",
)
GENERATED_REFERENCES = (
    "text-patterns.md",
    "image-patterns.md",
    "prevention-rules-text.md",
    "prevention-rules-image.md",
)
CATEGORY_ORDER = (
    "rhetoric",
    "lexical",
    "structure",
    "rhythm",
    "typography",
    "formatting",
    "attribution",
    "composition",
    "tone",
    "visual-style",
    "visual-composition",
    "visual-artifact",
    "visual-subject",
    "visual-typography",
)
CATEGORY_LABELS = {
    "rhetoric": "Rhetoric",
    "lexical": "Word choice",
    "structure": "Structure",
    "rhythm": "Rhythm",
    "typography": "Typography",
    "formatting": "Formatting",
    "attribution": "Attribution",
    "composition": "Composition",
    "tone": "Tone",
    "visual-style": "Visual style",
    "visual-composition": "Visual composition",
    "visual-artifact": "Visual artifacts",
    "visual-subject": "Subjects",
    "visual-typography": "Lettering in images",
}
POSITION_WORDS = {
    "any": "anywhere in the text",
    "text_start": "only at the very start of the text",
    "paragraph_start": "only at the start of a paragraph, heading or list item",
    "paragraph_end": "only at the end of a paragraph",
    "last_paragraph": "only in the last paragraph",
    "sentence_start": "only at the start of a sentence",
}
METRIC_WORDS = {
    "em_dash_density": "Em dashes (and en dashes set between spaces as dashes) per {per_words} words.",
    "curly_quotes": "Typographic quotation marks (“ ” ‘ ’) in languages that do not use them.",
    "sentence_length_cv": (
        "Variation of sentence length (coefficient of variation), taken as the lowest value over "
        "any run of {run} consecutive paragraphs. Low values mean evenly sized sentences."
    ),
    "emoji_decoration": "Emoji or decorative symbols used as the prefix of list items or headings.",
    "markdown_emphasis_density": "Bold, italic and heading markers per 100 words.",
    "paragraph_start_ratio": "Share of paragraphs that open with a term from the word list.",
    "nominalization_density": "Nouns with nominal suffixes per {per_words} words.",
    "bullet_bold_lead": "Longest run of list items within one list that open with a bold lead and a colon.",
    "triad": "Coordinations of exactly three short items (A, B and C; one to three words each).",
    "comma_density": "Commas per sentence.",
    "hyphenated_premodifier_density": "Hyphenated compound modifiers in front of a noun, per 100 words.",
}
EXAMPLE_MAX_CHARS = 240
MAX_POSITIVE_SHOWN = 4
MAX_NEGATIVE_SHOWN = 3

SHIM = '''"""Run the bundled slop-check engine: python scripts/slopcheck.py audit FILE."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from slopcheck.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
'''


class BuildError(RuntimeError):
    """Raised when the package cannot be built or violates section 7."""


# ---------------------------------------------------------------------------
# catalog (section 4.4)


def _now() -> _dt.datetime:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch and epoch.strip().isdigit():
        return _dt.datetime.fromtimestamp(int(epoch), tz=_dt.timezone.utc)
    return _dt.datetime.now(tz=_dt.timezone.utc)


def _verdict_thresholds(measurements: dict | None, thresholds: dict) -> dict:
    measured = (measurements or {}).get("verdict_thresholds") if isinstance(measurements, dict) else None
    if isinstance(measured, dict) and measured.get("yellow") is not None and measured.get("red") is not None:
        return {"yellow": float(measured["yellow"]), "red": float(measured["red"]), "source": "measured"}
    boot = thresholds.get("verdict_bootstrap") or {}
    return {"yellow": float(boot.get("yellow", 2.0)), "red": float(boot.get("red", 5.0)), "source": "bootstrap"}


def compile_catalog(
    patterns: list[dict],
    measurements: dict | None = None,
    thresholds: dict | None = None,
    version: str | None = None,
    generated_at: _dt.datetime | str | None = None,
) -> dict:
    """Catalog dict (section 4.4) with ``effective_status``, ``weight`` and ``weight_source``
    per pattern, derived by :func:`slopcheck_dev.status.derive`.

    ``measurements`` is a measurements.json structure (or None); ``thresholds`` defaults to
    the repository's ``governance/thresholds.yaml``. Patterns are sorted by (modality, id).
    """
    if thresholds is None:
        thresholds = load_thresholds()
    if isinstance(generated_at, str):
        stamp = generated_at
        day = generated_at[:10]
    else:
        when = generated_at or _now()
        stamp = when.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        day = when.astimezone(_dt.timezone.utc).strftime("%Y-%m-%d")
    entries = []
    for pattern in sorted(patterns, key=lambda p: (str(p.get("modality", "text")), str(p["id"]))):
        entry = copy.deepcopy(pattern)
        status, weight, source = derive(pattern, measurement_for(measurements, pattern["id"]), thresholds)
        entry["effective_status"] = status
        entry["weight"] = float(weight)
        entry["weight_source"] = source
        entries.append(entry)
    return {
        "catalog_version": version or day.replace("-", "."),
        "generated_at": stamp,
        "short_text_max_words": int(thresholds.get("short_text_max_words") or 150),
        "verdict_thresholds": _verdict_thresholds(measurements, thresholds),
        "patterns": entries,
    }


# ---------------------------------------------------------------------------
# markdown helpers


def _clean(text: object) -> str:
    return " ".join(str(text or "").split())


def _code(text: str) -> str:
    """Inline code span that survives backticks in ``text``."""
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if text.startswith("`") or text.endswith("`") or longest else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def _example(text: str) -> str:
    lines = [" ".join(line.split()) for line in str(text).strip().splitlines()]
    flat = " \\n ".join(line for line in lines if line)
    if len(flat) > EXAMPLE_MAX_CHARS:
        flat = flat[: EXAMPLE_MAX_CHARS - 6].rstrip() + " [...]"
    return _code(flat)


def _num(x: float) -> str:
    x = float(x)
    return str(int(x)) if x.is_integer() else f"{x:.3f}".rstrip("0").rstrip(".")


def _lang_label(lang: str) -> str:
    return "any language" if lang == "*" else lang


def _metric_unit(pattern: dict) -> str:
    detector = pattern.get("detector") or {}
    if detector.get("kind") == "metric":
        try:
            from slopcheck.metrics import METRICS

            spec = METRICS.get(detector.get("metric"))
            if spec is not None:
                return spec.unit
        except ImportError:  # pragma: no cover - engine always ships with the repository
            pass
    if detector.get("kind") == "llm" and (detector.get("params") or {}).get("unit") == "paragraph":
        return "paragraphs"
    return "sentences"


def _params_text(params: dict, skip: tuple[str, ...] = ()) -> str:
    rest = {k: v for k, v in sorted(params.items()) if k not in skip}
    if not rest:
        return ""
    parts = [f"{k}={json.dumps(v, ensure_ascii=False, sort_keys=True)}" for k, v in rest.items()]
    return " Parameters: " + "; ".join(parts) + "."


def detection_words(pattern: dict) -> str:
    """The detection rule in words."""
    detector = pattern.get("detector") or {}
    kind = detector.get("kind")
    where = POSITION_WORDS.get(detector.get("position") or "any", POSITION_WORDS["any"])
    if kind == "regex":
        return f"Phrase match, {where}. Each match of the phrase shapes shown in the example hits counts once."
    if kind == "lexicon":
        return (
            f"Word list, {where}. Each whole-word, case-insensitive occurrence of a listed term counts "
            "once; a trailing * marks a prefix."
        )
    if kind == "metric":
        name = detector.get("metric") or ""
        params = detector.get("params") or {}
        template = METRIC_WORDS.get(name, f"Metric {name}.")
        values = {"per_words": params.get("per_words", 100), "run": params.get("run", 3)}
        text = f"Measured value ({name}): " + template.format(**values)
        used = tuple(k for k in ("per_words", "run") if "{" + k + "}" in template)
        return text + _params_text(params, used)
    if kind == "llm":
        return "Judgment call (the script evaluates it only with a language model): " + _clean(
            detector.get("rubric")
        )
    if kind == "vision":
        return "Visual judgment: " + _clean(detector.get("rubric"))
    return "No detector: described for reference only."


def threshold_words(pattern: dict) -> list[str]:
    """Threshold sentences: base rule, short-text rule, context rules, dependency."""
    from slopcheck.thresholds import describe_rule, effective_rule

    threshold = pattern.get("threshold") or {}
    unit = _metric_unit(pattern)
    lines = [f"Threshold: {describe_rule(effective_rule(threshold, False, 'default'), None, unit)}."]
    if threshold.get("short_text"):
        short = describe_rule(effective_rule(threshold, True, "default"), None, unit)
        lines.append(f"Short texts: {short}.")
    for ctx in sorted((threshold.get("context_overrides") or {}).keys()):
        if ctx == "default":
            continue
        lines.append(f"Context {ctx}: {describe_rule(effective_rule(threshold, False, ctx), None, unit)}.")
    needed = (pattern.get("requires") or {}).get("min_other_findings")
    if needed:
        lines.append(f"Counts only when at least {needed} other scored patterns are triggered as well.")
    return lines


def status_words(pattern: dict) -> str:
    status = pattern.get("effective_status") or pattern.get("status")
    category = CATEGORY_LABELS.get(pattern.get("category"), pattern.get("category") or "-")
    if status == "core":
        source = pattern.get("weight_source")
        how = {
            "bootstrap": "bootstrap weight from the legacy catalog, not yet measured",
            "measured": "measured on the reference corpora",
        }.get(source, "no weight source")
        return f"Status: core, weight {_num(pattern.get('weight') or 0)} ({how}). Category: {category}."
    if status == "fading":
        return (
            "Status: fading, weight 0. The latest measurement found it no longer over-represented; "
            f"report it under observations only. Category: {category}."
        )
    return f"Status: candidate, weight 0; report it under observations only. Category: {category}."


def _example_block(pattern: dict) -> list[str]:
    out: list[str] = []
    kind = (pattern.get("detector") or {}).get("kind")
    realizations = pattern.get("realizations") or {}
    for lang in sorted(realizations, key=lambda k: (k == "*", k)):
        body = realizations[lang] or {}
        label = _lang_label(lang)
        terms = [t for t in body.get("terms") or [] if isinstance(t, str)]
        if terms and kind in ("lexicon", "metric"):
            out.append(f"Terms ({label}): " + ", ".join(_code(t) for t in terms) + ".")
            out.append("")
        examples = body.get("examples") or {}
        positives = [e for e in examples.get("positive") or [] if isinstance(e, str)][:MAX_POSITIVE_SHOWN]
        negatives = [e for e in examples.get("negative") or [] if isinstance(e, str)][:MAX_NEGATIVE_SHOWN]
        if positives:
            out.append(f"Example hits ({label}):")
            out.append("")
            out.extend(f"- {_example(e)}" for e in positives)
            out.append("")
        if negatives:
            out.append(f"Not a hit ({label}):")
            out.append("")
            out.extend(f"- {_example(e)}" for e in negatives)
            out.append("")
    return out


def _pattern_section(pattern: dict) -> list[str]:
    lines = [f"### {_clean(pattern.get('name')) or pattern['id']} (`{pattern['id']}`)", ""]
    lines.append(status_words(pattern))
    lines.append("")
    lines.append(_clean(pattern.get("summary")))
    lines.append("")
    lines.append("Detection: " + detection_words(pattern))
    lines.append("")
    if pattern.get("detector"):
        for sentence in threshold_words(pattern):
            lines.append(sentence)
            lines.append("")
    lines.extend(_example_block(pattern))
    if _clean(pattern.get("legitimate_use")):
        lines.append("Legitimate use: " + _clean(pattern.get("legitimate_use")))
        lines.append("")
    lines.append("Fix: " + _clean(pattern.get("fix")))
    lines.append("")
    return lines


def _groups(catalog: dict, modality: str) -> tuple[list[dict], list[dict], list[dict]]:
    pats = [p for p in catalog.get("patterns", []) if p.get("modality", "text") == modality]
    core = [p for p in pats if p.get("effective_status") == "core"]
    core.sort(key=lambda p: (-float(p.get("weight") or 0), p["id"]))
    candidates = sorted((p for p in pats if p.get("effective_status") == "candidate"), key=lambda p: p["id"])
    fading = sorted((p for p in pats if p.get("effective_status") == "fading"), key=lambda p: p["id"])
    return core, candidates, fading


def _index_table(groups: list[tuple[str, list[dict]]]) -> list[str]:
    lines = ["| Pattern | ID | Status | Weight |", "|---|---|---|---|"]
    for status, pats in groups:
        for p in pats:
            weight = _num(p.get("weight") or 0) if status == "core" else "0"
            lines.append(f"| {_clean(p.get('name'))} | `{p['id']}` | {status} | {weight} |")
    return lines


TEXT_INTRO = """\
Use this file when the bundled script cannot run, or to judge hits the script reports. For each
pattern, find the hits described under Detection, compare their number with the Threshold, and
check the legitimate use before you report a finding. Report in the structure of
`references/report-format.md`. Findings describe style patterns; they never state who or what
wrote a text.

Scoring: the score is the sum of the weights of the triggered scored patterns. The verdict is
GREEN below {yellow}, YELLOW from {yellow} and RED from {red} ({vt_source} thresholds). Candidate
and fading patterns carry no weight; list triggered ones as observations.

A text with at most {short_max} words counts as short. Some patterns use a separate threshold for
short texts or for a context (informal, technical, academic, marketing).
"""

IMAGE_INTRO = """\
Use this file to audit images and image prompts. Look at the image (or read the prompt), apply each
rubric under Detection, and check the legitimate use before you report a finding. Describe what is
visible; never state how an image was made.

Image patterns have no measured benchmark yet. Unless a pattern below is marked core, it carries
weight 0 and belongs under observations in the report.
"""


def render_patterns_markdown(catalog: dict, modality: str = "text") -> str:
    """``references/text-patterns.md`` or ``references/image-patterns.md``."""
    core, candidates, fading = _groups(catalog, modality)
    vt = catalog.get("verdict_thresholds") or {}
    title = "Text pattern catalog" if modality == "text" else "Image pattern catalog"
    lines = [f"# {title}", ""]
    lines.append(
        f"Generated by `slopcheck-dev build` from catalog version {catalog.get('catalog_version')}. "
        "Edit the pattern files in the repository, never this file."
    )
    lines.append("")
    if modality == "text":
        intro = TEXT_INTRO.format(
            yellow=_num(vt.get("yellow", 2.0)),
            red=_num(vt.get("red", 5.0)),
            vt_source=vt.get("source", "bootstrap"),
            short_max=catalog.get("short_text_max_words", 150),
        )
    else:
        intro = IMAGE_INTRO
    lines.extend(intro.rstrip("\n").split("\n"))
    lines.append("")
    groups = [("core", core), ("candidate", candidates), ("fading", fading)]
    if not any(pats for _s, pats in groups):
        lines.append("No patterns of this modality are in the catalog yet.")
        lines.append("")
        return "\n".join(lines).rstrip("\n") + "\n"
    lines.append("## Index")
    lines.append("")
    lines.extend(_index_table(groups))
    lines.append("")
    headings = {
        "core": "## Scored patterns",
        "candidate": "## Candidates (observed, weight 0)",
        "fading": "## Fading patterns (observed, weight 0)",
    }
    for status, pats in groups:
        if not pats:
            continue
        lines.append(headings[status])
        lines.append("")
        for p in pats:
            lines.extend(_pattern_section(p))
    return "\n".join(lines).rstrip("\n") + "\n"


def render_prevention_markdown(catalog: dict, modality: str = "text") -> str:
    """``references/prevention-rules-<modality>.md``: core and candidate rules by category."""
    pats = [
        p
        for p in catalog.get("patterns", [])
        if p.get("modality", "text") == modality
        and p.get("effective_status") in ("core", "candidate")
        and _clean(p.get("prevention"))
    ]
    kind_word = "writing text" if modality == "text" else "writing image prompts or generating images"
    lines = [f"# Prevention rules ({modality})", ""]
    lines.append(
        f"Generated by `slopcheck-dev build` from catalog version {catalog.get('catalog_version')}. "
        "Edit the pattern files in the repository, never this file."
    )
    lines.append("")
    lines.append(
        f"Apply these rules while {kind_word}. Each rule names the pattern it prevents; the full "
        f"description is in `references/{modality}-patterns.md`. Rules for scored patterns come "
        "first within each group."
    )
    lines.append("")
    if not pats:
        lines.append("No prevention rules for this modality yet.")
        return "\n".join(lines).rstrip("\n") + "\n"
    order = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    by_cat: dict[str, list[dict]] = {}
    for p in pats:
        by_cat.setdefault(p.get("category") or "other", []).append(p)
    for cat in sorted(by_cat, key=lambda c: (order.get(c, len(order)), c)):
        lines.append(f"## {CATEGORY_LABELS.get(cat, cat.replace('-', ' ').capitalize())}")
        lines.append("")
        items = sorted(
            by_cat[cat],
            key=lambda p: (p.get("effective_status") != "core", -float(p.get("weight") or 0), p["id"]),
        )
        for p in items:
            lines.append(f"- {_clean(p.get('prevention'))} (`{p['id']}`)")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


_BOLD_LEAD = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?:\*\*|__)")
_CODE_SPAN = re.compile(r"(`+)(?:(?!\1).)+?\1")
_EMOJI = re.compile("[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f000-\U0001f2ff⭐⬆✅]")


def formatting_problems(markdown: str) -> list[str]:
    """Bold-lead list items and emoji outside code spans in generated Markdown."""
    problems = []
    for n, line in enumerate(markdown.splitlines(), 1):
        if _BOLD_LEAD.match(line):
            problems.append(f"line {n}: list item with a bold lead")
        if _EMOJI.search(_CODE_SPAN.sub("", line)):
            problems.append(f"line {n}: emoji outside a code span")
    return problems


# ---------------------------------------------------------------------------
# package checks (section 7)


def parse_frontmatter(text: str) -> tuple[dict | None, str]:
    """(frontmatter dict or None, body) of a Markdown file with ``---`` frontmatter."""
    import yaml

    if not text.startswith("---"):
        return None, text
    lines = text.split("\n")
    if lines[0].strip() != "---":
        return None, text
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            try:
                data = yaml.safe_load("\n".join(lines[1:i]))
            except yaml.YAMLError:
                return None, text
            return (data if isinstance(data, dict) else None), "\n".join(lines[i + 1 :])
    return None, text


_MAGIC = (
    (0, b"PK\x03\x04", "zip"),
    (0, b"\x1f\x8b", "gzip"),
    (0, b"7z\xbc\xaf\x27\x1c", "7z"),
    (0, b"Rar!", "rar"),
    (0, b"BZh", "bzip2"),
    (0, b"\xfd7zXZ\x00", "xz"),
    (257, b"ustar", "tar"),
)


def _archive_kind(path: Path) -> str | None:
    try:
        with open(path, "rb") as fh:
            head = fh.read(264)
    except OSError:
        return None
    for offset, magic, name in _MAGIC:
        if head[offset : offset + len(magic)] == magic:
            return name
    return None


def check_package(pkg_dir: str | Path) -> tuple[list[str], list[str]]:
    """Section 7 checks on a built package directory: (errors, warnings)."""
    pkg = Path(pkg_dir)
    errors: list[str] = []
    warnings: list[str] = []
    if pkg.name != SKILL_NAME:
        errors.append(f"package folder must be named '{SKILL_NAME}', is '{pkg.name}'")
    skill = pkg / "SKILL.md"
    if not skill.is_file():
        errors.append("SKILL.md missing in the package root")
    else:
        meta, _body = parse_frontmatter(skill.read_text(encoding="utf-8"))
        if meta is None:
            errors.append("SKILL.md: frontmatter (--- name / description ---) missing or invalid")
        else:
            name = meta.get("name")
            if name != SKILL_NAME:
                errors.append(f"SKILL.md: frontmatter name must be '{SKILL_NAME}', is {name!r}")
            elif not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", str(name)):
                errors.append("SKILL.md: frontmatter name must be lowercase with hyphens")
            description = meta.get("description")
            if not isinstance(description, str) or not description.strip():
                errors.append("SKILL.md: frontmatter description missing or empty")
    total = 0
    for path in sorted(pkg.rglob("*"), key=lambda p: p.as_posix()):
        rel = path.relative_to(pkg).as_posix()
        if path.is_symlink():
            errors.append(f"{rel}: symbolic links are not allowed")
            continue
        if any(part.startswith(".") for part in path.relative_to(pkg).parts):
            errors.append(f"{rel}: hidden files and folders are not allowed")
            continue
        if path.name == "__pycache__" or path.suffix in (".pyc", ".pyo"):
            errors.append(f"{rel}: __pycache__ and compiled Python files are not allowed")
            continue
        if path.is_dir():
            continue
        total += path.stat().st_size
        suffix = path.suffix.lower()
        if suffix in ARCHIVE_EXTENSIONS:
            errors.append(f"{rel}: archives are not allowed inside the package")
        elif suffix not in ALLOWED_EXTENSIONS:
            allowed = " ".join(ALLOWED_EXTENSIONS)
            errors.append(f"{rel}: file type '{suffix or '(none)'}' not allowed (allowed: {allowed})")
        else:
            kind = _archive_kind(path)
            if kind:
                errors.append(f"{rel}: contains {kind} archive data")
    if total >= MAX_BYTES:
        errors.append(f"package size {total / 1048576:.1f} MB exceeds the 100 MB limit")
    elif total >= WARN_BYTES:
        warnings.append(f"package size {total / 1048576:.1f} MB is above 5 MB; keep it far below 100 MB")
    return errors, warnings


# ---------------------------------------------------------------------------
# build


@dataclass
class BuildResult:
    package_dir: Path
    zip_path: Path
    export_path: Path
    catalog: dict
    warnings: list[str] = field(default_factory=list)


def _copy_engine(src: Path, dest: Path) -> list[str]:
    """Copy src/slopcheck without caches, hidden files or a stray catalog.json."""
    notes = []
    for path in sorted(src.rglob("*"), key=lambda p: p.as_posix()):
        rel = path.relative_to(src)
        if any(part.startswith(".") or part == "__pycache__" for part in rel.parts):
            continue
        if path.is_dir() or path.suffix in (".pyc", ".pyo"):
            continue
        if rel.as_posix() == "catalog.json":
            notes.append("src/slopcheck/catalog.json not copied (scripts/catalog.json is generated)")
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    return notes


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def write_zip(pkg_dir: Path, zip_path: Path) -> None:
    """Deterministic zip with ``slop-check/`` at the root (fixed timestamps, sorted entries)."""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    entries = sorted(pkg_dir.rglob("*"), key=lambda p: p.relative_to(pkg_dir).as_posix())
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        root_info = zipfile.ZipInfo(f"{pkg_dir.name}/", date_time=(1980, 1, 1, 0, 0, 0))
        root_info.external_attr = (0o40755 << 16) | 0x10
        zf.writestr(root_info, b"")
        for path in entries:
            arc = f"{pkg_dir.name}/{path.relative_to(pkg_dir).as_posix()}"
            if path.is_dir():
                info = zipfile.ZipInfo(arc + "/", date_time=(1980, 1, 1, 0, 0, 0))
                info.external_attr = (0o40755 << 16) | 0x10
                zf.writestr(info, b"")
                continue
            info = zipfile.ZipInfo(arc, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, path.read_bytes())


EXPORT_INTRO = """\
# slop-check (single-file export)

This file bundles the slop-check skill for runtimes without skill support. Where the
instructions refer to a file under `references/`, read the section of that name further down.
The bundled script is not available in this form: apply the pattern catalog yourself.
"""


def render_export(skill_body: str, references: list[tuple[str, str]]) -> str:
    parts = [EXPORT_INTRO.rstrip("\n"), "", skill_body.strip("\n"), ""]
    for name, text in references:
        parts.extend(["---", "", f"# File: references/{name}", "", text.strip("\n"), ""])
    return "\n".join(parts).rstrip("\n") + "\n"


def _reference_order(names: list[str]) -> list[str]:
    fixed = [n for n in HANDWRITTEN_REFERENCES if n in names]
    extras = sorted(n for n in names if n not in HANDWRITTEN_REFERENCES and n not in GENERATED_REFERENCES)
    generated = [n for n in GENERATED_REFERENCES if n in names]
    return fixed + extras + generated


def build(
    out_dir: str | Path = "dist",
    measurements_path: str | Path | None = None,
    version: str | None = None,
    root: str | Path | None = None,
    patterns: list[dict] | None = None,
    thresholds: dict | None = None,
) -> BuildResult:
    """Build ``<out_dir>/slop-check/``, the zip and the single-file export."""
    root = Path(root).resolve() if root else repo_root()
    out = Path(out_dir)
    if not out.is_absolute():
        out = Path.cwd() / out
    skill_src = root / "skill" / "SKILL.md"
    if not skill_src.is_file():
        raise BuildError(
            "skill/SKILL.md not found: the skill instructions are hand-written and must exist before "
            "the package can be built"
        )
    engine_src = root / "src" / "slopcheck"
    if not (engine_src / "__init__.py").is_file():
        raise BuildError("src/slopcheck/ not found: the runtime engine is bundled into the package")
    try:
        thresholds = thresholds if thresholds is not None else load_thresholds(root)
        patterns = patterns if patterns is not None else load_patterns(root)
    except LoadError as exc:
        raise BuildError(str(exc)) from exc
    measurements = None
    if measurements_path:
        try:
            measurements = json.loads(Path(measurements_path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BuildError(f"cannot read measurements {measurements_path}: {exc}") from exc
    catalog = compile_catalog(patterns, measurements, thresholds, version)
    warnings: list[str] = []

    pkg = out / SKILL_NAME
    if pkg.exists():
        shutil.rmtree(pkg)
    refs_dir = pkg / "references"
    refs_dir.mkdir(parents=True)
    shutil.copyfile(skill_src, pkg / "SKILL.md")

    ref_src = root / "skill" / "references"
    handwritten: list[str] = []
    if ref_src.is_dir():
        for path in sorted(ref_src.glob("*.md")):
            if path.name in GENERATED_REFERENCES:
                raise BuildError(f"skill/references/{path.name} clashes with a generated reference of that name")
            shutil.copyfile(path, refs_dir / path.name)
            handwritten.append(path.name)
    missing = [n for n in HANDWRITTEN_REFERENCES if n not in handwritten]
    if missing:
        warnings.append("hand-written references missing: " + ", ".join(missing))

    generated = {
        "text-patterns.md": render_patterns_markdown(catalog, "text"),
        "image-patterns.md": render_patterns_markdown(catalog, "image"),
        "prevention-rules-text.md": render_prevention_markdown(catalog, "text"),
        "prevention-rules-image.md": render_prevention_markdown(catalog, "image"),
    }
    for name, text in generated.items():
        _write(refs_dir / name, text)
        warnings.extend(f"references/{name}: {p}" for p in formatting_problems(text))

    scripts = pkg / "scripts"
    _write(scripts / "catalog.json", json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
    warnings.extend(_copy_engine(engine_src, scripts / "slopcheck"))
    _write(scripts / "slopcheck.py", SHIM)

    errors, size_warnings = check_package(pkg)
    warnings.extend(size_warnings)
    if errors:
        raise BuildError("package violates section 7:\n  " + "\n  ".join(errors))

    zip_path = out / f"{SKILL_NAME}.zip"
    write_zip(pkg, zip_path)

    _meta, body = parse_frontmatter((pkg / "SKILL.md").read_text(encoding="utf-8"))
    names = _reference_order(sorted(p.name for p in refs_dir.glob("*.md")))
    references = [(n, (refs_dir / n).read_text(encoding="utf-8")) for n in names]
    export_path = out / "exports" / "system-prompt.md"
    _write(export_path, render_export(body, references))
    return BuildResult(pkg, zip_path, export_path, catalog, warnings)


def run(args) -> int:
    """CLI handler for ``slopcheck-dev build``."""
    root = Path(args.root).resolve() if getattr(args, "root", None) else repo_root()
    try:
        result = build(args.out, args.measurements, args.version, root=root)
    except BuildError as exc:
        print(f"build: {exc}", file=sys.stderr)
        return 1
    for w in result.warnings:
        print(f"build: warning: {w}", file=sys.stderr)
    counts: dict[str, int] = {}
    for p in result.catalog["patterns"]:
        counts[p["effective_status"]] = counts.get(p["effective_status"], 0) + 1
    summary = ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
    print(f"build: catalog {result.catalog['catalog_version']} ({summary})")
    print(f"build: wrote {result.package_dir}, {result.zip_path}, {result.export_path}")
    return 0
