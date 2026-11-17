"""kind: llm patterns through an injected judge, and the OpenRouter client helpers (no network)."""

import json

import pytest

from slopcheck import llm
from slopcheck.engine import analyze, locate_quotes
from slopcheck.textmodel import build_text_model

TEXT = (
    "Quality speaks for itself. Latency fell from 180 ms to 40 ms.\n\n"
    "Success is a mindset. We shipped on 3 March."
)


def llm_pattern(pattern, pattern_id="hollow", **kwargs):
    return pattern(
        pattern_id,
        kind="llm",
        rubric="Report sentences without checkable content.",
        realizations={
            "en": {"examples": {"positive": ["Quality speaks for itself."], "negative": ["It took 3 days."]}},
            "de": {"examples": {"positive": ["Qualität entsteht nicht zufällig."]}},
        },
        **kwargs,
    )


class StubJudge:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def __call__(self, text, patterns, lang):
        self.calls.append((text, [p["id"] for p in patterns], lang))
        return self.reply


# --- engine side ---------------------------------------------------------------------


def test_judge_hits_are_located_and_counted(pattern, catalog):
    judge = StubJudge({"hollow": [{"quote": "Quality speaks for itself."}, "Success is a mindset."]})
    result = analyze(TEXT, catalog(llm_pattern(pattern)), lang="en", llm_judge=judge)
    assert judge.calls == [(TEXT, ["hollow"], "en")]
    finding = result["findings"][0]
    assert finding["count"] == 2
    assert [h["paragraph"] for h in finding["hits"]] == [1, 2]
    assert finding["hits"][0]["quote"] == "Quality speaks for itself"
    assert result["not_evaluated"] == []


def test_quotes_not_in_text_are_dropped(pattern, catalog):
    judge = StubJudge({"hollow": ["Invented sentence.", "", None, {"quote": "Success is a mindset."}]})
    entry = analyze(TEXT, catalog(llm_pattern(pattern)), lang="en", llm_judge=judge)["all_patterns"]["hollow"]
    assert entry == {"triggered": True, "count": 1}


def test_missing_entry_means_zero_hits(pattern, catalog):
    result = analyze(TEXT, catalog(llm_pattern(pattern)), lang="en", llm_judge=StubJudge({}))
    assert result["all_patterns"]["hollow"] == {"triggered": False, "count": 0}


def test_value_rule_is_share_of_sentences(pattern, catalog):
    threshold = {"value": {"op": "gt", "x": 0.3334}, "min_units": 3}
    p = llm_pattern(pattern, params={"unit": "sentence"}, threshold=threshold)
    two = StubJudge({"hollow": ["Quality speaks for itself.", "Success is a mindset."]})
    entry = analyze(TEXT, catalog(p), lang="en", llm_judge=two)["all_patterns"]["hollow"]
    assert entry == {"triggered": True, "count": 2, "value": 0.5}
    one = StubJudge({"hollow": ["Success is a mindset."]})
    entry = analyze(TEXT, catalog(p), lang="en", llm_judge=one)["all_patterns"]["hollow"]
    assert entry == {"triggered": False, "count": 1, "value": 0.25}


def test_judge_not_called_below_min_units(pattern, catalog):
    p = llm_pattern(pattern, threshold={"value": {"op": "gt", "x": 0.3}, "min_units": 3})
    judge = StubJudge({"hollow": ["Quality speaks for itself."]})
    result = analyze("Quality speaks for itself. Fine.", catalog(p), lang="en", llm_judge=judge)
    assert judge.calls == []
    assert result["all_patterns"]["hollow"] == {"triggered": False, "count": 0}


def test_one_judge_call_for_all_llm_patterns(pattern, catalog):
    judge = StubJudge({"a": [], "b": []})
    analyze(TEXT, catalog(llm_pattern(pattern, "a"), llm_pattern(pattern, "b")), lang="en", llm_judge=judge)
    assert len(judge.calls) == 1
    assert judge.calls[0][1] == ["a", "b"]


def test_judge_failure_is_reported_not_raised(pattern, catalog):
    def broken(text, patterns, lang):
        raise RuntimeError("quota exceeded")

    rx = pattern("rx", realizations={"*": {"patterns": ["Quality"]}})
    result = analyze(TEXT, catalog(llm_pattern(pattern), rx), lang="en", llm_judge=broken)
    assert result["not_evaluated_reasons"] == {"hollow": "llm_error"}
    assert result["llm_error"] == "RuntimeError: quota exceeded"
    assert result["all_patterns"]["rx"]["triggered"]


