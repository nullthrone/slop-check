from __future__ import annotations

import json

import pytest

from slopcheck_dev.evals.budget import BudgetExceeded
from slopcheck_dev.evals.openrouter import ChatResult, ModelUnavailableError

pytest.importorskip("slopcheck.llm")
from slopcheck_dev.evals.judge import judge_params, make_judge

PATTERN = {
    "id": "hollow",
    "name": "Hollow",
    "detector": {"kind": "llm", "rubric": "Flag hollow sentences."},
    "realizations": {
        "en": {"examples": {"positive": ["Quality speaks."], "negative": ["It costs 4 euros."]}}
    },
}
TEXT = "Quality always speaks for itself. The update costs 4 euros."


class FakeClient:
    def __init__(self, replies, unavailable=(), budget=False):
        self.replies = replies
        self.unavailable = set(unavailable)
        self.budget = budget
        self.calls = []

    def chat(self, model, messages, max_tokens=1024, role="x", params=None):
        self.calls.append((model["id"], params, role))
        if self.budget:
            raise BudgetExceeded("cap", cap="run", limit=1, would_be=2)
        if model["id"] in self.unavailable:
            raise ModelUnavailableError("gone")
        return ChatResult(
            text=self.replies, model=model["id"], canonical_slug=model.get("canonical_slug"), usd=0.002
        )


def test_judge_returns_verbatim_hits_only():
    reply = json.dumps({"hollow": [{"quote": "Quality always speaks for itself."}, {"quote": "invented"}]})
    fc = FakeClient(reply)
    judge = make_judge(fc, {"id": "a/judge", "canonical_slug": "a/judge-1"})
    out = judge(TEXT, [PATTERN], "en")
    assert out == {"hollow": [{"quote": "Quality always speaks for itself."}]}
    assert fc.calls[0] == ("a/judge", {"temperature": 0}, "judges")
    assert judge.stats.calls == 1 and judge.stats.usd == pytest.approx(0.002)


def test_judge_switches_model_when_unavailable():
    fc = FakeClient(json.dumps({"hollow": []}), unavailable={"a/old"})
    judge = make_judge(
        fc, {"id": "a/old"}, refresh=lambda entry, failed: {"id": "a/new", "canonical_slug": "a/new-1"}
    )
    assert judge(TEXT, [PATTERN], "en") == {"hollow": []}
    assert judge.entry["id"] == "a/new" and [c[0] for c in fc.calls] == ["a/old", "a/new"]
    assert any("switched to a/new" in m for m in judge.stats.messages)


def test_judge_errors_are_counted_and_reraised():
    judge = make_judge(FakeClient("not json"), {"id": "a/j"})
    with pytest.raises(Exception):  # noqa: B017 - any parse error is acceptable
        judge(TEXT, [PATTERN], "en")
    assert judge.stats.errors == 1
    over = make_judge(FakeClient("{}", budget=True), {"id": "a/j"})
    with pytest.raises(BudgetExceeded):
        over(TEXT, [PATTERN], "en")
    assert over.stats.budget_exceeded


def test_judge_params_respect_supported_parameters():
    assert judge_params({"id": "x"}) == {"temperature": 0}
    assert judge_params({"id": "x", "supported_parameters": ["max_tokens"]}) == {}


def test_judge_works_inside_engine():
    engine = pytest.importorskip("slopcheck.engine")
    from evals_helpers import standin_compile

    from slopcheck_dev.evals._common import load_patterns

    pats = [p for p in load_patterns() if p["id"] == "hollow-sentences"]
    if not pats:
        pytest.skip("hollow-sentences not in repository")
    text = (
        "Quality always speaks for itself. Success is a journey. Every day is a chance. The fee is 4 euros."
    )
    sentences = ["Quality always speaks for itself.", "Success is a journey.", "Every day is a chance."]
    reply = json.dumps({"hollow-sentences": [{"quote": s} for s in sentences]})
    judge = make_judge(FakeClient(reply), {"id": "a/j"})
    res = engine.analyze(text, standin_compile(pats, None), lang="en", llm_judge=judge)
    assert res["all_patterns"]["hollow-sentences"]["triggered"] is True
