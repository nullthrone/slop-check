"""``slopcheck-dev build``: compile the catalog and package the skill (sections 4.4 and 7).

Output below ``--out`` (default ``dist``)::

    slop-check/SKILL.md                          skill/SKILL.md with the core catalog injected
    slop-check/references/*.md                   copied from skill/references/*.md
    slop-check/references/text-patterns.md       generated
    slop-check/references/image-patterns.md      generated
    slop-check/references/prevention-rules-text.md   generated
    slop-check/references/prevention-rules-image.md  generated
    slop-check/scripts/catalog.json              generated (section 4.4)
    slop-check/scripts/slopcheck/                copy of src/slopcheck
    slop-check/scripts/slopcheck.py              shim: python scripts/slopcheck.py audit ...
    slop-check.zip                               folder slop-check/ at the zip root
    slop-check-flat.zip                          SKILL.md and the package files at the zip root
    exports/system-prompt.md                     SKILL.md body, report format, condensed catalog
    exports/knowledge.md                         SKILL.md body plus every reference

The region of ``SKILL.md`` between ``<!-- slopcheck:core-catalog -->`` and
``<!-- /slopcheck:core-catalog -->`` is replaced by a compact list of the scored core patterns,
the verdict thresholds and the candidate IDs, so that ``SKILL.md`` alone suffices for a correct
audit in runtimes that neither run scripts nor open ``references/`` (section 7). The packaged
``SKILL.md`` must stay within the Agent Skills size guidance (``MAX_SKILL_LINES``,
``MAX_SKILL_TOKENS``); the build shows fewer typical hits per pattern when the full list does
not fit, and fails when even the list without typical hits does not fit.

The package is checked against section 7 before the zips are written. Generated Markdown is
deterministic for the same inputs: patterns are ordered by fixed keys and no timestamps
appear in it (``catalog.json`` carries ``generated_at``; set ``SOURCE_DATE_EPOCH`` for a
reproducible value).
"""

from __future__ import annotations

import copy
import datetime as _dt
import json
import math
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
MAX_DESCRIPTION_CHARS = 200  # claude.ai's limit, the strictest known runtime (section 7)
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
    "curly_quotes": "Typographic (curly) quotation marks in languages whose plain text does not use them.",
    "sentence_length_cv": (
        "Variation of sentence length (coefficient of variation), taken as the lowest value over "
        "any run of {run} consecutive paragraphs. Low values mean evenly sized sentences."
    ),
    "emoji_decoration": "Emoji or decorative symbols used as the prefix of list items or headings.",
    "markdown_emphasis_density": "Bold, italic and heading markers per 100 words.",
    "paragraph_start_ratio": "Share of paragraphs that open with a term from the word list.",
    "nominalization_density": "Nouns with nominal suffixes per {per_words} words.",
    "bullet_bold_lead": "Longest run of list items within one list that open with a bold lead and a colon.",
    "triad": "Coordinations of exactly three short items joined by a final and/or, each up to three words.",
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
    provisional = thresholds.get("verdict_provisional") or {}
    return {
        "yellow": float(provisional.get("yellow", 2.0)),
        "red": float(provisional.get("red", 5.0)),
        "source": "provisional",
    }


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
    ``weight_source`` is ``measured``, ``provisional`` (``initial_core``) or ``none``;
    ``verdict_thresholds.source`` is ``measured`` or ``provisional`` (``verdict_provisional``).
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
        return f"Phrase match, {where}. Each phrase shaped like the example hits counts once."
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
        min_sentences = params.get("min_sentences_per_paragraph")
        if name == "sentence_length_cv" and isinstance(min_sentences, int) and min_sentences > 1:
            text += f" Paragraphs with fewer than {min_sentences} sentences break a run."
            used += ("min_sentences_per_paragraph",)
        return text + _params_text(params, used)
    if kind == "llm":
        rubric = _clean(detector.get("rubric"))
        return f"Judgment call; the script evaluates it only with a language model. Rubric: {rubric}"
    if kind == "vision":
        return "Visual judgment: " + _clean(detector.get("rubric"))
    return "No detector: described for reference only."


