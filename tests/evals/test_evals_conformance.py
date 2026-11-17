from __future__ import annotations

import json

import pytest
from evals_helpers import standin_compile

from slopcheck_dev.evals import conformance as K
from slopcheck_dev.evals._common import load_patterns, load_thresholds
from slopcheck_dev.evals.budget import BudgetExceeded
from slopcheck_dev.evals.openrouter import ChatResult, ModelUnavailableError


def make_skill(tmp_path):
    skill = tmp_path / "slop-check"
    (skill / "references").mkdir(parents=True, exist_ok=True)
    (skill / "scripts").mkdir(exist_ok=True)
    (skill / "SKILL.md").write_text("---\nname: slop-check\ndescription: Checks text.\n---\n# Skill\n")
    (skill / "references" / "report-format.md").write_text("# Report format\nEnd with a JSON block.\n")
    (skill / "references" / "audit-procedure.md").write_text("# Audit\n")
    (skill / "scripts" / "slopcheck.py").write_text("print('never loaded')\n")
    return skill


def reply(findings, verdict="RED", observations=(), prose="Report text."):
    block = {
        "verdict": verdict,
        "score": 3.5,
        "findings": [{"pattern_id": p, "weight": 1.0} for p in findings],
        "observations": [{"pattern_id": p} for p in observations],
    }
    return f"{prose}\n\n```json\n{json.dumps(block)}\n```\n"


AUDIT = {
    "id": "a1",
    "language": "en",
    "mode": "audit",
    "text": "x",
    "must_find": ["p1", "p2"],
    "must_not_find": ["n1"],
    "expect_verdict": ["RED"],
}
CLEAN = {
    "id": "c1",
    "language": "de",
    "mode": "audit",
    "text": "x",
    "must_find": [],
    "must_not_find": ["n1"],
    "expect_verdict": ["GREEN"],
    "max_findings": 0,
}
REWRITE = {
    "id": "r1",
    "language": "en",
    "mode": "rewrite",
    "text": "In conclusion, it opens at 9 am on Monday.",
    "must_find": [],
    "must_not_find": [],
    "must_remove": ["In conclusion"],
    "must_keep": ["9 am", "Monday"],
    "expect_verdict": [],
}


def test_load_skill_ignores_scripts(tmp_path):
    skill = K.load_skill(make_skill(tmp_path))
    assert skill["name"] == "slop-check"
    assert [p for p, _ in skill["files"]] == [
        "SKILL.md",
        "references/audit-procedure.md",
        "references/report-format.md",
    ]
    prompt = K.skill_system_prompt(skill)
    assert '<file path="references/report-format.md">' in prompt and "never loaded" not in prompt
    with pytest.raises(FileNotFoundError):
        K.load_skill(tmp_path / "missing")


def test_extract_json_block_variants():
    assert K.extract_json_block(reply(["p1"]))["findings"][0]["pattern_id"] == "p1"
    raw = 'Some text {"verdict": "GREEN", "findings": []} trailing'
    assert K.extract_json_block(raw) == {"verdict": "GREEN", "findings": []}
    two = reply(["old"]) + reply(["new"])
    assert K.extract_json_block(two)["findings"][0]["pattern_id"] == "new"
    assert K.extract_json_block("no json here") is None
    assert K.extract_json_block('```json\n{"other": 1}\n```') is None
    f, o = K.result_ids(
        {"findings": [{"id": "a"}, "b", {"pattern": "c"}], "observations": [{"pattern_id": "d"}]}
    )
    assert f == ["a", "b", "c"] and o == ["d"]


def test_score_audit():
    ok = K.score_audit(AUDIT, reply(["p1"], observations=["p2"]))
    assert ok.passed and ok.parse_ok and ok.missing == [] and ok.verdict == "RED"
    miss = K.score_audit(AUDIT, reply(["p1", "n1"], verdict="YELLOW"))
    assert not miss.passed and miss.missing == ["p2"] and miss.unexpected == ["n1"]
    assert miss.checks["verdict"] is False
    broken = K.score_audit(AUDIT, "I could not do it.")
    assert not broken.parse_ok and broken.error and broken.missing == ["p1", "p2"]


def test_score_clean_case():
    assert K.score_audit(CLEAN, reply([], verdict="GREEN", observations=["x"])).passed
    bad = K.score_audit(CLEAN, reply(["p9"], verdict="GREEN"))
    assert not bad.passed and bad.extra_scored == ["p9"]


def test_score_rewrite():
    good = "Diff...\n\n```rewrite\nIt opens at 9 am on Monday.\n```"
    r = K.score_rewrite(REWRITE, good)
    assert r.passed and r.checks["extraction"] == "fence"
    kept_phrase = "```rewrite\nIn conclusion, it opens at 9 am on Monday.\n```"
    assert K.score_rewrite(REWRITE, kept_phrase).unexpected == ["In conclusion"]
    lost = K.score_rewrite(REWRITE, "```rewrite\nIt opens on Monday.\n```")
    assert lost.missing == ["9 am"] and not lost.passed
    via_json = K.score_rewrite(
        REWRITE,
        '```json\n{"verdict": "GREEN", "findings": [], "rewritten_text": "It opens at 9 am on Monday."}\n```',
    )
    assert via_json.passed and via_json.checks["extraction"] == "json"
    too_long = K.score_rewrite(REWRITE, "```rewrite\n" + "It opens at 9 am on Monday. " * 5 + "\n```")
    assert not too_long.checks["length_ok"]


