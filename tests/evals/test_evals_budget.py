from __future__ import annotations

import json
import threading

import pytest

from slopcheck_dev.evals import budget as B


def make(thresholds, tmp_path, kind="scheduled", call=None, run_id="run-1"):
    caps = B.load_caps(thresholds, kind, call)
    ledger = B.Ledger(tmp_path / "ledger.json")
    return B.Budget(ledger, caps, run_id)


def test_caps_from_thresholds(thresholds):
    caps = B.load_caps(thresholds, "pull_request")
    assert caps.monthly_usd == 26.0
    assert caps.run_usd == 0.5
    assert caps.call_usd == 0.25  # default per-call cap
    assert B.load_caps(thresholds, "conformance").run_usd == 6.0
    assert B.load_caps(thresholds, "scheduled", max_call_usd=50).call_usd == 12.0  # never above run cap
    with pytest.raises(ValueError):
        B.load_caps(thresholds, "weekly")
    with pytest.raises(ValueError):
        B.load_caps({"budget": {}}, "scheduled")


def test_repository_thresholds_have_budget():
    caps = B.load_caps(None, "scheduled")
    assert caps.monthly_usd > 0 and caps.run_usd > 0


def test_check_monthly_run_and_call_caps(thresholds, tmp_path):
    b = make(thresholds, tmp_path, "pull_request")
    b.check(0.2)
    with pytest.raises(B.BudgetExceeded) as exc:
        b.check(0.3)  # above per-call cap 0.25
    assert exc.value.cap == "call"
    b.settle(0.0, 0.2, role="judges", model="m")
    b.settle(0.0, 0.2, role="judges", model="m")
    with pytest.raises(B.BudgetExceeded) as exc:
        b.check(0.2)  # run total 0.4 + 0.2 > 0.5
    assert exc.value.cap == "run"
    assert b.allows(0.05)


def test_monthly_cap_counts_other_runs(thresholds, tmp_path):
    ledger = B.Ledger(tmp_path / "ledger.json")
    month = B.current_month()
    ledger.add(run_id="earlier", run_kind="scheduled", role="generators", model="m", usd=25.9, month=month)
    ledger.add(run_id="old", run_kind="scheduled", role="generators", model="m", usd=100.0, month="1999-01")
    b = B.Budget(ledger, B.load_caps(thresholds, "scheduled"), "now")
    assert ledger.month_total(month) == pytest.approx(25.9)
    b.check(0.05)
    with pytest.raises(B.BudgetExceeded) as exc:
        b.check(0.2)
    assert exc.value.cap == "monthly"
    assert "monthly cap" in str(exc.value)


def test_reserve_settle_release_and_persistence(thresholds, tmp_path):
    b = make(thresholds, tmp_path)
    r = b.reserve(0.1)
    with pytest.raises(B.BudgetExceeded):
        B.Budget(b.ledger, B.load_caps(thresholds, "scheduled"), "run-1").check(20)
    b.settle(r, 0.03, role="generators", model="acme/a", prompt_tokens=100, completion_tokens=900,
             canonical_slug="acme/a-1")
    r2 = b.reserve(0.1)
    b.release(r2)
    b.settle(b.reserve(0.1), 0.02, role="generators", model="acme/a", prompt_tokens=50, completion_tokens=50,
             estimated=True)
    data = json.loads((tmp_path / "ledger.json").read_text())
    assert len(data["entries"]) == 1  # aggregated per month, run, role, model
    e = data["entries"][0]
    assert e["calls"] == 2 and e["prompt_tokens"] == 150 and e["completion_tokens"] == 950
    assert e["usd"] == pytest.approx(0.05) and e["estimated_usd"] == pytest.approx(0.02)
    assert e["canonical_slug"] == "acme/a-1" and e["run_id"] == "run-1"
    assert b.status()["run_total_usd"] == pytest.approx(0.05)
    reloaded = B.Ledger(tmp_path / "ledger.json")
    assert reloaded.run_total("run-1") == pytest.approx(0.05)


def test_reservations_block_parallel_overshoot(thresholds, tmp_path):
    b = make(thresholds, tmp_path, "pull_request")  # run cap 0.5
    granted, refused = [], []
    lock = threading.Lock()

    def worker():
        try:
            r = b.reserve(0.2)
        except B.BudgetExceeded:
            with lock:
                refused.append(1)
            return
        with lock:
            granted.append(r)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(granted) == 2 and len(refused) == 8


def test_default_run_id(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "3")
    assert B.default_run_id() == "gh-42-3"
    monkeypatch.delenv("GITHUB_RUN_ID")
    assert B.default_run_id().startswith("local-")


def test_ledger_summary(thresholds, tmp_path):
    ledger = B.Ledger(tmp_path / "l.json")
    m = B.current_month()
    ledger.add(run_id="a", run_kind="scheduled", role="generators", model="x", usd=1.0, month=m)
    ledger.add(run_id="b", run_kind="scheduled", role="judges", model="y", usd=0.5, month=m)
    s = B.ledger_summary(ledger, m)
    assert s["month_total_usd"] == 1.5 and s["runs"] == 2
    assert s["by_role"] == {"generators": 1.0, "judges": 0.5}
