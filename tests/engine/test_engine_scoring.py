"""Scoring, verdict, provisional flag and the result structure (sections 1 D9, 4.5)."""

from pathlib import Path

import pytest
import yaml

from slopcheck import __version__
from slopcheck.engine import analyze, verdict_for

THRESHOLDS_YAML = Path(__file__).resolve().parents[2] / "governance" / "thresholds.yaml"


def token_pattern(pattern, pattern_id, weight=1.0, status="core", **kwargs):
    token = pattern_id.replace("-", "")
    return pattern(
        pattern_id,
        status=status,
        weight=weight,
        realizations={"*": {"patterns": [rf"\b{token}\b"]}},
        **kwargs,
    )


# --- verdict boundaries -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("score", "verdict"),
    [(0.0, "GREEN"), (1.99, "GREEN"), (2.0, "YELLOW"), (4.99, "YELLOW"), (5.0, "RED"), (9.0, "RED")],
)
def test_verdict_boundaries(score, verdict):
    assert verdict_for(score, {"yellow": 2.0, "red": 5.0}) == verdict


def test_verdict_tolerates_float_noise():
    assert verdict_for(0.1 + 0.2 + 1.7, {"yellow": 2.0, "red": 5.0}) == "YELLOW"


def test_verdict_thresholds_come_from_catalog(pattern, catalog):
    p = token_pattern(pattern, "tokA", weight=1.0)
    cat = catalog(p, verdict_thresholds={"yellow": 0.5, "red": 1.0, "source": "measured"})
    result = analyze("tokA", cat, lang="und")
    assert result["verdict"] == "RED"
    assert result["verdict_thresholds"] == {"yellow": 0.5, "red": 1.0}


# --- legacy traffic light ----------------------------------------------------------------


def legacy_verdict(tier1: int, tier2: int) -> str:
    """Legacy rules quoted in governance/thresholds.yaml."""
    if tier1 >= 2 or tier2 >= 5 or (tier1 == 1 and tier2 >= 3):
        return "RED"
    if tier1 == 1 or 2 <= tier2 <= 4:
        return "YELLOW"
    return "GREEN"


def test_bootstrap_weights_reproduce_legacy_rules(pattern, catalog):
    governance = yaml.safe_load(THRESHOLDS_YAML.read_text(encoding="utf-8"))
    weights = governance["weights"]["bootstrap"]
    vt = governance["verdict_bootstrap"]
    tier1 = [token_pattern(pattern, f"tierone{i}", weights["legacy_tier_1"]) for i in range(3)]
    tier2 = [token_pattern(pattern, f"tiertwo{i}", weights["legacy_tier_2"]) for i in range(7)]
    cat = catalog(*tier1, *tier2, verdict_thresholds={"yellow": vt["yellow"], "red": vt["red"]})
    for n1 in range(3):
        for n2 in range(7):
            tokens = [f"tierone{i}" for i in range(n1)] + [f"tiertwo{i}" for i in range(n2)]
            result = analyze(" ".join(tokens), cat, lang="und")
            assert result["verdict"] == legacy_verdict(n1, n2), (n1, n2, result["score"])


def test_tier3_bootstrap_weight_is_half(pattern, catalog):
    governance = yaml.safe_load(THRESHOLDS_YAML.read_text(encoding="utf-8"))
    weight = governance["weights"]["bootstrap"]["legacy_tier_3"]
    p = token_pattern(pattern, "tierthree", weight)
    assert analyze("tierthree", catalog(p), lang="und")["score"] == 0.5


# --- score and findings ------------------------------------------------------------------


def test_score_sums_only_triggered_core_weights(pattern, catalog):
    cat = catalog(
        token_pattern(pattern, "tokA", 2.5),
        token_pattern(pattern, "tokB", 1.0),
        token_pattern(pattern, "tokC", 1.0, status="candidate"),
        token_pattern(pattern, "tokD", 1.0, status="fading"),
        token_pattern(pattern, "tokE", 1.0, status="observation"),
        token_pattern(pattern, "tokF", 1.0),
    )
    result = analyze("tokA tokB tokB tokC tokD tokE", cat, lang="und")
    assert result["score"] == 3.5
    assert result["verdict"] == "YELLOW"
    assert [f["pattern_id"] for f in result["findings"]] == ["tokA", "tokB"]
    assert [o["pattern_id"] for o in result["observations"]] == ["tokC", "tokD"]
    assert all(o["weight"] == 0.0 for o in result["observations"])
    assert result["all_patterns"]["tokE"] == {"triggered": True, "count": 1}
    assert result["all_patterns"]["tokF"] == {"triggered": False, "count": 0}