def threshold_words(pattern: dict) -> list[str]:
    """Threshold sentences: base rule, short-text rule, context rules, dependency."""
    from slopcheck.thresholds import describe_rule as _describe
    from slopcheck.thresholds import effective_rule

    image = pattern.get("modality", "text") == "image"

    def describe_rule(rule: dict, requires: dict | None, unit: str) -> str:
        text = _describe(rule, requires, unit)
        return text.replace("per text", "per image") if image else text

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
            "provisional": "provisional weight, not yet measured",
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

Scoring: the score is the sum of the weights of the triggered scored patterns. A score below
{yellow} is GREEN. YELLOW starts at {yellow}, RED at {red} ({vt_source} thresholds). Candidate
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
            vt_source=vt.get("source", "provisional"),
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
# core catalog inside SKILL.md (section 7: the packaged SKILL.md suffices on its own)

CORE_CATALOG_START = "<!-- slopcheck:core-catalog -->"
CORE_CATALOG_END = "<!-- /slopcheck:core-catalog -->"
#: Agent Skills guidance for SKILL.md: under about 500 lines and about 5,000 tokens.
MAX_SKILL_LINES = 500
MAX_SKILL_TOKENS = 5000
#: Typical hits per language in the core catalog, richest first; the build takes the first
#: level that keeps SKILL.md within the limits above.
CORE_EXAMPLE_LEVELS = (2, 1, 0)
CORE_EXAMPLE_MAX_CHARS = 64
CORE_TERMS_PER_EXAMPLE = 3  # word-list terms shown per typical-hit slot
POSITION_SHORT = {
    "any": "",
    "text_start": " at the start of the text",
    "paragraph_start": " at the start of a paragraph or list item",
    "paragraph_end": " at the end of a paragraph",
    "last_paragraph": " in the last paragraph",
    "sentence_start": " at the start of a sentence",
}
METRIC_SHORT = {
    "em_dash_density": "em dashes (and spaced en dashes) per {per_words} words",
    "curly_quotes": "curly quotation marks in a language whose plain text uses straight ones",
    "sentence_length_cv": (
        "variation of sentence length (standard deviation / mean), lowest over {run} consecutive paragraphs"
    ),
    "emoji_decoration": "emoji or symbols used as list or heading prefixes",
    "markdown_emphasis_density": "bold, italic and heading markers per 100 words",
    "paragraph_start_ratio": "share of paragraphs that open with a listed word",
    "nominalization_density": "nouns of {min_word_length}+ letters ending in {suffixes} (plurals count) per {per_words} words",
    "bullet_bold_lead": "longest run of list items that open with a bold lead and a colon",
    "triad": 'lists of exactly three short items ("A, B and C", each up to three words)',
    "comma_density": "commas per sentence",
    "hyphenated_premodifier_density": "hyphenated modifiers in front of a noun per 100 words",
}
COMPACT_CORE_POINTER = (
    "In this single-file export, the scored patterns, the verdict thresholds and the candidates are "
    'listed in the section "File: references/text-patterns.md (condensed)" at the end.'
)


def estimate_tokens(text: str) -> int:
    """Rough token count: one token per four characters (the usual rule of thumb)."""
    return math.ceil(len(text) / 4)


def skill_size(text: str) -> dict:
    """Lines, characters and estimated tokens of a SKILL.md text."""
    return {"lines": len(text.splitlines()), "chars": len(text), "tokens": estimate_tokens(text)}


def _report_num(x: float) -> str:
    """A number as the report writes it: at least one decimal (2.0, 2.5, 0.375)."""
    x = float(x)
    return f"{x:.1f}" if float(round(x, 1)) == x else _num(x)


def _strip_parens(text: str) -> str:
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"\s*\([^()]*\)", "", text)
    return _clean(text)


