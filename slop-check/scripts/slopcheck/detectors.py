"""Regex and lexicon detectors, hit construction and position rules (section 4.3).

A hit is a dict ``{"quote", "paragraph", "line", "start", "end"}``. ``start`` and ``end``
are offsets into the original text, ``paragraph`` is the 1-based unit index and ``line``
the 1-based line number of ``start``.

Compiled regexes are cached by pattern id and payload, so repeated analyses with the same
catalog compile every expression once.
"""

from __future__ import annotations

import re
from functools import lru_cache

from .textmodel import LEAD_SKIP, TAIL_SKIP, TextModel

POSITIONS = ("any", "text_start", "paragraph_start", "paragraph_end", "last_paragraph", "sentence_start")

# Regex and lexicon quotes are trimmed of whitespace and sentence punctuation.
QUOTE_TRIM = " \t\r\n\f\v .,;:!?…—–-"
# Metric evidence keeps punctuation (an em dash must stay visible in its quote).
SPACE_TRIM = " \t\r\n\f\v "


def make_hit(model: TextModel, start: int, end: int, trim: str = QUOTE_TRIM) -> dict | None:
    """Build a hit for ``text[start:end]`` after trimming ``trim`` characters.

    Returns None if nothing is left or the span starts outside every paragraph unit
    (for example inside a fenced code block).
    """
    masked = model.masked
    while start < end and masked[start] in trim:
        start += 1
    while end > start and masked[end - 1] in trim:
        end -= 1
    if start >= end:
        return None
    unit = model.unit_at(start)
    if unit is None:
        return None
    return {
        "quote": model.text[start:end],
        "paragraph": unit.index,
        "line": model.line_of(start),
        "start": start,
        "end": end,
    }


def _only(text: str, start: int, end: int, allowed: str) -> bool:
    """True if ``text[start:end]`` consists only of ``allowed`` characters."""
    return all(ch in allowed for ch in text[start:end])


def position_ok(model: TextModel, hit: dict, position: str | None) -> bool:
    """Check a hit against a detector position rule.

    - ``text_start``: hit starts the first unit of the text.
    - ``paragraph_start``: hit starts its unit (after Markdown markers, opening quotes
      and emphasis markup).
    - ``paragraph_end``: only whitespace, punctuation, closing quotes or markup follow
      the hit inside its unit.
    - ``last_paragraph``: hit lies in the last blank-line separated block.
    - ``sentence_start``: hit starts a sentence.
    """
    if position in (None, "", "any"):
        return True
    unit = model.unit_at(hit["start"])
    if unit is None:
        return False
    start, end = hit["start"], hit["end"]
    if position == "paragraph_start":
        return _only(model.masked, unit.body_start, start, LEAD_SKIP)
    if position == "text_start":
        return unit is model.units[0] and _only(model.masked, unit.body_start, start, LEAD_SKIP)
    if position == "paragraph_end":
        return _only(model.masked, end, unit.end, TAIL_SKIP)
    if position == "last_paragraph":
        return unit.block == model.last_block
    if position == "sentence_start":
        sentence = model.sentence_at(unit, start)
        return sentence is not None and _only(model.masked, sentence.start, start, LEAD_SKIP)
    raise ValueError(f"unknown detector position: {position!r}")


def select_non_overlapping(hits: list[dict]) -> list[dict]:
    """Keep the earliest (and on ties the longest) of overlapping hits, in text order."""
    ordered = sorted(hits, key=lambda h: (h["start"], -(h["end"] - h["start"])))
    kept: list[dict] = []
    for hit in ordered:
        if kept and hit["start"] < kept[-1]["end"]:
            continue
        kept.append(hit)
    return kept


# ---------------------------------------------------------------------------
# Regex


@lru_cache(maxsize=4096)
def compile_regexes(key: str, patterns: tuple[str, ...]) -> tuple[re.Pattern, ...]:
    """Compile regex payloads with ``re.MULTILINE``. Raises ValueError naming ``key``."""
    compiled = []
    for source in patterns:
        try:
            compiled.append(re.compile(source, re.MULTILINE))
        except re.error as exc:
            raise ValueError(f"pattern {key}: invalid regex {source!r}: {exc}") from exc
    return tuple(compiled)


def regex_hits(model: TextModel, key: str, patterns: list[str], position: str | None) -> list[dict]:
    """Run regex payloads over the text (code masked) and return position-filtered hits."""
    candidates = []
    for rx in compile_regexes(key, tuple(patterns)):
        for m in rx.finditer(model.masked):
            if m.end() <= m.start():
                continue
            hit = make_hit(model, m.start(), m.end())
            if hit is not None and position_ok(model, hit, position):
                candidates.append(hit)
    return select_non_overlapping(candidates)


# ---------------------------------------------------------------------------
# Lexicon


def term_regex(term: str) -> str:
    """Translate one lexicon term into a regex body.

    Words of a multi-word term match across any whitespace, straight and curly
    apostrophes are interchangeable, and a trailing ``*`` matches any word ending.
    """
    term = term.strip()
    prefix = term.endswith("*")
    core = term[:-1].strip() if prefix else term
    parts = [re.sub(r"['’]", "['’]", re.escape(p)) for p in core.split()]
    body = r"\s+".join(parts)
    return body + r"[^\W_]*" if prefix else body


@lru_cache(maxsize=4096)
def compile_lexicon(key: str, terms: tuple[str, ...]) -> re.Pattern | None:
    """Compile lexicon terms into one case-insensitive whole-word alternation.

    Longer terms come first, so that a multi-word term wins over its first word.
    Returns None for an empty term list.
    """
    cores = sorted({t.strip() for t in terms if t.strip(" *")}, key=lambda t: (-len(t.rstrip("*")), t))
    if not cores:
        return None
    body = "|".join(term_regex(t) for t in cores)
    try:
        return re.compile(rf"(?<![^\W_])(?:{body})(?![^\W_])", re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"pattern {key}: invalid lexicon term: {exc}") from exc


def lexicon_hits(model: TextModel, key: str, terms: list[str], position: str | None) -> list[dict]:
    """Return whole-word, case-insensitive term hits, filtered by position."""
    rx = compile_lexicon(key, tuple(terms))
    if rx is None:
        return []
    hits = []
    for m in rx.finditer(model.masked):
        hit = make_hit(model, m.start(), m.end())
        if hit is not None and position_ok(model, hit, position):
            hits.append(hit)
    return hits
