"""Markdown report layout (section 4.6) in English and German, JSON rendering."""

import json

import pytest

from slopcheck.engine import analyze
from slopcheck.report import format_score, render_json, render_markdown, render_pattern_list

TEXT = "Intro line.\n\nIt is tokA here. tokB and tokB again.\n\ntokC shows up."


@pytest.fixture
def result(pattern, catalog):
    def rx(pid, weight, status="core", **kw):
        token = pid.replace("-", "")
        return pattern(pid, weight=weight, status=status, realizations={"*": {"patterns": [token]}}, **kw)

    cat = catalog(
        rx("tokA", 2.5, name="Antithesis template", fix="State the claim\n directly."),
        rx("tokB", 1.0, name="Triad"),
        rx("tokC", 0.0, status="candidate", name="Rhetorical self-answer"),
        pattern("hollow-sentences", kind="llm", rubric="Hollow.", realizations={"*": {}}),
        catalog_version="2026.11.17",
    )
    return analyze(TEXT, cat, lang="en")


def test_english_layout(result):
    md = render_markdown(result, title="draft.md")
    lines = md.splitlines()
    assert lines[0] == "# Slop-Check: draft.md"
    assert lines[1] == ""
    assert lines[2] == "Verdict: YELLOW (score 3.5; yellow from 2.0, red from 5.0) | 13 words | language: en"
    assert lines[3] == "Heaviest findings: Antithesis template (2.5), Triad (1.0)."
    assert "## Findings (2)" in lines
    assert "1. Antithesis template (`tokA`, weight 2.5): 1 hit, threshold min 1 per text" in lines
    assert '   > "tokA" (paragraph 2)' in lines
    assert "   Suggestion: State the claim directly." in lines
    assert "2. Triad (`tokB`, weight 1.0): 2 hits, threshold min 1 per text" in lines
    assert "## Observations, not scored (1)" in lines
    assert "1. Rhetorical self-answer (`tokC`, candidate): 1 hit, threshold min 1 per text" in lines
    assert "## Not evaluated (1)" in lines
    assert "- `hollow-sentences` (requires a language model)" in lines
    assert "## Notes" in lines
    assert any("provisional" in line for line in lines)
    assert md.endswith("\n")


def test_section_order(result):
    md = render_markdown(result)
    order = ["## Findings", "## Observations", "## Not evaluated", "## Notes"]
    positions = [md.index(h) for h in order]
    assert positions == sorted(positions)
    assert md.startswith("# Slop-Check: text\n")


def test_german_labels(result):
    md = render_markdown(result, title="Entwurf", lang="de")
    lines = md.splitlines()
    assert lines[2] == "Gesamtbefund: GELB (Score 3,5; Gelb ab 2,0, Rot ab 5,0) | 13 Wörter | Sprache: en"
    assert lines[3] == "Schwerste Befunde: Antithesis template (2,5), Triad (1,0)."
    assert "## Befunde (2)" in lines
    assert "1. Antithesis template (`tokA`, Gewicht 2,5): 1 Treffer, Schwelle mind. 1 pro Text" in lines
    assert '   > "tokA" (Absatz 2)' in lines
    assert "   Vorschlag: State the claim directly." in lines
    assert "## Beobachtungen (nicht gewertet) (1)" in lines
    assert "1. Rhetorical self-answer (`tokC`, Kandidat): 1 Treffer, Schwelle mind. 1 pro Text" in lines
    assert "## Nicht ausgewertet (1)" in lines
    assert "- `hollow-sentences` (benötigt ein Sprachmodell)" in lines
    assert "## Hinweise" in lines


def test_green_report_without_findings(pattern, catalog):
    p = pattern("tokA", realizations={"*": {"patterns": ["tokA"]}}, weight_source="measured")
    res = analyze("Nothing to see here, and the rest is fine.", catalog(p), lang="en")
    md = render_markdown(res)
    assert "Verdict: GREEN (score 0.0;" in md
    assert "## Findings (0)\nNo scored pattern reached its threshold." in md
    assert "## Observations" not in md
    assert "## Not evaluated" not in md
    assert "provisional" not in md
    assert "They do not show who or what wrote the text." in md


def test_quotes_are_truncated_and_limited(pattern, catalog):
    p = pattern("long", realizations={"*": {"patterns": [r"x[^.]*"]}})
    text = ". ".join(["x " + "word " * 60] * 5) + "."
    md = render_markdown(analyze(text, catalog(p), lang="und"))
    quotes = [line for line in md.splitlines() if line.startswith("   > ")]
    assert len(quotes) == 3
    assert all(len(q) < 200 and "…" in q for q in quotes)
    assert "   (+2 more)" in md


def test_metric_value_and_unit_shown(pattern, catalog):
    p = pattern(
        "uniform",
        kind="metric",
        metric="comma_density",
        params={},
        threshold={"value": {"op": "lt", "x": 0.4}, "min_units": 3},
    )
    res = analyze("We met. We talked. We left.", catalog(p), lang="en")
    md = render_markdown(res, lang="de")
    assert "3 Treffer, Wert 0, Schwelle Wert < 0,4, mind. 3 Sätze" in md


def test_notes_for_short_text_und_and_llm_error(pattern, catalog):
    res = analyze("Game over.", catalog(pattern("tokA", realizations={"*": {"patterns": ["tokA"]}})))
    res["llm_error"] = "RuntimeError: boom"
    md = render_markdown(res)
    assert "Short text (2 words)" in md
    assert "Language not detected" in md
    assert "Language model error: RuntimeError: boom" in md


def test_render_json_round_trip(result):
    text = render_json(result)
    assert json.loads(text) == result
    assert "ö" in render_json({"x": "Wörter"})


def test_format_score():
    assert format_score(2) == "2.0"
    assert format_score(2.48) == "2.48"
    assert format_score(3.5, "de") == "3,5"


def test_render_pattern_list():
    table = render_pattern_list(
        [
            {
                "id": "a",
                "name": "A | B",
                "modality": "text",
                "effective_status": "core",
                "weight": 2.5,
                "detector": {"kind": "regex"},
            }
        ]
    )
    assert table.splitlines()[0] == "| Pattern | Name | Modality | Status | Detector | Weight |"
    assert "| `a` | A \\| B | text | core | regex | 2.5 |" in table