def _gist(pattern: dict) -> str:
    """First sentence of the summary without parenthetical examples, lower-cased start."""
    gist = _first_sentence(_strip_parens(_clean(pattern.get("summary"))), 200).rstrip(".")
    if gist[:2] and not gist[:2].isupper():
        gist = gist[0].lower() + gist[1:]
    return gist


def _core_rule(pattern: dict) -> str:
    """How to find hits, in a few words."""
    detector = pattern.get("detector") or {}
    kind = detector.get("kind")
    where = POSITION_SHORT.get(detector.get("position") or "any", "")
    if kind == "regex":
        return f"Phrase{where}"
    if kind == "lexicon":
        return f"Listed words{where}"
    if kind == "metric":
        name = detector.get("metric") or ""
        params = detector.get("params") or {}
        suffixes = params.get("suffixes") or {}
        values = {
            "per_words": params.get("per_words", 100),
            "run": params.get("run", 3),
            "min_word_length": params.get("min_word_length", 6),
            "suffixes": "; ".join(
                f"{lang} " + " ".join(f"-{s}" for s in suffixes[lang]) for lang in sorted(suffixes)
            )
            or "a nominal suffix",
        }
        text = "Measured: " + METRIC_SHORT.get(name, name.replace("_", " ")).format(**values)
        min_sentences = params.get("min_sentences_per_paragraph")
        if name == "sentence_length_cv" and isinstance(min_sentences, int) and min_sentences > 1:
            text += f" of {min_sentences}+ sentences"
        return text
    if kind == "llm":
        rule = (pattern.get("threshold") or {}).get("value")
        unit = _metric_unit(pattern)
        if rule:
            return f"Judgment per {unit[:-1]}: {_gist(pattern)}; value = share of such {unit}"
        return f"Judgment: {_gist(pattern)}"  # the summary already says where to look
    return "Judgment: " + _gist(pattern)


def _core_threshold(pattern: dict) -> str:
    """Base rule (with dependency), then short-text and context variants, as the report writes them."""
    from slopcheck.thresholds import describe_rule, effective_rule

    threshold = pattern.get("threshold") or {}
    unit = _metric_unit(pattern)
    text = describe_rule(effective_rule(threshold, False, "default"), pattern.get("requires"), unit)
    variants = []
    if threshold.get("short_text"):
        variants.append("short texts: " + describe_rule(effective_rule(threshold, True, "default"), None, unit))
    for ctx in sorted((threshold.get("context_overrides") or {}).keys()):
        if ctx != "default":
            variants.append(f"{ctx}: " + describe_rule(effective_rule(threshold, False, ctx), None, unit))
    return text + (f" ({'; '.join(variants)})" if variants else "")


def _distinct_terms(terms: list[str], limit: int) -> list[str]:
    """The first ``limit`` terms, skipping inflections of a term already picked."""
    picked: list[str] = []
    for term in terms:
        if len(picked) >= limit:
            break
        stems = [p.rstrip("*").lower() for p in picked]
        if any(term.lower().startswith(stem) for stem in stems if stem):
            continue
        picked.append(term)
    return picked


def _typical_phrase(example: str, regexes: tuple) -> str:
    """The part of a positive example that a phrase pattern matches, else the whole example."""
    for rx in regexes:
        m = rx.search(example)
        if m and m.end() > m.start():
            phrase = m.group(0).strip().lstrip(",;").strip().rstrip(" -–—")
            if phrase:
                return phrase
    return example


