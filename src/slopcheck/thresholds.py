"""Threshold rules (pattern field ``threshold``, architecture sections 3 and 4).

The effective rule for one analysis starts from the pattern's base threshold, then
applies ``short_text`` (texts with at most ``short_text_max_words`` words), then the
override for the requested context. Overrides replace keys shallowly.

Count rules compare the number of hits (or the density ``hits * per_words / words``)
with ``min_count``; scope ``paragraph`` triggers if any single paragraph reaches it.
Value rules compare a metric value with ``{op, x}``. ``min_units`` and ``min_words`` are
preconditions: below that many sentences or paragraphs (``min_units``, in the detector's unit)
or words of analyzed text (``min_words``) the rule never triggers.
"""

from __future__ import annotations

RULE_KEYS = ("min_count", "per_words", "comparison", "scope", "value", "min_units", "min_words")
DEFAULT_RULE = {
    "min_count": 1,
    "per_words": None,
    "comparison": "gte",
    "scope": "text",
    "value": None,
    "min_units": None,
    "min_words": None,
}
_EPS = 1e-9


def effective_rule(threshold: dict | None, short: bool = False, context: str = "default") -> dict:
    """Merge base threshold, short-text override and context override into one rule."""
    threshold = threshold or {}
    rule = dict(DEFAULT_RULE)
    rule.update({k: threshold[k] for k in RULE_KEYS if k in threshold})
    if short and threshold.get("short_text"):
        rule.update({k: v for k, v in threshold["short_text"].items() if k in RULE_KEYS})
    override = (threshold.get("context_overrides") or {}).get(context)
    if override:
        rule.update({k: v for k, v in override.items() if k in RULE_KEYS})
    return rule


def compare(measure: float, op: str, x: float) -> bool:
    """Compare with a small tolerance against floating point noise."""
    if op == "gte":
        return measure >= x - _EPS
    if op == "gt":
        return measure > x + _EPS
    if op == "lte":
        return measure <= x + _EPS
    if op == "lt":
        return measure < x - _EPS
    raise ValueError(f"unknown comparison: {op!r}")


def units_ok(rule: dict, units: int) -> bool:
    """True unless ``min_units`` is set and not reached."""
    return not rule.get("min_units") or units >= rule["min_units"]


def words_ok(rule: dict, words: int) -> bool:
    """True unless ``min_words`` is set and the analyzed text has fewer words."""
    return not rule.get("min_words") or words >= rule["min_words"]


def value_met(rule: dict, value: float | None) -> bool:
    """Evaluate a value rule. A missing value never triggers."""
    spec = rule.get("value")
    if not spec or value is None:
        return False
    return compare(value, spec["op"], spec["x"])


def count_met(rule: dict, hits: list[dict], words: int, paragraph_words: dict[int, int]) -> bool:
    """Evaluate a count rule on hits. At least one hit is always required.

    ``paragraph_words`` maps 1-based unit index to its word count (scope ``paragraph``
    with ``per_words``).
    """
    if not hits:
        return False
    op = rule.get("comparison") or "gte"
    min_count = rule.get("min_count")
    min_count = 1 if min_count is None else min_count
    per_words = rule.get("per_words")
    if rule.get("scope") == "paragraph":
        groups: dict[int, int] = {}
        for hit in hits:
            groups[hit["paragraph"]] = groups.get(hit["paragraph"], 0) + 1
        for paragraph, count in groups.items():
            measure = count
            if per_words:
                n = paragraph_words.get(paragraph, 0)
                measure = count * per_words / n if n else 0
            if compare(measure, op, min_count):
                return True
        return False
    measure = len(hits)
    if per_words:
        measure = len(hits) * per_words / words if words else 0
    return compare(measure, op, min_count)


# ---------------------------------------------------------------------------
# Descriptions

_OPS = {"gte": "≥", "gt": ">", "lte": "≤", "lt": "<"}
_UNIT_NAMES = {
    "en": {"sentences": "sentences", "paragraphs": "paragraphs"},
    "de": {"sentences": "Sätze", "paragraphs": "Absätze"},
}
_TEXT = {
    "en": {
        "min": "min {n}",
        "more": "more than {n}",
        "per_text": "per text",
        "per_paragraph": "per paragraph",
        "per_words": "per {n} words",
        "in_paragraph": "in one paragraph",
        "value": "value {op} {x}",
        "min_units": "at least {n} {unit}",
        "min_words": "at least {n} words",
        "requires": "only with {n} other findings",
    },
    "de": {
        "min": "mind. {n}",
        "more": "mehr als {n}",
        "per_text": "pro Text",
        "per_paragraph": "pro Absatz",
        "per_words": "pro {n} Wörter",
        "in_paragraph": "in einem Absatz",
        "value": "Wert {op} {x}",
        "min_units": "mind. {n} {unit}",
        "min_words": "mind. {n} Wörter",
        "requires": "nur mit {n} weiteren Befunden",
    },
}


def format_number(x: float, lang: str = "en") -> str:
    """Format a threshold or value: integers without decimals, else up to 4 decimals."""
    if x is None:
        return "-"
    if float(x).is_integer():
        text = str(int(x))
    else:
        text = f"{x:.4f}".rstrip("0").rstrip(".")
    return text.replace(".", ",") if lang == "de" else text


def describe_rule(rule: dict, requires: dict | None = None, unit: str = "sentences", lang: str = "en") -> str:
    """Human-readable rule, e.g. ``min 1 per text`` or ``value < 0.2, at least 3 sentences``."""
    t = _TEXT.get(lang, _TEXT["en"])
    paragraph = rule.get("scope") == "paragraph"
    if rule.get("value"):
        spec = rule["value"]
        text = t["value"].format(op=_OPS.get(spec["op"], spec["op"]), x=format_number(spec["x"], lang))
        if paragraph:
            text += " " + t["in_paragraph"]
    else:
        n = format_number(1 if rule.get("min_count") is None else rule["min_count"], lang)
        text = (t["more"] if rule.get("comparison") == "gt" else t["min"]).format(n=n)
        if rule.get("per_words"):
            text += " " + t["per_words"].format(n=format_number(rule["per_words"], lang))
            if paragraph:
                text += " " + t["in_paragraph"]
        else:
            text += " " + (t["per_paragraph"] if paragraph else t["per_text"])
    if rule.get("min_units"):
        unit_name = _UNIT_NAMES.get(lang, _UNIT_NAMES["en"]).get(unit, unit)
        text += ", " + t["min_units"].format(n=rule["min_units"], unit=unit_name)
    if rule.get("min_words"):
        text += ", " + t["min_words"].format(n=rule["min_words"])
    if requires and requires.get("min_other_findings"):
        text += "; " + t["requires"].format(n=requires["min_other_findings"])
    return text