def test_judge_receives_detected_language(pattern, catalog):
    judge = StubJudge({})
    analyze("Das ist gut und wir sind froh, dass es klappt.", catalog(llm_pattern(pattern)), llm_judge=judge)
    assert judge.calls[0][2] == "de"


def test_locate_quotes_maps_repeats_to_successive_occurrences():
    model = build_text_model("Again. Again. Again.", "en")
    hits = locate_quotes(model, ["Again.", "Again.", "“Again.”"])
    assert [h["start"] for h in hits] == [0, 7, 14]


def test_locate_quotes_ignores_code_blocks():
    model = build_text_model("Prose.\n\n```\nsecret code\n```", "en")
    assert locate_quotes(model, ["secret code"]) == []


# --- client helpers ------------------------------------------------------------------


def test_make_llm_judge_filters_non_verbatim_quotes(pattern):
    seen = {}

    def fake_chat(messages, model, api_key=None):
        seen["messages"], seen["model"] = messages, model
        reply = {
            "hollow": [
                {"quote": "Quality speaks for itself."},
                {"quote": "Quality speaks for itself"},
                "nope",
            ]
        }
        return {"content": "```json\n" + json.dumps(reply) + "\n```"}

    judge = llm.make_llm_judge("test/model", chat_fn=fake_chat)
    out = judge(TEXT, [llm_pattern(pattern)], "en")
    assert out == {
        "hollow": [{"quote": "Quality speaks for itself."}, {"quote": "Quality speaks for itself"}]
    }
    assert seen["model"] == "test/model"
    user = seen["messages"][1]["content"]
    assert "### hollow" in user and "Quality speaks for itself." in user and TEXT in user
    assert seen["messages"][0]["role"] == "system"


def test_make_llm_judge_end_to_end_with_engine(pattern, catalog):
    def fake_chat(messages, model, api_key=None):
        return 'Here you go: {"hollow": ["Success is a mindset."]} done'

    judge = llm.make_llm_judge("test/model", chat_fn=fake_chat)
    result = analyze(TEXT, catalog(llm_pattern(pattern)), lang="en", llm_judge=judge)
    assert result["findings"][0]["hits"][0]["quote"] == "Success is a mindset"


def test_invalid_json_raises_llm_error():
    with pytest.raises(llm.LLMError):
        llm.parse_json_object("no json here")
    with pytest.raises(llm.LLMError):
        llm.parse_json_object("[1, 2]")


def test_build_messages_uses_language_examples_and_position(pattern):
    p = llm_pattern(pattern, position="paragraph_end")
    user = llm.build_messages("Text.", [p], "de")[1]["content"]
    assert "Qualität entsteht nicht zufällig." in user
    assert "paragraph end" in user
    assert '"hollow"' in user


def test_resolve_model_precedence(tmp_path, monkeypatch):
    monkeypatch.delenv(llm.MODEL_ENV, raising=False)
    monkeypatch.delenv(llm.LOCK_ENV, raising=False)
    assert llm.resolve_model() is None
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps({"roles": {"judges": [{"family": "x", "id": "vendor/judge-9"}]}}))
    monkeypatch.setenv(llm.LOCK_ENV, str(lock))
    assert llm.resolve_model() == "vendor/judge-9"
    monkeypatch.setenv(llm.MODEL_ENV, "vendor/env-model")
    assert llm.resolve_model() == "vendor/env-model"
    assert llm.resolve_model("vendor/flag-model") == "vendor/flag-model"


def test_model_from_lock_handles_missing_file(tmp_path):
    assert llm.model_from_lock(str(tmp_path / "missing.json")) is None


def test_chat_requires_key_and_https(monkeypatch):
    monkeypatch.delenv(llm.KEY_ENV, raising=False)
    with pytest.raises(llm.LLMError, match=llm.KEY_ENV):
        llm.chat([], "test/model")
    with pytest.raises(llm.LLMError, match="https"):
        llm.chat([], "test/model", api_key="dummy", url="http://example.invalid")