def _core_examples(pattern: dict, per_language: int) -> str:
    """Typical hits per language: word-list terms, the matched part of the positive examples of
    a phrase pattern, or short single-line positive examples of other patterns."""
    from slopcheck.detectors import compile_regexes

    if per_language <= 0:
        return ""
    parts = []
    phrase_kind = (pattern.get("detector") or {}).get("kind") == "regex"
    realizations = pattern.get("realizations") or {}
    for lang in sorted(realizations, key=lambda k: (k == "*", k)):
        body = realizations[lang] or {}
        terms = [t for t in body.get("terms") or [] if isinstance(t, str)]
        if terms:
            shown = _distinct_terms(terms, per_language * CORE_TERMS_PER_EXAMPLE)
        else:
            regexes: tuple = ()
            if phrase_kind:
                try:
                    regexes = compile_regexes(f"{pattern['id']}/{lang}", tuple(body.get("patterns") or ()))
                except ValueError:
                    regexes = ()
            positives = [e for e in ((body.get("examples") or {}).get("positive")) or [] if isinstance(e, str)]
            candidates = [_clean(_typical_phrase(e.strip(), regexes)) for e in positives if "\n" not in e.strip()]
            shown = [c for c in candidates if c and len(c) <= CORE_EXAMPLE_MAX_CHARS][:per_language]
        if shown:
            label = "any language" if lang == "*" else lang
            parts.append(f"{label}: " + ", ".join(_code(s) for s in shown) + ".")
    return " ".join(parts)


def render_core_catalog(catalog: dict, examples: int = CORE_EXAMPLE_LEVELS[0]) -> str:
    """The region between the core-catalog markers of the packaged SKILL.md.

    One line per scored (core) text pattern: ID, name, weight, how to find hits, threshold and
    ``examples`` typical hits per language; then the verdict thresholds' source and one line
    of candidate (and fading) IDs.
    """
    core, candidates, fading = _groups(catalog, "text")
    vt = catalog.get("verdict_thresholds") or {}
    yellow, red = _report_num(vt.get("yellow", 2.0)), _report_num(vt.get("red", 5.0))
    lines = [
        f"Catalog {catalog.get('catalog_version')}. Verdict: a score below {yellow} is GREEN, from {yellow} "
        f"YELLOW, from {red} RED ({vt.get('source', 'provisional')} thresholds). A short text has at most "
        f"{catalog.get('short_text_max_words', 150)} words.",
    ]
    if any(p.get("weight_source") == "provisional" for p in core):
        lines.append("The weights are provisional, so every report carries the provisional-weights note.")
    elif core:
        lines.append("All weights are measured, so reports carry no provisional-weights note.")
    lines.append("")
    if core:
        lines.append(
            "Each line: ID, name, weight, how to find hits, threshold as the report writes it, typical hits "
            "per language."
        )
        lines.append("")
    else:
        lines.append("No scored patterns yet: every text audit is GREEN.")
    for p in core:
        line = (
            f"- `{p['id']}` {_clean(p.get('name'))}, weight {_report_num(p.get('weight') or 0)}. "
            f"{_core_rule(p)}; threshold {_core_threshold(p)}."
        )
        typical = _core_examples(p, examples)
        lines.append(line + (f" {typical}" if typical else ""))
    observed = [("Candidates", candidates), ("Fading", fading)]
    tail = [
        f"{label} (weight 0, observations only): " + ", ".join(f"`{p['id']}`" for p in pats) + "."
        for label, pats in observed
        if pats
    ]
    if tail:
        lines.append("")
        lines.extend(tail)
    return "\n".join(lines) + "\n"


def replace_marked_region(
    text: str, content: str, start: str = CORE_CATALOG_START, end: str = CORE_CATALOG_END
) -> str:
    """Replace the lines between the marker lines ``start`` and ``end`` (kept) with ``content``."""
    lines = text.split("\n")
    starts = [i for i, line in enumerate(lines) if line.strip() == start]
    ends = [i for i, line in enumerate(lines) if line.strip() == end]
    if len(starts) != 1 or len(ends) != 1 or ends[0] < starts[0]:
        raise BuildError(
            f"skill/SKILL.md needs exactly one line '{start}' followed by exactly one line '{end}'; the build "
            "fills the region between them (section 7)"
        )
    body = content.strip("\n").split("\n") if content.strip("\n") else []
    return "\n".join(lines[: starts[0] + 1] + body + lines[ends[0] :])


