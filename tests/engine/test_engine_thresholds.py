"""Threshold rules: min_count, per_words, comparison, scope, short_text, context_overrides,
min_units, value rules and requires."""

import pytest

from slopcheck.engine import analyze
from slopcheck.thresholds import count_met, describe_rule, effective_rule


def rx_pattern(pattern, pattern_id="rx", word="slop", **kwargs):
    return pattern(pattern_id, realizations={"*": {"patterns": [rf"(?i)\b{word}\b"]}}, **kwargs)


def triggered(text, p, catalog, **kwargs):
    return analyze(text, catalog(p), lang="und", **kwargs)["all_patterns"][p["id"]]["triggered"]


# --- effective rule -----------------------------------------------------------------


def test_effective_rule_defaults():
    assert effective_rule(None) == {
        "min_count": 1,
        "per_words": None,
        "comparison": "gte",
        "scope": "text",
        "value": None,
        "min_units": None,
    }


def test_effective_rule_applies_short_text_then_context():
    threshold = {
        "min_count": 3,
        "short_text": {"min_count": 2, "scope": "paragraph"},
        "context_overrides": {"informal": {"min_count": 5}},
    }
    assert effective_rule(threshold, short=False)["min_count"] == 3
    short = effective_rule(threshold, short=True)
    assert (short["min_count"], short["scope"]) == (2, "paragraph")
    both = effective_rule(threshold, short=True, context="informal")
    assert (both["min_count"], both["scope"]) == (5, "paragraph")
    assert effective_rule(threshold, context="technical")["min_count"] == 3


# --- count rules ----------------------------------------------------------------------


def test_min_count_gte_and_gt(pattern, catalog):
    gte = rx_pattern(pattern, threshold={"min_count": 2})
    gt = rx_pattern(pattern, threshold={"min_count": 2, "comparison": "gt"})
    assert not triggered("slop", gte, catalog)
    assert triggered("slop slop", gte, catalog)
    assert not triggered("slop slop", gt, catalog)
    assert triggered("slop slop slop", gt, catalog)


def test_min_count_zero_still_needs_a_hit(pattern, catalog):
    p = rx_pattern(pattern, threshold={"min_count": 0})
    assert not triggered("clean text", p, catalog)
    assert triggered("slop", p, catalog)


def test_per_words_density(pattern, catalog):
    p = rx_pattern(pattern, threshold={"min_count": 4, "per_words": 100})
    text_ok = "slop " * 3 + "word " * 97
    text_hit = "slop " * 4 + "word " * 96
    assert not triggered(text_ok, p, catalog)
    assert triggered(text_hit, p, catalog)
    assert triggered("slop slop word", p, catalog)


def test_paragraph_scope(pattern, catalog):
    p = rx_pattern(pattern, threshold={"min_count": 2, "scope": "paragraph"})
    assert not triggered("slop here.\n\nslop there.", p, catalog)
    assert triggered("slop and slop.\n\nclean.", p, catalog)


def test_paragraph_scope_with_per_words():
    rule = effective_rule({"min_count": 10, "per_words": 100, "scope": "paragraph"})
    hits = [{"paragraph": 1}, {"paragraph": 2}]
    assert count_met(rule, hits, 30, {1: 20, 2: 5}) is True
    assert count_met(rule, hits, 30, {1: 20, 2: 15}) is False


def test_short_text_override(pattern, catalog):
    p = rx_pattern(pattern, threshold={"min_count": 3, "short_text": {"min_count": 1}})
    short = "slop " + "word " * 20
    long = "slop " + "word " * 200
    assert triggered(short, p, catalog)
    assert not triggered(long, p, catalog)


def test_short_text_limit_comes_from_catalog(pattern, catalog):
    p = rx_pattern(pattern, threshold={"min_count": 3, "short_text": {"min_count": 1}})
    text = "slop " + "word " * 20
    result = analyze(text, catalog(p, short_text_max_words=10), lang="und")
    assert result["short_text"] is False
    assert not result["all_patterns"]["rx"]["triggered"]


