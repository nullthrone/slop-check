"""Metric registry (architecture section 4.3).

Every metric receives a :class:`MetricInput` and returns a :class:`MetricResult` with

- ``value``: the number compared with ``threshold.value`` (None if the metric cannot be
  computed, for example a density over zero words);
- ``hits``: evidence spans;
- ``units``: the number of units the metric looked at, compared with
  ``threshold.min_units``. The unit (sentences or paragraphs) is declared per metric.

Count metrics, whose value is a number of instances (curly quotes, decorated lines,
triads, bold-lead items), report every instance as a hit. Aggregate metrics
(``aggregate=True``: densities, ratios, variation) turn instances into one value, so a
single instance is no finding on its own: the engine reports their hits as evidence only
when the value rule is met. Without a value rule, hits are always reported.

Adding a metric needs a code change here and an enum entry in the pattern schema.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Callable
from dataclasses import dataclass, field

from .detectors import SPACE_TRIM, compile_lexicon, make_hit
from .textmodel import LEAD_SKIP, PROSE_KINDS, STOPWORDS, WORD_RE, TextModel, Unit


@dataclass
class MetricInput:
    """Arguments for a metric function.

    ``units`` are the units in scope: all units of the text, or a single unit when the
    threshold scope is ``paragraph``. ``terms`` is the merged lexicon of the realization.
    ``direction`` is ``low`` for lt/lte value rules and ``high`` otherwise; aggregate
    metrics use it to pick their evidence.
    """

    model: TextModel
    units: list[Unit]
    params: dict = field(default_factory=dict)
    lang: str = "und"
    terms: list[str] = field(default_factory=list)
    direction: str = "high"
    key: str = ""


@dataclass
class MetricResult:
    value: float | None
    hits: list[dict]
    units: int


@dataclass(frozen=True)
class MetricSpec:
    name: str
    fn: Callable[[MetricInput], MetricResult]
    unit: str
    aggregate: bool


METRICS: dict[str, MetricSpec] = {}


def metric(name: str, unit: str, aggregate: bool = False):
    """Register a metric function under ``name``."""

    def register(fn: Callable[[MetricInput], MetricResult]):
        METRICS[name] = MetricSpec(name=name, fn=fn, unit=unit, aggregate=aggregate)
        return fn

    return register


# ---------------------------------------------------------------------------
# Helpers

_FUNCTION_WORDS = STOPWORDS["de"] | STOPWORDS["en"] | {"and", "or", "und", "oder", "in", "an", "am", "was"}


def _words(units: list[Unit]) -> int:
    return sum(u.word_count for u in units)


def _sentences(units: list[Unit], kinds: tuple[str, ...] = PROSE_KINDS) -> int:
    return sum(len(u.sentences) for u in units if u.kind in kinds)


def _density(count: int, words: int, per_words: float) -> float | None:
    return None if words == 0 else count * per_words / words


def _per_words(params: dict, default: int = 100) -> float:
    value = params.get("per_words")
    return float(value) if value else float(default)


def _kinds(params: dict, default: tuple[str, ...]) -> tuple[str, ...]:
    kinds = params.get("unit_kinds")
    return tuple(kinds) if kinds else default


def _context_hit(model: TextModel, unit: Unit, start: int, end: int, words: int = 3) -> dict | None:
    """Hit for a short span (one character) widened by up to ``words`` words per side,
    kept on the same line."""
    before = [w for w in unit.word_spans if w[1] <= start][-words:]
    after = [w for w in unit.word_spans if w[0] >= end][:words]
    s = before[0][0] if before else start
    e = after[-1][1] if after else end
    line_start = model.masked.rfind("\n", 0, start) + 1
    line_end = model.masked.find("\n", end)
    if line_end == -1:
        line_end = len(model.masked)
    return make_hit(model, max(s, line_start), min(e, line_end), trim=SPACE_TRIM)


def _span_hit(model: TextModel, start: int, end: int) -> dict | None:
    return make_hit(model, start, end, trim=SPACE_TRIM)


def _lines(model: TextModel, unit: Unit) -> list[tuple[int, int]]:
    """(start, end) of each line of a unit."""
    spans = []
    pos = unit.start
    for line in model.masked[unit.start : unit.end].split("\n"):
        spans.append((pos, pos + len(line)))
        pos += len(line) + 1
    return spans


# ---------------------------------------------------------------------------
# em_dash_density

_DASH_RE = re.compile(r"—|(?<=\s)–(?=\s)")


@metric("em_dash_density", unit="sentences", aggregate=True)
def em_dash_density(inp: MetricInput) -> MetricResult:
    """Em dashes (U+2014) and en dashes (U+2013) between whitespace, per ``per_words`` words.

    params: ``per_words`` (default 100). Hits: each dash with up to three words of context.
    """
    model = inp.model
    hits = []
    for unit in inp.units:
        for m in _DASH_RE.finditer(model.masked, unit.start, unit.end):
            hit = _context_hit(model, unit, m.start(), m.end())
            if hit:
                hits.append(hit)
    value = _density(len(hits), _words(inp.units), _per_words(inp.params))
    return MetricResult(value, hits, _sentences(inp.units))


# ---------------------------------------------------------------------------
# curly_quotes

_CURLY_RE = re.compile("[“”‘’]")


@metric("curly_quotes", unit="sentences")
def curly_quotes(inp: MetricInput) -> MetricResult:
    """Count of U+201C, U+201D, U+2018 and U+2019 (also as apostrophe).

    params: ``exempt_languages`` (default []): languages in which curly quotes are
    regular typography; the value is 0 there. Hits: each character with context.
    """
    if inp.lang in (inp.params.get("exempt_languages") or []):
        return MetricResult(0.0, [], _sentences(inp.units))
    model = inp.model
    hits = []
    for unit in inp.units:
        for m in _CURLY_RE.finditer(model.masked, unit.start, unit.end):
            hit = _context_hit(model, unit, m.start(), m.end(), words=2)
            if hit:
                hits.append(hit)
    return MetricResult(float(len(hits)), hits, _sentences(inp.units))


# ---------------------------------------------------------------------------
# sentence_length_cv


@metric("sentence_length_cv", unit="sentences", aggregate=True)
def sentence_length_cv(inp: MetricInput) -> MetricResult:
    """Minimum, over runs of ``run`` consecutive prose paragraphs, of the coefficient of
    variation (population standard deviation / mean) of sentence length in words, pooled
    over the sentences of the run.

    params: ``run`` (default 3), ``unit_kinds`` (default ["paragraph"]; headings, list
    items and table rows are skipped). Value None with fewer than ``run`` paragraphs.
    Evidence: the paragraphs of the run with the lowest value.
    """
    run = int(inp.params.get("run") or 3)
    kinds = _kinds(inp.params, ("paragraph",))
    paragraphs = [u for u in inp.units if u.kind in kinds]
    units = _sentences(paragraphs, kinds)
    best: tuple[float, int] | None = None
    for i in range(len(paragraphs) - run + 1):
        lengths = [s.words for u in paragraphs[i : i + run] for s in u.sentences]
        if len(lengths) < 2:
            continue
        mean = sum(lengths) / len(lengths)
        cv = statistics.pstdev(lengths) / mean
        if best is None or cv < best[0]:
            best = (cv, i)
    if best is None:
        return MetricResult(None, [], units)
    hits = [
        h for u in paragraphs[best[1] : best[1] + run] if (h := _span_hit(inp.model, u.body_start, u.end))
    ]
    return MetricResult(best[0], hits, units)


# ---------------------------------------------------------------------------
# emoji_decoration

_DECOR_RANGES = (
    (0x2190, 0x21FF),  # arrows
    (0x2300, 0x23FF),  # miscellaneous technical (watch, hourglass, play buttons)
    (0x25A0, 0x25FF),  # geometric shapes
    (0x2600, 0x27BF),  # miscellaneous symbols, dingbats (check marks, stars, sparkles)
    (0x27F0, 0x27FF),  # supplemental arrows A
    (0x2900, 0x297F),  # supplemental arrows B
    (0x2B00, 0x2BFF),  # miscellaneous symbols and arrows (star, circle)
    (0x1F000, 0x1FAFF),  # emoji and pictographs
)
_DECOR_SINGLE = frozenset({0x203C, 0x2049, 0x2139, 0x3030, 0x303D})
_LINE_MARKER_RE = re.compile(r"[ \t]*(?:>[ \t]?)*(?:#{1,6}[ \t]+|(?:[-*+]|\d{1,9}[.)])[ \t]+)?")


def is_decorative(text: str) -> bool:
    """True if ``text`` starts with an emoji or decorative symbol (keycaps included).

    Plain bullets (U+2022) and box drawing characters are not decorative.
    """
    if not text:
        return False
    if len(text) > 1 and "⃣" in text[1:3]:
        return True
    cp = ord(text[0])
    return cp in _DECOR_SINGLE or any(lo <= cp <= hi for lo, hi in _DECOR_RANGES)


@metric("emoji_decoration", unit="paragraphs")
def emoji_decoration(inp: MetricInput) -> MetricResult:
    """Count of lines whose first character after Markdown markers (heading, list,
    blockquote) is an emoji or decorative symbol.

    params: none. Hits: each decorated line.
    """
    model = inp.model
    hits = []
    for unit in inp.units:
        for start, end in _lines(model, unit):
            m = _LINE_MARKER_RE.match(model.masked, start, end)
            pos = m.end() if m else start
            if is_decorative(model.masked[pos:end]):
                hit = _span_hit(model, start, end)
                if hit:
                    hits.append(hit)
    return MetricResult(float(len(hits)), hits, len(inp.units))


# ---------------------------------------------------------------------------
# markdown_emphasis_density

_BOLD_RE = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_ITALIC_RE = re.compile(
    r"(?<![*\w])\*(?=[^\s*])[^*\n]+?(?<=[^\s*])\*(?![*\w])"
    r"|(?<![_\w])_(?=[^\s_])[^_\n]+?(?<=[^\s_])_(?![_\w])"
)


@metric("markdown_emphasis_density", unit="sentences", aggregate=True)
def markdown_emphasis_density(inp: MetricInput) -> MetricResult:
    """Bold spans, italic spans and headings per ``per_words`` words.

    Each ``**bold**``/``__bold__`` span, each ``*italic*``/``_italic_`` span and each
    Markdown heading counts once. params: ``per_words`` (default 100). Hits: each span or
    heading line.
    """
    model = inp.model
    hits = []
    for unit in inp.units:
        if unit.kind == "heading":
            hit = _span_hit(model, unit.start, unit.end)
            if hit:
                hits.append(hit)
        segment = model.masked[unit.body_start : unit.end]
        blanked = list(segment)
        for m in _BOLD_RE.finditer(segment):
            hit = _span_hit(model, unit.body_start + m.start(), unit.body_start + m.end())
            if hit:
                hits.append(hit)
            marker = len(m.group(1))
            for i in [*range(m.start(), m.start() + marker), *range(m.end() - marker, m.end())]:
                blanked[i] = " "
        for m in _ITALIC_RE.finditer("".join(blanked)):
            hit = _span_hit(model, unit.body_start + m.start(), unit.body_start + m.end())
            if hit:
                hits.append(hit)
    hits.sort(key=lambda h: h["start"])
    value = _density(len(hits), _words(inp.units), _per_words(inp.params))
    return MetricResult(value, hits, _sentences(inp.units))


# ---------------------------------------------------------------------------
# paragraph_start_ratio


@metric("paragraph_start_ratio", unit="paragraphs", aggregate=True)
def paragraph_start_ratio(inp: MetricInput) -> MetricResult:
    """Share of prose paragraphs that start with a term of the realization's ``terms``
    (whole word, case-insensitive, ``term*`` = prefix).

    params: ``unit_kinds`` (default ["paragraph"]). Value None without paragraphs or
    terms. Hits: each opening term.
    """
    model = inp.model
    kinds = _kinds(inp.params, ("paragraph",))
    paragraphs = [u for u in inp.units if u.kind in kinds]
    rx = compile_lexicon(inp.key or "paragraph_start_ratio", tuple(inp.terms))
    if not paragraphs or rx is None:
        return MetricResult(None, [], len(paragraphs))
    hits = []
    for unit in paragraphs:
        pos = unit.body_start
        while pos < unit.end and model.masked[pos] in LEAD_SKIP:
            pos += 1
        m = rx.match(model.masked, pos, unit.end)
        if m:
            hit = make_hit(model, m.start(), m.end())
            if hit:
                hits.append(hit)
    return MetricResult(len(hits) / len(paragraphs), hits, len(paragraphs))


# ---------------------------------------------------------------------------
# nominalization_density

DEFAULT_SUFFIXES = {
    "de": ["ung", "heit", "keit", "tion", "sion", "tät", "ismus"],
    "en": ["tion", "sion", "ment", "ness", "ity", "ance", "ence"],
}


def _stems(word: str, lang: str):
    """The word itself plus its singular candidates (simple plural stripping)."""
    yield word
    if lang == "de" and word.endswith("en"):
        yield word[:-2]
    if lang == "en":
        if word.endswith("ies"):
            yield word[:-3] + "y"
        if word.endswith("es"):
            yield word[:-2]
        if word.endswith("s"):
            yield word[:-1]


@metric("nominalization_density", unit="sentences", aggregate=True)
def nominalization_density(inp: MetricInput) -> MetricResult:
    """Tokens with a nominal suffix per ``per_words`` words.

    params: ``per_words`` (default 100), ``min_word_length`` (default 6), ``suffixes``
    ({language: [suffix, ...]}, defaults for de and en). Plural forms count
    (``-en`` in German, ``-s``/``-es``/``-ies`` in English). Value None for a language
    without suffix list. Hits: each token.
    """
    model = inp.model
    suffixes = (inp.params.get("suffixes") or {}).get(inp.lang) or DEFAULT_SUFFIXES.get(inp.lang)
    if not suffixes:
        return MetricResult(None, [], _sentences(inp.units))
    min_len = int(inp.params.get("min_word_length") or 6)
    ends = tuple(s.lower() for s in suffixes)
    hits = []
    for unit in inp.units:
        for start, end in unit.word_spans:
            word = model.masked[start:end].lower()
            if len(word) >= min_len and any(stem.endswith(ends) for stem in _stems(word, inp.lang)):
                hit = _span_hit(model, start, end)
                if hit:
                    hits.append(hit)
    value = _density(len(hits), _words(inp.units), _per_words(inp.params))
    return MetricResult(value, hits, _sentences(inp.units))


# ---------------------------------------------------------------------------
# bullet_bold_lead

_BOLD_LEAD_RE = re.compile(r"(\*\*|__)[^*_\n]{1,80}?(?::\1|\1[ \t]*:)")


@metric("bullet_bold_lead", unit="paragraphs")
def bullet_bold_lead(inp: MetricInput) -> MetricResult:
    """Longest run of consecutive list items shaped ``**lead**: text`` or ``**lead:** text``.

    A unit that is not a list item ends the list; a list item without a bold lead ends
    the run. params: none. Hits: the bold lead of every matching item.
    """
    model = inp.model
    hits = []
    best = run = 0
    items = 0
    for unit in inp.units:
        if unit.kind != "list_item":
            run = 0
            continue
        items += 1
        m = _BOLD_LEAD_RE.match(model.masked, unit.body_start, unit.end)
        if not m:
            run = 0
            continue
        run += 1
        best = max(best, run)
        hit = _span_hit(model, m.start(), m.end())
        if hit:
            hits.append(hit)
    return MetricResult(float(best), hits, items)


# ---------------------------------------------------------------------------
# triad

DEFAULT_CONJUNCTIONS = {"en": ["and", "or"], "de": ["und", "oder"]}
_WORD = r"[^\W\d_][^\W_]*(?:['’-][^\W_]+)*"


def _triad_regex(conjunctions: tuple[str, ...]) -> re.Pattern:
    conj = "|".join(re.escape(c) for c in conjunctions)
    return re.compile(
        rf"(?<![^\W_])({_WORD}),[ \t]+({_WORD}(?:[ \t]+{_WORD}){{0,2}}),?[ \t]+(?:{conj})[ \t]+({_WORD})",
        re.IGNORECASE,
    )


_TRIAD_CACHE: dict[tuple[str, ...], re.Pattern] = {}


def _introductory(model: TextModel, unit: Unit, m: re.Match) -> bool:
    """True if the comma after the first item closes an introductory phrase."""
    sentence = model.sentence_at(unit, m.start())
    start = sentence.start if sentence else unit.body_start
    prefix_words = len(WORD_RE.findall(model.masked, start, m.start()))
    first_middle = m.group(2).split()[0].lower()
    return prefix_words <= 1 and first_middle in _FUNCTION_WORDS


@metric("triad", unit="sentences")
def triad(inp: MetricInput) -> MetricResult:
    """Count of three-item coordinations ``A, B(,) and/or C`` (de: ``und``/``oder``).

    The middle item has 1 to 3 words; the first and last item are matched by their
    nearest word. A match preceded by a comma belongs to a longer enumeration and does
    not count. An introductory phrase does not count either: the first item is one of
    the first two words of its sentence and the middle item starts with a function word
    ("Today, our fast and cheap ...").

    params: ``conjunctions`` ({language: [word, ...]}, defaults en: and, or; de: und,
    oder; other languages use all defaults). Hits: each coordination.
    """
    model = inp.model
    table = inp.params.get("conjunctions") or DEFAULT_CONJUNCTIONS
    conj = table.get(inp.lang) or sorted({c for words in table.values() for c in words})
    key = tuple(conj)
    rx = _TRIAD_CACHE.get(key)
    if rx is None:
        rx = _TRIAD_CACHE[key] = _triad_regex(key)
    hits = []
    for unit in inp.units:
        for m in rx.finditer(model.masked, unit.body_start, unit.end):
            before = model.masked[unit.body_start : m.start()].rstrip()
            if before.endswith(",") or _introductory(model, unit, m):
                continue
            hit = make_hit(model, m.start(), m.end())
            if hit:
                hits.append(hit)
    return MetricResult(float(len(hits)), hits, _sentences(inp.units))


# ---------------------------------------------------------------------------
# comma_density

_COMMA_RE = re.compile(r",(?!\d)|(?<!\d),")


@metric("comma_density", unit="sentences", aggregate=True)
def comma_density(inp: MetricInput) -> MetricResult:
    """Commas per sentence. Commas between two digits (``4,2``, ``2,000``) do not count.

    params: ``unit_kinds`` (default ["paragraph", "list_item"]). Value None without
    sentences. Evidence: sentences without a comma for lt/lte rules, sentences with more
    commas than the mean otherwise.
    """
    model = inp.model
    kinds = _kinds(inp.params, PROSE_KINDS)
    sentences = [s for u in inp.units if u.kind in kinds for s in u.sentences]
    if not sentences:
        return MetricResult(None, [], 0)
    counts = [len(_COMMA_RE.findall(model.masked, s.start, s.end)) for s in sentences]
    value = sum(counts) / len(sentences)
    if inp.direction == "low":
        chosen = [s for s, c in zip(sentences, counts, strict=True) if c == 0]
    else:
        chosen = [s for s, c in zip(sentences, counts, strict=True) if c > value]
    hits = [h for s in chosen if (h := _span_hit(model, s.start, s.end))]
    return MetricResult(value, hits, len(sentences))


# ---------------------------------------------------------------------------
# hyphenated_premodifier_density

_HYPHEN_RE = re.compile(r"(?<![^\W_])([^\W_]+(?:-[^\W_]+)+)(?=,?[ \t]+([^\W\d_][^\W_]*))")


@metric("hyphenated_premodifier_density", unit="sentences", aggregate=True)
def hyphenated_premodifier_density(inp: MetricInput) -> MetricResult:
    """Hyphenated compound pre-modifiers per ``per_words`` words.

    A compound counts when its first part has at least two characters, its last part
    starts with a lowercase letter (adjective or participle, so German noun compounds
    such as ``Patch-Release`` stay out) and the next word is not a function word.
    params: ``per_words`` (default 100). Hits: each compound.
    """
    model = inp.model
    hits = []
    for unit in inp.units:
        for m in _HYPHEN_RE.finditer(model.masked, unit.body_start, unit.end):
            parts = m.group(1).split("-")
            if len(parts[0]) < 2 or not parts[-1][:1].islower():
                continue
            if m.group(2).lower() in _FUNCTION_WORDS:
                continue
            hit = _span_hit(model, m.start(1), m.end(1))
            if hit:
                hits.append(hit)
    value = _density(len(hits), _words(inp.units), _per_words(inp.params))
    return MetricResult(value, hits, _sentences(inp.units))