def package_skill_md(skill_text: str, catalog: dict) -> tuple[str, dict, list[str]]:
    """Packaged SKILL.md text, its size (:func:`skill_size`) and warnings.

    Takes the richest level of ``CORE_EXAMPLE_LEVELS`` whose result stays within
    ``MAX_SKILL_LINES`` and ``MAX_SKILL_TOKENS`` (a warning names a reduced level). Raises
    :class:`BuildError` when even the catalog without typical hits does not fit.
    """
    size: dict = {}
    for level in CORE_EXAMPLE_LEVELS:
        text = replace_marked_region(skill_text, render_core_catalog(catalog, level))
        size = skill_size(text)
        if size["lines"] <= MAX_SKILL_LINES and size["tokens"] <= MAX_SKILL_TOKENS:
            warnings = []
            if level != CORE_EXAMPLE_LEVELS[0]:
                warnings.append(
                    f"SKILL.md: the core catalog shows {level} typical hits per language instead of "
                    f"{CORE_EXAMPLE_LEVELS[0]} to stay within {MAX_SKILL_LINES} lines and about "
                    f"{MAX_SKILL_TOKENS} tokens"
                )
            return text, size, warnings
    raise BuildError(
        f"packaged SKILL.md has {size['lines']} lines and about {size['tokens']} tokens with the smallest "
        f"core catalog; the limits are {MAX_SKILL_LINES} lines and about {MAX_SKILL_TOKENS} tokens "
        "(section 7). Shorten the hand-written text of skill/SKILL.md."
    )


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
            elif len(description.strip()) > MAX_DESCRIPTION_CHARS:
                errors.append(
                    f"SKILL.md: frontmatter description has {len(description.strip())} characters, "
                    f"at most {MAX_DESCRIPTION_CHARS} are allowed"
                )
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
    flat_zip_path: Path | None = None
    skill_size: dict | None = None  # lines, chars, tokens of the packaged SKILL.md (skill_size())


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


def write_zip(pkg_dir: Path, zip_path: Path, *, flat: bool = False) -> None:
    """Deterministic zip (fixed timestamps, sorted entries).

    By default the folder ``slop-check/`` is at the zip root; with ``flat`` the package files
    themselves are (``SKILL.md`` at the root), for runtimes that expect that layout.
    """
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    entries = sorted(pkg_dir.rglob("*"), key=lambda p: p.relative_to(pkg_dir).as_posix())
    prefix = "" if flat else f"{pkg_dir.name}/"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if prefix:
            root_info = zipfile.ZipInfo(prefix, date_time=(1980, 1, 1, 0, 0, 0))
            root_info.external_attr = (0o40755 << 16) | 0x10
            zf.writestr(root_info, b"")
        for path in entries:
            arc = f"{prefix}{path.relative_to(pkg_dir).as_posix()}"
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


COMPACT_INTRO = """\
# slop-check (compact system prompt)

This file bundles the slop-check skill for runtimes without skill support, in a size that fits a
system prompt or custom instructions. It holds the skill instructions, the report format and a
condensed pattern catalog. Where the instructions refer to a file under `references/`, use the
section of that name below; for full pattern detail (all example phrases, word lists and
rubrics) attach `knowledge.md` as a knowledge file where the runtime supports one. The bundled
script is not available in this form: apply the catalog yourself.
"""


def _first_sentence(text: object, limit: int = 160) -> str:
    clean = _clean(text)
    for stop in (". ", "? ", "! "):
        idx = clean.find(stop)
        if 0 < idx < limit:
            return clean[: idx + 1]
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _compact_examples(pattern: dict, per_language: int = 1) -> str:
    parts: list[str] = []
    for lang, real in sorted((pattern.get("realizations") or {}).items()):
        examples = ((real or {}).get("examples") or {}).get("positive") or []
        picked = [f'"{_clean(e)}"' for e in examples[:per_language]]
        if picked:
            label = "any language" if lang == "*" else lang
            parts.append(f"{label}: " + "; ".join(picked))
    return " | ".join(parts)