def test_summarize():
    cases = [AUDIT, CLEAN, REWRITE]
    results = [
        K.score_audit(AUDIT, reply(["p1", "n1"])),
        K.score_audit(CLEAN, reply(["p9"], verdict="GREEN")),
        K.score_rewrite(REWRITE, "```rewrite\nIt opens at 9 am on Monday.\n```"),
    ]
    s = K.summarize(cases, results)
    assert s["true_positives"] == 1 and s["false_negatives"] == 1 and s["false_positives"] == 2
    assert s["recall"] == 0.5 and s["precision"] == pytest.approx(round(1 / 3, 4))
    assert s["clean_pass_rate"] == 0.0 and s["rewrite_pass_rate"] == 1.0 and s["passed"] == 1


class FakeClient:
    def __init__(self, replies, unavailable=(), budget_after=None):
        self.replies = replies
        self.unavailable = set(unavailable)
        self.budget_after = budget_after
        self.calls = []

    def chat(self, model, messages, max_tokens=1024, role="x", params=None):
        if model["id"] in self.unavailable:
            raise ModelUnavailableError("gone")
        if self.budget_after is not None and len(self.calls) >= self.budget_after:
            raise BudgetExceeded("cap", cap="run", limit=1, would_be=2)
        self.calls.append((model["id"], messages))
        user = messages[-1]["content"]
        text = next(v for k, v in self.replies.items() if k in user)
        return ChatResult(text=text, model=model["id"], canonical_slug=model.get("canonical_slug"), usd=0.01)


def test_run_conformance(tmp_path):
    cases = [
        dict(AUDIT, text="AUDITTEXT"),
        dict(REWRITE, text="In conclusion, REWRITETEXT at 9 am on Monday."),
    ]
    replies = {
        "AUDITTEXT": reply(["p1", "p2"]),
        "REWRITETEXT": "```rewrite\nREWRITETEXT at 9 am on Monday.\n```",
    }
    models = [
        {"key": "conformance/a/x", "family": "a", "id": "a/m", "canonical_slug": "a/m-1"},
        {"key": "conformance/b/x", "family": "b", "id": "b/m", "canonical_slug": "b/m-1"},
    ]
    fc = FakeClient(replies)
    out = K.run_conformance(make_skill(tmp_path), models, fc, cases=cases, workers=2)
    assert [m["id"] for m in out["models"]] == ["a/m", "b/m"]
    for m in out["models"]:
        assert m["summary"]["passed"] == 2 and m["summary"]["recall"] == 1.0
        assert [c["id"] for c in m["cases"]] == ["a1", "r1"]
    assert out["skill"]["name"] == "slop-check" and not out["aborted"]
    system = fc.calls[0][1][0]["content"]
    assert "references/report-format.md" in system
    assert "AUDITTEXT" in fc.calls[0][1][1]["content"] or "AUDITTEXT" in fc.calls[1][1][1]["content"]


def test_run_conformance_unavailable_and_budget(tmp_path):
    cases = [dict(AUDIT, text="AUDITTEXT")]
    models = [{"key": "k", "family": "a", "id": "a/old"}]
    repl = {"key": "k", "family": "a", "id": "a/new"}
    out = K.run_conformance(
        make_skill(tmp_path),
        models,
        FakeClient({"AUDITTEXT": reply(["p1", "p2"])}, unavailable={"a/old"}),
        cases=cases,
        workers=1,
        refresh=lambda e, f: repl,
    )
    assert out["models"][0]["id"] == "a/new" and any("now a/new" in n for n in out["notices"])
    out2 = K.run_conformance(
        make_skill(tmp_path),
        models + [dict(repl, key="k2")],
        FakeClient({"AUDITTEXT": reply([])}, budget_after=0),
        cases=cases,
        workers=1,
    )
    assert out2["aborted"] and "budget" in out2["notices"][-1]


def test_build_request_language():
    assert "audit mode" in K.build_request(AUDIT)
    assert "Audit-Modus" in K.build_request(dict(AUDIT, language="de"))
    assert "`rewrite`" in K.build_request(REWRITE)


# ---------------------------------------------------------------------------
# repository cases


def test_repository_cases_are_complete():
    cases = K.load_cases()
    ids = {p["id"] for p in load_patterns()}
    assert len(cases) >= 14
    assert {c["language"] for c in cases} == {"de", "en"}
    clean = [c for c in cases if c["mode"] == "audit" and c.get("max_findings") == 0]
    assert len(clean) >= 3 and all(c["expect_verdict"] == ["GREEN"] for c in clean)
    rewrites = [c for c in cases if c["mode"] == "rewrite"]
    assert len(rewrites) >= 2 and all(c["must_remove"] and c["must_keep"] for c in rewrites)
    for c in cases:
        for pid in c["must_find"] + c["must_not_find"]:
            assert pid in ids, f"{c['id']}: unknown pattern {pid}"
        if c["mode"] == "audit" and c not in clean:
            assert c["must_find"] and c["must_not_find"]


def test_repository_cases_agree_with_engine():
    """must_find ids trigger, must_not_find ids do not, clean texts are GREEN without findings."""
    engine = pytest.importorskip("slopcheck.engine")
    catalog = standin_compile(load_patterns(), load_thresholds())
    for c in K.load_cases():
        result = engine.analyze(c["text"], catalog, lang=c["language"])
        triggered = {pid for pid, v in result["all_patterns"].items() if v["triggered"]}
        if c["mode"] == "audit":
            assert set(c["must_find"]) <= triggered, (c["id"], set(c["must_find"]) - triggered)
            assert not set(c["must_not_find"]) & triggered, (c["id"], set(c["must_not_find"]) & triggered)
            if c.get("max_findings") is not None:
                assert len(result["findings"]) <= c["max_findings"], (c["id"], result["findings"])
                assert result["verdict"] in c["expect_verdict"]
        else:
            assert result["findings"], c["id"]
