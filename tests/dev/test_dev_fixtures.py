"""slopcheck-dev check-fixtures: contributor examples and test texts against the engine."""

from __future__ import annotations

import pytest
from dev_helpers import make_pattern

from slopcheck_dev.cli import main
from slopcheck_dev.fixtures import check_fixtures, is_aggregate_metric, relaxed_threshold


def failures(report) -> list[tuple[str, str, str, int]]:
    return [(f.pattern_id, f.lang, f.what, f.index) for f in report.failures]


def regex(pid: str = "rx-one", patterns=(r"(?i)\bfoo\b",), positive=(), negative=(), test_texts=None, **over):
    body = {"patterns": list(patterns), "examples": {"positive": list(positive), "negative": list(negative)}}
    if test_texts is not None:
        body["test_texts"] = test_texts
    return make_pattern(pid, realizations={"en": body}, **over)


def test_valid_examples_pass(thresholds):
    report = check_fixtures([make_pattern("cand-one")], thresholds)
    assert report.ok, report.render()
    assert report.checked == ["cand-one"]
    assert report.examples_run == 4


def test_failing_positive_and_negative_are_reported(thresholds):
    pattern = regex(positive=["A foo here.", "Nothing here."], negative=["A bar.", "Foo slipped in."])
    report = check_fixtures([pattern], thresholds)
    assert failures(report) == [("rx-one", "en", "positive", 1), ("rx-one", "en", "negative", 1)]
    text = report.render()
    assert 'rx-one [en] positive #2: expected at least one hit, got 0 hit(s): "Nothing here."' in text
    assert 'rx-one [en] negative #2: expected no hit, got 1 hit(s): "Foo slipped in."' in text
    assert "1 pattern(s) checked, 4 example(s) run, 2 failure(s), 0 skipped" in text


def test_examples_use_relaxed_threshold_but_keep_position(thresholds):
    pattern = regex(
        positive=["Foo opens the text."],
        negative=["Then a foo appears."],
        detector={"kind": "regex", "position": "text_start"},
        threshold={"min_count": 3, "per_words": 100, "short_text": {"min_count": 2}},
        requires={"min_other_findings": 3},
    )
    assert check_fixtures([pattern], thresholds).ok
    assert relaxed_threshold(pattern) == {"min_count": 1}


def test_test_texts_use_full_threshold_and_context(thresholds):
    cases = [
        {"text": "A foo and a foo.", "expect": "no_trigger"},
        {"text": "A foo, a foo and a foo.", "expect": "trigger"},
        {"text": "Just one foo.", "expect": "trigger", "context": "informal"},
        {"text": "A foo and a foo.", "expect": "trigger"},  # wrong on purpose
    ]
    pattern = regex(
        positive=["A foo.", "Foo."],
        negative=["A bar.", "Food."],
        threshold={"min_count": 3, "context_overrides": {"informal": {"min_count": 1}}},
        requires={"min_other_findings": 2},  # dropped: depends on other patterns
        test_texts=cases,
    )
    report = check_fixtures([pattern], thresholds)
    assert failures(report) == [("rx-one", "en", "test_text", 3)]
    assert "expected trigger (context default), got no_trigger with 2 hit(s)" in report.failures[0].detail


def test_short_text_override_applies_to_test_texts(thresholds):
    long_text = " ".join(["filler"] * 160) + " foo."
    pattern = regex(
        positive=["foo"],
        negative=["bar"],
        threshold={"min_count": 2, "short_text": {"min_count": 1}},
        test_texts=[
            {"text": "A short foo.", "expect": "trigger"},
            {"text": long_text, "expect": "no_trigger"},
        ],
    )
    assert check_fixtures([pattern], thresholds).ok


def test_lexicon_examples(thresholds):
    pattern = make_pattern(
        "lex-one",
        detector={"kind": "lexicon", "position": "any"},
        threshold={"min_count": 2},
        realizations={
            "en": {
                "terms": ["delve", "tapestr*"],
                "examples": {
                    "positive": ["We delve in.", "A tapestry of ideas."],
                    "negative": ["Delving is a different word.", "A tape recorder."],
                },
            }
        },
    )
    assert check_fixtures([pattern], thresholds).ok