def render_compact_catalog(catalog: dict) -> str:
    """Condensed catalog for the compact export: scored core, then candidates, both modalities."""
    vt = catalog.get("verdict_thresholds") or {}
    lines = [
        "# File: references/text-patterns.md (condensed)",
        "",
        f"Verdict: GREEN below {_num(vt.get('yellow', 0))}, YELLOW from {_num(vt.get('yellow', 0))}, "
        f"RED from {_num(vt.get('red', 0))} (sum of the weights of triggered scored patterns). "
        "Candidates carry weight 0 and are reported as observations.",
        "",
    ]
    for modality in ("text", "image"):
        core, candidates, _fading = _groups(catalog, modality)
        if not core and not candidates:
            continue
        lines.extend([f"## {modality.capitalize()} patterns", ""])
        for pattern in core + candidates:
            status = pattern.get("effective_status")
            weight = _num(pattern.get("weight") or 0) if status == "core" else "0"
            head = f"- `{pattern['id']}` {pattern.get('name', '')} ({status}, weight {weight})."
            body = [_first_sentence(pattern.get("summary"))]
            body.append(" ".join(threshold_words(pattern)))
            examples = _compact_examples(pattern)
            if examples:
                body.append(f"Examples: {examples}.")
            body.append("Fix: " + _first_sentence(pattern.get("fix")))
            lines.append(head + " " + " ".join(b for b in body if b))
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def render_compact_export(skill_body: str, report_format: str | None, catalog: dict) -> str:
    """``exports/system-prompt.md``. The condensed catalog at the end is the export's only pattern
    list: the core-catalog region of the SKILL.md body, if present, becomes a pointer to it."""
    if CORE_CATALOG_START in skill_body:
        skill_body = replace_marked_region(skill_body, COMPACT_CORE_POINTER)
    parts = [COMPACT_INTRO.rstrip("\n"), "", skill_body.strip("\n"), ""]
    if report_format:
        parts.extend(["---", "", "# File: references/report-format.md", "", report_format.strip("\n"), ""])
    parts.extend(["---", "", render_compact_catalog(catalog).strip("\n"), ""])
    return "\n".join(parts).rstrip("\n") + "\n"


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
    skill_text, size, skill_warnings = package_skill_md(skill_src.read_text(encoding="utf-8"), catalog)
    _write(pkg / "SKILL.md", skill_text)
    warnings.extend(skill_warnings)

    ref_src = root / "skill" / "references"
    handwritten: list[str] = []
    if ref_src.is_dir():
        for path in sorted(ref_src.glob("*.md")):
            if path.name in GENERATED_REFERENCES:
                raise BuildError(f"skill/references/{path.name} clashes with a generated reference")
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
    flat_zip_path = out / f"{SKILL_NAME}-flat.zip"
    write_zip(pkg, flat_zip_path, flat=True)

    _meta, body = parse_frontmatter((pkg / "SKILL.md").read_text(encoding="utf-8"))
    names = _reference_order(sorted(p.name for p in refs_dir.glob("*.md")))
    references = [(n, (refs_dir / n).read_text(encoding="utf-8")) for n in names]
    _write(out / "exports" / "knowledge.md", render_export(body, references))
    report_format = dict(references).get("report-format.md")
    export_path = out / "exports" / "system-prompt.md"
    _write(export_path, render_compact_export(body, report_format, catalog))
    return BuildResult(pkg, zip_path, export_path, catalog, warnings, flat_zip_path, size)


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
    if result.skill_size:
        size = result.skill_size
        print(
            f"build: SKILL.md {size['lines']} lines, {size['chars']} characters, about {size['tokens']} "
            f"tokens (limits {MAX_SKILL_LINES} lines, about {MAX_SKILL_TOKENS} tokens)"
        )
    print(
        f"build: wrote {result.package_dir}, {result.zip_path}, {result.flat_zip_path}, {result.export_path}"
    )
    return 0