def test_findings_sorted_by_weight_then_count(pattern, catalog):
    cat = catalog(
        token_pattern(pattern, "tokA", 1.0),
        token_pattern(pattern, "tokB", 1.0),
        token_pattern(pattern, "tokC", 2.5),
    )
    result = analyze("tokA tokB tokB tokB tokC", cat, lang="und")
    assert [f["pattern_id"] for f in result["findings"]] == ["tokC", "tokB", "tokA"]


def test_finding_shape(pattern, catalog):
    p = token_pattern(pattern, "tokA", 2.5, fix="Say it   plainly.\nThen stop.")
    finding = analyze("Intro.\n\nThe tokA here.", catalog(p), lang="und")["findings"][0]
    assert finding["pattern_id"] == "tokA"
    assert finding["effective_status"] == "core"
    assert finding["weight"] == 2.5
    assert finding["count"] == 1
    assert finding["triggered"] is True
    assert finding["threshold"] == "min 1 per text"
    assert finding["fix"] == "Say it plainly. Then stop."
    assert finding["hits"] == [{"quote": "tokA", "paragraph": 2, "line": 3, "start": 12, "end": 16}]


# --- provisional ------------------------------------------------------------------------


def test_provisional_when_any_scored_weight_is_bootstrap(pattern, catalog):
    boot = token_pattern(pattern, "tokA", 2.5, weight_source="bootstrap")
    measured = token_pattern(pattern, "tokB", 1.2, weight_source="measured")
    assert analyze("clean", catalog(boot, measured), lang="und")["provisional"] is True
    assert analyze("tokB", catalog(measured), lang="und")["provisional"] is False


def test_candidates_do_not_make_result_provisional(pattern, catalog):
    cand = token_pattern(pattern, "tokA", status="candidate")
    assert analyze("tokA", catalog(cand), lang="und")["provisional"] is False


# --- result structure -----------------------------------------------------------------------


def test_result_top_level_fields(pattern, catalog):
    cat = catalog(token_pattern(pattern, "tokA"), catalog_version="2026.11.17")
    result = analyze("The cat and the dog sat on the mat.", cat, context="informal")
    assert result["engine_version"] == __version__
    assert result["catalog_version"] == "2026.11.17"
    assert result["words"] == 9
    assert result["language"] == "en"
    assert result["context"] == "informal"
    assert result["modality"] == "text"
    assert result["short_text"] is True
    assert result["verdict"] == "GREEN"
    assert result["score"] == 0
    for key in ("findings", "observations", "not_evaluated", "all_patterns"):
        assert key in result


def test_llm_patterns_without_judge_are_not_evaluated(pattern, catalog):
    llm = pattern("hollow", kind="llm", rubric="Find hollow sentences.", realizations={"en": {}})
    result = analyze("Some text here.", catalog(llm), lang="en")
    assert result["not_evaluated"] == ["hollow"]
    assert result["not_evaluated_reasons"] == {"hollow": "requires_llm"}
    assert "hollow" not in result["all_patterns"]


def test_modality_filter_and_vision_patterns(pattern, catalog):
    text_p = token_pattern(pattern, "tokA")
    image_p = pattern("plastic", kind="vision", rubric="Waxy skin.", modality="image", status="candidate")
    no_detector = token_pattern(pattern, "tokB")
    no_detector["detector"] = None
    cat = catalog(text_p, image_p, no_detector)
    text_result = analyze("tokA tokB", cat, lang="und")
    assert set(text_result["all_patterns"]) == {"tokA"}
    assert text_result["not_evaluated"] == []
    image_result = analyze("", cat, modality="image")
    assert image_result["not_evaluated_reasons"] == {"plastic": "requires_vision"}
    assert image_result["all_patterns"] == {}


def test_missing_effective_status_falls_back_to_status(pattern, catalog):
    p = token_pattern(pattern, "tokA", 1.0)
    del p["effective_status"]
    assert analyze("tokA", catalog(p), lang="und")["score"] == 1.0


def test_empty_text(pattern, catalog):
    result = analyze("", catalog(token_pattern(pattern, "tokA")))
    assert result["words"] == 0
    assert result["language"] == "und"
    assert result["verdict"] == "GREEN"
