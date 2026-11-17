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


# --- provisional weights from governance/thresholds.yaml -------------------------------


def test_initial_core_weights_and_provisional_verdict_thresholds(pattern, catalog):
    """Two heavy (2.5) patterns reach RED, one heavy plus two light (1.0) stays YELLOW."""
    governance = yaml.safe_load(THRESHOLDS_YAML.read_text(encoding="utf-8"))
    vt = governance["verdict_provisional"]
    weights = sorted(set(governance["initial_core"].values()))
    assert weights == [0.5, 1.0, 2.5]
    heavy = [token_pattern(pattern, f"heavy{i}", 2.5) for i in range(2)]
    light = [token_pattern(pattern, f"light{i}", 1.0) for i in range(5)]
    cat = catalog(*heavy, *light, verdict_thresholds={"yellow": vt["yellow"], "red": vt["red"]})
    cases = {
        "": "GREEN",
        "light0": "GREEN",
        "light0 light1": "YELLOW",
        "heavy0": "YELLOW",
        "heavy0 light0 light1": "YELLOW",
        "heavy0 heavy1": "RED",
        "light0 light1 light2 light3 light4": "RED",
    }
    for text, verdict in cases.items():
        assert analyze(text, cat, lang="und")["verdict"] == verdict, text


# --- provisional ------------------------------------------------------------------------


def test_provisional_when_any_scored_weight_is_provisional(pattern, catalog):
    boot = token_pattern(pattern, "tokA", 2.5, weight_source="provisional")
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
