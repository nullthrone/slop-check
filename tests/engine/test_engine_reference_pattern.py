"""The reference pattern patterns/text/antithesis-template.yaml runs through the engine."""

import time
from pathlib import Path

import pytest
import yaml

from slopcheck.catalog import make_catalog
from slopcheck.engine import analyze
from slopcheck.report import render_markdown

PATTERN_FILE = Path(__file__).resolve().parents[2] / "patterns" / "text" / "antithesis-template.yaml"


def load_reference() -> dict:
    pattern = yaml.safe_load(PATTERN_FILE.read_text(encoding="utf-8"))
    pattern.update({"effective_status": "core", "weight": 2.5, "weight_source": "bootstrap"})
    return pattern


@pytest.fixture(scope="module")
def reference():
    pattern = load_reference()
    return pattern, make_catalog([pattern])


def examples(kind):
    pattern = load_reference()
    return [(lang, text) for lang, real in pattern["realizations"].items() for text in real["examples"][kind]]


@pytest.mark.parametrize(("lang", "text"), examples("positive"))
def test_positive_examples_trigger(reference, lang, text):
    pattern, cat = reference
    for language in (lang, None):
        result = analyze(text, cat, lang=language)
        entry = result["all_patterns"][pattern["id"]]
        assert entry["triggered"] and entry["count"] >= 1, (language, text)
        assert result["verdict"] == "YELLOW"
        assert result["score"] == 2.5
        assert result["provisional"] is True


@pytest.mark.parametrize(("lang", "text"), examples("negative"))
def test_negative_examples_do_not_hit(reference, lang, text):
    pattern, cat = reference
    result = analyze(text, cat, lang=lang)
    assert result["all_patterns"][pattern["id"]] == {"triggered": False, "count": 0}
    assert result["verdict"] == "GREEN"


def test_report_for_reference_pattern(reference):
    _, cat = reference
    md = render_markdown(analyze("Das ist kein Werkzeug, das ist eine Haltung.", cat, lang="de"), lang="de")
    assert "1. Antithesis template (`antithesis-template`, Gewicht 2,5): 1 Treffer" in md
    assert '> "Das ist kein Werkzeug, das ist" (Absatz 1)' in md


def test_large_text_is_fast(reference):
    _, cat = reference
    paragraph = (
        "The team reviewed the quarterly numbers and found steady growth. It's not just a tool, it's a "
        "movement. Das ist kein Werkzeug, das ist eine Haltung.\n\n"
    )
    text = paragraph * (50_000 // len(paragraph))
    start = time.perf_counter()
    result = analyze(text, cat, lang="en")
    assert time.perf_counter() - start < 5.0
    assert result["all_patterns"]["antithesis-template"]["count"] > 100