def test_aggregate_metric_keeps_value_rule(thresholds):
    long_text = " ".join(["word"] * 300) + " — end."
    pattern = make_pattern(
        "dash-one",
        category="typography",
        detector={
            "kind": "metric",
            "position": "any",
            "metric": "em_dash_density",
            "params": {"per_words": 500},
        },
        threshold={"value": {"op": "gt", "x": 3}, "short_text": {"value": {"op": "gt", "x": 100}}},
        realizations={
            "*": {
                "examples": {
                    "positive": ["Fast — cheap — good — done."],
                    "negative": ["Plain words without any dash.", long_text],
                }
            }
        },
    )
    assert is_aggregate_metric(pattern)
    assert relaxed_threshold(pattern) == {"min_count": 1, "value": {"op": "gt", "x": 3}}
    assert check_fixtures([pattern], thresholds).ok
    pattern["realizations"]["*"]["examples"]["negative"].append("One — dash in few words.")
    report = check_fixtures([pattern], thresholds)
    assert failures(report) == [("dash-one", "*", "negative", 2)]
    assert "triggered=True, value=" in report.failures[0].detail


def test_count_metric_is_relaxed_to_one_instance(thresholds):
    pattern = make_pattern(
        "emoji-one",
        category="formatting",
        detector={"kind": "metric", "position": "any", "metric": "emoji_decoration"},
        threshold={"value": {"op": "gte", "x": 2}},
        realizations={
            "*": {
                "examples": {
                    "positive": ["- ✅ Done\n- Next step", "## \U0001f680 Launch\n\nText."],
                    "negative": ["Done ✅", "- Done\n- Next"],
                }
            }
        },
    )
    assert not is_aggregate_metric(pattern)
    assert relaxed_threshold(pattern) == {"min_count": 1}
    assert check_fixtures([pattern], thresholds).ok


def test_llm_vision_and_detectorless_patterns_are_skipped(thresholds):
    patterns = [
        make_pattern("llm-one", detector={"kind": "llm", "rubric": "Judge it."}),
        make_pattern("img-one", modality="image", detector={"kind": "vision", "rubric": "Look."}),
        make_pattern("obs-one", status="observation", detector=None),
        make_pattern("cand-one"),
    ]
    report = check_fixtures(patterns, thresholds)
    assert report.checked == ["cand-one"]
    assert set(report.skipped) == {"llm-one", "img-one", "obs-one"}
    assert report.skipped["obs-one"] == "no detector"
    assert "Skipped (3):" in report.render()


def test_star_realization_runs_with_language_detection(thresholds):
    pattern = make_pattern(
        "star-one",
        realizations={
            "*": {
                "patterns": [r"\bXYZ\b"],
                "examples": {
                    "positive": ["Das Ergebnis XYZ ist da.", "The result XYZ is here."],
                    "negative": ["xyz in lower case.", "Nothing at all."],
                },
            }
        },
    )
    assert check_fixtures([pattern], thresholds).ok


def test_select_ids_and_unknown_ids(thresholds):
    patterns = [make_pattern("cand-one"), regex(positive=["nope"])]
    report = check_fixtures(patterns, thresholds, ["cand-one"])
    assert report.checked == ["cand-one"] and report.ok
    with pytest.raises(KeyError, match="ghost"):
        check_fixtures(patterns, thresholds, ["cand-one", "ghost"])


def test_cli_check_fixtures(repo, capsys):
    root = str(repo.root)
    assert main(["check-fixtures", "--root", root]) == 0
    assert "2 pattern(s) checked" in capsys.readouterr().out
    repo.write_pattern(regex("cand-bad", positive=["No hit here."], negative=["A bar."]))
    assert main(["check-fixtures", "--root", root]) == 1
    err = capsys.readouterr().err
    assert "cand-bad [en] positive #1" in err
    assert main(["check-fixtures", "--root", root, "cand-one"]) == 0
    capsys.readouterr()
    assert main(["check-fixtures", "--root", root, "ghost"]) == 2
    assert "unknown pattern id(s): ghost" in capsys.readouterr().err
    (repo.root / "patterns" / "text" / "broken.yaml").write_text("id: [unclosed\n", encoding="utf-8")
    assert main(["check-fixtures", "--root", root]) == 2