def test_context_overrides(pattern, catalog):
    p = rx_pattern(pattern, threshold={"min_count": 1, "context_overrides": {"informal": {"min_count": 2}}})
    assert triggered("slop", p, catalog)
    assert not triggered("slop", p, catalog, context="informal")
    assert triggered("slop slop", p, catalog, context="informal")
    assert triggered("slop", p, catalog, context="technical")


def test_min_units_for_count_rules(pattern, catalog):
    p = rx_pattern(pattern, threshold={"min_count": 1, "min_units": 3})
    assert not triggered("One slop. Two.", p, catalog)
    assert triggered("One slop. Two. Three.", p, catalog)


@pytest.mark.parametrize(
    ("op", "x", "expected"),
    [
        ("gte", 2, True),
        ("gt", 2, False),
        ("lte", 2, True),
        ("lt", 2, False),
        ("lt", 3, True),
        ("gt", 1, True),
    ],
)
def test_value_rule_operators(pattern, catalog, op, x, expected):
    p = pattern("tri", kind="metric", metric="triad", params={}, threshold={"value": {"op": op, "x": x}})
    text = "It is fast, safe and cheap. Teams plan, build and ship."
    assert triggered(text, p, catalog) is expected


# --- requires -------------------------------------------------------------------------


def requires_catalog(pattern, catalog, other_statuses=("core", "core", "core")):
    patterns = [
        rx_pattern(pattern, f"other-{i}", word=f"tok{i}", status=status)
        for i, status in enumerate(other_statuses)
    ]
    patterns.append(rx_pattern(pattern, "dependent", word="vague", requires={"min_other_findings": 3}))
    return catalog(*patterns)


def test_requires_counts_only_with_enough_other_core_findings(pattern, catalog):
    cat = requires_catalog(pattern, catalog)
    few = analyze("vague tok0 tok1", cat, lang="und")["all_patterns"]["dependent"]
    assert few == {"triggered": False, "count": 1}
    enough = analyze("vague tok0 tok1 tok2", cat, lang="und")
    assert enough["all_patterns"]["dependent"]["triggered"]
    assert enough["score"] == 4.0


def test_requires_ignores_candidates(pattern, catalog):
    cat = requires_catalog(pattern, catalog, other_statuses=("core", "core", "candidate"))
    result = analyze("vague tok0 tok1 tok2", cat, lang="und")
    assert not result["all_patterns"]["dependent"]["triggered"]


def test_requires_chain_resolves_to_fixpoint(pattern, catalog):
    patterns = [
        rx_pattern(pattern, "a", word="tokA"),
        rx_pattern(pattern, "b", word="tokB", requires={"min_other_findings": 1}),
        rx_pattern(pattern, "c", word="tokC", requires={"min_other_findings": 2}),
    ]
    result = analyze("tokA tokB tokC", catalog(*patterns), lang="und")
    assert all(result["all_patterns"][k]["triggered"] for k in "abc")
    lonely = analyze("tokB tokC", catalog(*patterns), lang="und")
    assert not any(lonely["all_patterns"][k]["triggered"] for k in "bc")


# --- descriptions ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("threshold", "requires", "en", "de"),
    [
        ({"min_count": 1}, None, "min 1 per text", "mind. 1 pro Text"),
        ({"min_count": 2, "comparison": "gt"}, None, "more than 2 per text", "mehr als 2 pro Text"),
        ({"min_count": 2, "scope": "paragraph"}, None, "min 2 per paragraph", "mind. 2 pro Absatz"),
        ({"min_count": 4, "per_words": 100}, None, "min 4 per 100 words", "mind. 4 pro 100 Wörter"),
        (
            {"value": {"op": "lt", "x": 0.2}, "min_units": 3},
            None,
            "value < 0.2, at least 3 sentences",
            "Wert < 0,2, mind. 3 Sätze",
        ),
        ({"min_count": 1}, {"min_other_findings": 3}, "min 1 per text; only with 3 other findings", None),
    ],
)
def test_describe_rule(threshold, requires, en, de):
    rule = effective_rule(threshold)
    assert describe_rule(rule, requires, lang="en") == en
    if de:
        assert describe_rule(rule, requires, lang="de") == de
