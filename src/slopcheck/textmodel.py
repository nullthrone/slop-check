"""Text model: paragraph units, sentences, words and language (architecture section 4.2).

All offsets refer to the original text. YAML front matter and fenced code blocks are
replaced by spaces in an analysis copy (``TextModel.masked``) of the same length, so every
offset found in the masked copy is also valid in the original text.

Paragraph units:

- Blocks are separated by blank lines.
- Inside a block, Markdown headings, list items and table rows are units of their own.
  Consecutive plain lines form a ``paragraph`` unit; a plain line right after a list item
  continues that item.
- Horizontal rules and table separator rows belong to no unit.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field

# Unicode word tokens without underscores (so that Markdown ``__bold__`` and ``_italic_``
# markers are not part of words), with apostrophes inside words.
WORD_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)*")

PROSE_KINDS = ("paragraph", "list_item")

# Fences may be indented further than CommonMark's three spaces: inside list items (nested
# lists in particular) a fence is indented by the item's content offset. An indented code
# block whose content is a fence line is code as well, so masking it loses no prose.
_FENCE_OPEN_RE = re.compile(r"[ \t]*(`{3,}|~{3,})")
_FENCE_CLOSE_RE = re.compile(r"[ \t]*(`{3,}|~{3,})[ \t\r]*$")
_FRONT_MATTER_MAX_LINES = 100
_QUOTE_PREFIX_RE = re.compile(r"[ \t]*(?:>[ \t]?)+")
_QUOTE_MARKERS_RE = re.compile(r"(?:>[ \t]*)+")
_HEADING_RE = re.compile(r"[ ]{0,3}#{1,6}(?:[ \t]+|$)")
_LIST_RE = re.compile(r"[ \t]*(?:[-*+•◦▪‣]|\d{1,9}[.)])[ \t]+")
_TABLE_RE = re.compile(r"[ \t]*\|")
_HR_RE = re.compile(r"[ ]{0,3}(?:(?:-[ \t]*){3,}|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,})\r?$")
_TABLE_SEP_RE = re.compile(r"[ \t]*\|?[ \t]*:?-{2,}:?[ \t]*(?:\|[ \t]*:?-{2,}:?[ \t]*)*\|?[ \t\r]*$")

# Sentence end candidates: terminal punctuation, optional closing quotes or brackets,
# followed by whitespace.
_SENT_END_RE = re.compile(r"[.!?…]+[\"'”’»«)\]]*(?=\s)")
_SENT_OPENERS = set("\"'„“”‚‘’«»([¿¡*_")

# Characters skipped between a unit or sentence start and the first real character
# (opening quotes, brackets, emphasis markup). Used by position rules.
LEAD_SKIP = " \t\r\n\"'„“”‚‘’«»([*_`"
# Characters allowed between a hit end and the end of its paragraph (paragraph_end).
TAIL_SKIP = " \t\r\n.,;:!?…\"'”’»«)]*_`—–-"

ABBREVIATIONS = {
    "en": frozenset(
        {
            "mr",
            "mrs",
            "ms",
            "dr",
            "prof",
            "sr",
            "jr",
            "st",
            "vs",
            "e.g",
            "i.e",
            "cf",
            "fig",
            "figs",
            "no",
            "nos",
            "vol",
            "vols",
            "approx",
            "inc",
            "ltd",
            "co",
            "corp",
            "dept",
            "jan",
            "feb",
            "mar",
            "apr",
            "jun",
            "jul",
            "aug",
            "sep",
            "sept",
            "oct",
            "nov",
            "dec",
            "u.s",
            "u.k",
            "ph.d",
            "pp",
            "ch",
            "sec",
            "eq",
            "ed",
            "eds",
            "rev",
            "gen",
            "col",
            "lt",
            "sgt",
            "mt",
            "ft",
            "al",
        }
    ),
    "de": frozenset(
        {
            "z.b",
            "d.h",
            "u.a",
            "u.ä",
            "o.ä",
            "bzw",
            "ca",
            "vgl",
            "ggf",
            "evtl",
            "inkl",
            "zzgl",
            "exkl",
            "nr",
            "dr",
            "prof",
            "hr",
            "fr",
            "abs",
            "bd",
            "bzgl",
            "sog",
            "max",
            "min",
            "mio",
            "mrd",
            "jh",
            "jhd",
            "str",
            "tel",
            "gem",
            "lt",
            "z.t",
            "u.u",
            "v.a",
            "i.d.r",
            "d.i",
            "o.g",
            "u.v.m",
            "allg",
            "anm",
            "dt",
            "engl",
            "frz",
            "geb",
            "gest",
            "hrsg",
            "kap",
            "mind",
            "rd",
            "ebd",
            "vs",
            "jan",
            "feb",
            "apr",
            "aug",
            "sept",
            "okt",
            "nov",
            "dez",
            "s",
            "art",
        }
    ),
}

# Stopwords for language detection. Words that are frequent in both languages
# (in, an, am, so, was, will, also, man) are left out on purpose.
STOPWORDS = {
    "de": frozenset(
        {
            "der",
            "die",
            "das",
            "und",
            "ist",
            "nicht",
            "mit",
            "von",
            "zu",
            "auf",
            "für",
            "sich",
            "ein",
            "eine",
            "einen",
            "einem",
            "einer",
            "sind",
            "wir",
            "sie",
            "ich",
            "du",
            "es",
            "er",
            "auch",
            "aber",
            "wie",
            "wenn",
            "dass",
            "noch",
            "nach",
            "bei",
            "aus",
            "um",
            "nur",
            "über",
            "werden",
            "wird",
            "kann",
            "können",
            "haben",
            "hat",
            "durch",
            "diese",
            "dieser",
            "dieses",
            "des",
            "den",
            "dem",
            "im",
            "vom",
            "zum",
            "zur",
            "bis",
            "schon",
            "oder",
            "sehr",
            "kein",
            "keine",
            "mehr",
            "uns",
            "unsere",
            "unser",
            "ihr",
            "ihre",
            "seine",
            "jetzt",
            "war",
            "wurde",
            "sowie",
            "doch",
            "weil",
            "dann",
            "hier",
            "alle",
        }
    ),
    "en": frozenset(
        {
            "the",
            "and",
            "of",
            "to",
            "is",
            "are",
            "were",
            "be",
            "been",
            "it",
            "its",
            "it's",
            "that",
            "this",
            "these",
            "those",
            "with",
            "for",
            "on",
            "at",
            "by",
            "from",
            "as",
            "or",
            "not",
            "but",
            "have",
            "has",
            "had",
            "they",
            "we",
            "you",
            "he",
            "she",
            "i",
            "our",
            "your",
            "their",
            "there",
            "which",
            "who",
            "what",
            "when",
            "how",
            "if",
            "can",
            "would",
            "should",
            "could",
            "do",
            "does",
            "did",
            "a",
            "into",
            "about",
            "than",
            "then",
            "more",
            "all",
            "any",
            "some",
            "just",
            "only",
            "very",
            "out",
            "don't",
            "isn't",
            "we're",
            "you're",
            "i'm",
            "that's",
            "there's",
            "let's",
            "after",
            "before",
        }
    ),
}


@dataclass
class Sentence:
    """A sentence span inside a unit, with its word count."""

    start: int
    end: int
    words: int


@dataclass
class Unit:
    """A paragraph unit: prose paragraph, heading, list item or table row.

    ``start`` is the first visible character of the unit (Markdown markers included),
    ``body_start`` the first character after heading, list or blockquote markers,
    ``end`` the end of the last line without trailing whitespace. ``index`` is 1-based.
    """

    index: int
    kind: str
    block: int
    start: int
    body_start: int
    end: int
    line: int
    sentences: list[Sentence] = field(default_factory=list)
    word_spans: list[tuple[int, int]] = field(default_factory=list)

    @property
    def word_count(self) -> int:
        return len(self.word_spans)


@dataclass
class TextModel:
    """Segmented view of one text. Build it with :func:`build_text_model`."""

    text: str
    masked: str
    language: str
    units: list[Unit]
    line_starts: list[int]
    _unit_starts: list[int] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._unit_starts = [u.start for u in self.units]

    @property
    def word_count(self) -> int:
        return sum(u.word_count for u in self.units)

    @property
    def last_block(self) -> int:
        return self.units[-1].block if self.units else -1

    def unit_at(self, offset: int) -> Unit | None:
        """Return the unit that contains ``offset`` (or None)."""
        i = bisect.bisect_right(self._unit_starts, offset) - 1
        if i < 0:
            return None
        unit = self.units[i]
        return unit if offset < unit.end else None

    def line_of(self, offset: int) -> int:
        """Return the 1-based line number of ``offset``."""
        return bisect.bisect_right(self.line_starts, offset)

    def sentence_at(self, unit: Unit, offset: int) -> Sentence | None:
        """Return the sentence of ``unit`` that contains ``offset`` (or None)."""
        for sentence in unit.sentences:
            if sentence.start <= offset < sentence.end:
                return sentence
        return None

    def units_of(self, kinds: tuple[str, ...]) -> list[Unit]:
        return [u for u in self.units if u.kind in kinds]

    def sentence_count(self, kinds: tuple[str, ...] = PROSE_KINDS) -> int:
        return sum(len(u.sentences) for u in self.units if u.kind in kinds)


# ---------------------------------------------------------------------------
# Lines and code masking


def _line_spans(text: str) -> list[tuple[int, int]]:
    """Return (start, end) per line; ``end`` excludes the newline."""
    spans = []
    pos = 0
    for line in text.split("\n"):
        spans.append((pos, pos + len(line)))
        pos += len(line) + 1
    return spans


def _front_matter_end(text: str, spans: list[tuple[int, int]]) -> int | None:
    """Index of the line that closes YAML front matter, or None.

    Front matter starts with a ``---`` line at the very start of the text and ends at the next
    ``---`` line within the first 100 lines.
    """
    if not spans or text[spans[0][0] : spans[0][1]].rstrip("\r") != "---":
        return None
    for i in range(1, min(len(spans), _FRONT_MATTER_MAX_LINES)):
        if text[spans[i][0] : spans[i][1]].rstrip() == "---":
            return i
    return None


def mask_code(text: str) -> str:
    """Replace YAML front matter and fenced code blocks (fence lines included) by spaces,
    keeping newlines.

    An unclosed fence runs to the end of the text, as in CommonMark. A backtick line whose
    info string contains a backtick (```` ```code``` ````) is inline code, not a fence.
    """
    spans = _line_spans(text)
    ranges = []
    front_end = _front_matter_end(text, spans)
    if front_end is not None:
        ranges.extend(spans[: front_end + 1])
        spans = spans[front_end + 1 :]
    fence: tuple[str, int] | None = None
    for start, end in spans:
        line = text[start:end]
        if fence is None:
            m = _FENCE_OPEN_RE.match(line)
            if m and not (m.group(1)[0] == "`" and "`" in line[m.end() :]):
                fence = (m.group(1)[0], len(m.group(1)))
                ranges.append((start, end))
            continue
        ranges.append((start, end))
        m = _FENCE_CLOSE_RE.match(line)
        if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= fence[1]:
            fence = None
    if not ranges:
        return text
    parts = []
    pos = 0
    for start, end in ranges:
        parts.append(text[pos:start])
        parts.append(" " * (end - start))
        pos = end
    parts.append(text[pos:])
    return "".join(parts)


# ---------------------------------------------------------------------------
# Units


def _classify(masked: str, start: int, end: int) -> tuple[str | None, int]:
    """Classify one line. Returns (kind, body_start); kind None means skip the line.

    kind is one of ``heading``, ``list_item``, ``table_row``, ``rule`` (skipped),
    ``text`` (plain line).
    """
    line = masked[start:end]
    qm = _QUOTE_PREFIX_RE.match(line)
    offset = qm.end() if qm and ">" in qm.group(0) else 0
    body = line[offset:]
    if _HR_RE.match(body) or _TABLE_SEP_RE.match(body):
        return "rule", start + offset
    for kind, rx in (("heading", _HEADING_RE), ("list_item", _LIST_RE), ("table_row", _TABLE_RE)):
        m = rx.match(body)
        if m:
            body_start = start + offset + (m.end() if kind != "table_row" else 0)
            return kind, body_start
    lead = len(body) - len(body.lstrip())
    return "text", start + offset + lead


def _build_units(masked: str, line_spans: list[tuple[int, int]]) -> list[dict]:
    """Group lines into raw unit dicts (kind, block, start, body_start, end, line)."""
    units: list[dict] = []
    current: dict | None = None
    block = 0
    in_block = False
    for line_no, (start, end) in enumerate(line_spans, start=1):
        if not masked[start:end].strip():
            current = None
            if in_block:
                block += 1
                in_block = False
            continue
        in_block = True
        kind, body_start = _classify(masked, start, end)
        stripped_end = start + len(masked[start:end].rstrip())
        visible_start = start + (len(masked[start:end]) - len(masked[start:end].lstrip()))
        if kind == "rule":
            current = None
            continue
        if kind == "text" and current is not None and current["kind"] in ("paragraph", "list_item"):
            current["end"] = stripped_end
            continue
        current = {
            "kind": "paragraph" if kind == "text" else kind,
            "block": block,
            "start": visible_start,
            "body_start": body_start,
            "end": stripped_end,
            "line": line_no,
        }
        units.append(current)
        if kind in ("heading", "table_row"):
            current = None
    return units


# ---------------------------------------------------------------------------
# Sentences and words


def _is_abbreviation(text: str, dot: int, lang: str) -> bool:
    """True if the period at ``dot`` closes an abbreviation, an initial or a German ordinal."""
    k = dot
    while k > 0 and not text[k - 1].isspace():
        k -= 1
    token = text[k:dot].lstrip("\"'„“‚‘«»([*_").lower()
    if not token:
        return False
    if len(token) == 1 and token.isalpha():
        return True
    if lang == "de" and token.isdigit() and len(token) <= 3:
        return True
    if lang in ABBREVIATIONS:
        return token in ABBREVIATIONS[lang]
    return token in ABBREVIATIONS["en"] or token in ABBREVIATIONS["de"]


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def split_sentences(text: str, start: int, end: int, lang: str) -> list[tuple[int, int]]:
    """Split ``text[start:end]`` into sentence spans.

    A sentence ends at ``.``, ``!``, ``?`` or ``…`` (optionally followed by closing quotes
    or brackets) when whitespace and an uppercase letter, digit or opening quote follow,
    unless the period closes an abbreviation of ``lang`` (both lists for ``und``). After a
    line break, blockquote markers (``>``) are skipped before that check.
    """
    spans = []
    cur = start
    for m in _SENT_END_RE.finditer(text, start, end):
        j = m.end()
        while j < end and text[j].isspace():
            j += 1
        if "\n" in text[m.end() : j]:
            q = _QUOTE_MARKERS_RE.match(text, j, end)
            if q:
                j = q.end()
        if j >= end:
            break
        nxt = text[j]
        if not (nxt.isupper() or nxt.isdigit() or nxt in _SENT_OPENERS):
            continue
        if m.group(0)[0] == "." and len(m.group(0).rstrip("\"'”’»«)]")) == 1:
            if _is_abbreviation(text, m.start(), lang):
                continue
        span = _trim(text, cur, m.end())
        if span[1] > span[0]:
            spans.append(span)
        cur = j
    span = _trim(text, cur, end)
    if span[1] > span[0]:
        spans.append(span)
    return spans


def word_spans(text: str, start: int = 0, end: int | None = None) -> list[tuple[int, int]]:
    """Return word token spans in ``text[start:end]``."""
    end = len(text) if end is None else end
    return [m.span() for m in WORD_RE.finditer(text, start, end)]


# ---------------------------------------------------------------------------
# Language detection


def _normalize_word(word: str) -> str:
    return word.lower().replace("’", "'")


def detect_language_from_words(words: list[str]) -> str:
    """Return ``de``, ``en`` or ``und`` from stopword frequencies.

    A language wins with at least 2 stopword hits and more than 1.5 times the hits of
    the other language; otherwise the result is ``und``.
    """
    counts = {lang: 0 for lang in STOPWORDS}
    for word in words:
        w = _normalize_word(word)
        for lang, stop in STOPWORDS.items():
            if w in stop:
                counts[lang] += 1
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    (best, best_n), (_, other_n) = ranked[0], ranked[1]
    if best_n >= 2 and best_n > 1.5 * other_n:
        return best
    return "und"


def detect_language(text: str) -> str:
    """Detect ``de`` or ``en`` for a text (fenced code ignored); ``und`` below confidence."""
    masked = mask_code(text)
    return detect_language_from_words([m.group(0) for m in WORD_RE.finditer(masked)])


# ---------------------------------------------------------------------------
# Build


def build_text_model(text: str, lang: str | None = None) -> TextModel:
    """Segment ``text``. ``lang`` None (or ``auto``) detects the language; region
    subtags are dropped (``de-DE`` becomes ``de``)."""
    masked = mask_code(text)
    spans = _line_spans(text)
    if lang in (None, "", "auto"):
        language = detect_language_from_words([m.group(0) for m in WORD_RE.finditer(masked)])
    else:
        language = lang.split("-")[0].split("_")[0].lower()
    units = []
    for i, raw in enumerate(_build_units(masked, spans), start=1):
        unit = Unit(index=i, **raw)
        unit.word_spans = word_spans(masked, unit.body_start, unit.end)
        for s, e in split_sentences(masked, unit.body_start, unit.end, language):
            n = len(WORD_RE.findall(masked, s, e))
            if n:
                unit.sentences.append(Sentence(s, e, n))
        units.append(unit)
    line_starts = [s for s, _ in spans]
    return TextModel(text=text, masked=masked, language=language, units=units, line_starts=line_starts)
