"""Status derivation (docs/architecture.md section 6.4) and pattern_hash."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math

import pytest
import yaml
from dev_helpers import make_pattern

from slopcheck_dev.status import (
    bootstrap_weight,
    derive,
    measured_weight,
    measurement_applies,
    measurement_for,
    pattern_hash,
)


def entry(pattern: dict, lift: float | None = 8.0, meets_core: bool = False, meets_fading: bool = False) -> dict:
    """A measurements.json entry that matches ``pattern``."""
    return {
        "pattern_hash": pattern_hash(pattern),
        "fpr_human": 0.01,
        "hit_ai": 0.2,
        "lift": lift,
        "meets_core": meets_core,
        "meets_fading": meets_fading,
    }


def core(tier: int = 1, pid: str = "gf-one") -> dict:
    return make_pattern(pid, status="core", legacy_tier=tier)


# ---------------------------------------------------------------------------
# the table, row by row


@pytest.mark.parametrize(
    "measurement",
    [None, {"meets_core": True, "lift": 9.0}, {"meets_fading": True, "lift": 1.0}],
)
def test_row_observation_any(thresholds, measurement):
    pattern = make_pattern("obs-one", status="observation")
    m = None if measurement is None else {**entry(pattern), **measurement}
    assert derive(pattern, m, thresholds) == ("observation", 0.0, "none")


def test_row_candidate_without_measurement(thresholds):
    assert derive(make_pattern("cand-one"), None, thresholds) == ("candidate", 0.0, "none")


def test_row_candidate_not_meeting_core(thresholds):
    pattern = make_pattern("cand-one")
    assert derive(pattern, entry(pattern, lift=30.0), thresholds) == ("candidate", 0.0, "none")


def test_row_candidate_meets_core_is_measured_core(thresholds):
    pattern = make_pattern("cand-one")
    status, weight, source = derive(pattern, entry(pattern, lift=8.0, meets_core=True), thresholds)
    assert (status, source) == ("core", "measured")
    assert weight == pytest.approx(math.log(8.0), abs=1e-3)


@pytest.mark.parametrize(("tier", "weight"), [(1, 2.5), (2, 1.0), (3, 0.5)])
def test_row_grandfathered_core_without_measurement_bootstrap(thresholds, tier, weight):
    assert derive(core(tier), None, thresholds) == ("core", weight, "bootstrap")


def test_row_grandfathered_core_meets_core_measured(thresholds):
    pattern = core(1)
    status, weight, source = derive(pattern, entry(pattern, lift=4.0, meets_core=True), thresholds)
    assert (status, source) == ("core", "measured")
    assert weight == pytest.approx(math.log(4.0), abs=1e-3)


def test_row_grandfathered_core_meets_fading(thresholds):
    pattern = core(1)
    assert derive(pattern, entry(pattern, lift=1.1, meets_fading=True), thresholds) == ("fading", 0.0, "none")


def test_row_grandfathered_core_neither_keeps_core_with_measured_weight(thresholds):
    pattern = core(2)
    status, weight, source = derive(pattern, entry(pattern, lift=3.0), thresholds)
    assert (status, source) == ("core", "measured")
    assert weight == pytest.approx(math.log(3.0), abs=1e-3)


@pytest.mark.parametrize("pattern", [make_pattern("cand-one"), core(1)], ids=["candidate", "core"])
def test_row_any_measured_core_meeting_fading_is_fading(thresholds, pattern):
    m = entry(pattern, lift=1.2, meets_core=True, meets_fading=True)
    assert derive(pattern, m, thresholds) == ("fading", 0.0, "none")


# ---------------------------------------------------------------------------
# hash matching and edge cases


def test_stale_measurement_falls_back_to_declared_status(thresholds):
    candidate = make_pattern("cand-one")
    m = entry(candidate, lift=8.0, meets_core=True)
    edited = make_pattern("cand-one", summary="An edited summary that is long enough.")
    assert not measurement_applies(edited, m)
    assert derive(edited, m, thresholds) == ("candidate", 0.0, "none")
    grandfathered = core(1)
    fading = entry(grandfathered, lift=1.0, meets_fading=True)
    edited_core = core(1)
    edited_core["fix"] = "A different fix."
    assert derive(edited_core, fading, thresholds) == ("core", 2.5, "bootstrap")


def test_check_hash_false_applies_stale_measurement(thresholds):
    m = entry(make_pattern("cand-one"), lift=8.0, meets_core=True)
    edited = make_pattern("cand-one", fix="Another fix.")
    assert derive(edited, m, thresholds, check_hash=False)[0] == "core"


def test_measurement_without_hash_never_applies(thresholds):
    pattern = core(1)
    m = entry(pattern, lift=1.0, meets_fading=True)
    m.pop("pattern_hash")
    assert derive(pattern, m, thresholds) == ("core", 2.5, "bootstrap")


def test_measurement_without_lift_keeps_bootstrap(thresholds):
    pattern = core(3)
    assert derive(pattern, entry(pattern, lift=None), thresholds) == ("core", 0.5, "bootstrap")


def test_unknown_status_raises(thresholds):
    with pytest.raises(ValueError, match="unknown status"):
        derive(make_pattern("x", status="retired"), None, thresholds)


@pytest.mark.parametrize(
    ("lift", "weight"),
    [
        (math.e**1.5, 1.5),
        (1.2, 0.5),  # ln 1.2 = 0.18, clamped to weights.from_lift.min
        (0.5, 0.5),  # negative log, clamped
        (1000.0, 3.0),  # ln 1000 = 6.9, clamped to weights.from_lift.max
        (math.e**3, 3.0),
    ],
)
def test_measured_weight_clamps_ln_lift(thresholds, lift, weight):
    assert measured_weight(lift, thresholds) == pytest.approx(weight, abs=1e-3)


@pytest.mark.parametrize("lift", [None, 0, -2, float("nan"), float("inf"), "n/a"])
def test_measured_weight_without_usable_lift(thresholds, lift):
    assert measured_weight(lift, thresholds) is None


def test_measured_weight_reads_thresholds(thresholds):
    thresholds["weights"]["from_lift"] = {"fn": "ln", "min": 1.0, "max": 2.0}
    assert measured_weight(1.5, thresholds) == 1.0
    assert measured_weight(100.0, thresholds) == 2.0


def test_bootstrap_weight_unknown_tier(thresholds):
    assert bootstrap_weight(make_pattern("cand-one"), thresholds) is None
    assert bootstrap_weight(core(9), thresholds) is None
    assert derive(core(9), None, thresholds) == ("core", 0.0, "none")


def test_measurement_for():
    data = {"patterns": {"a": {"lift": 2.0}, "b": "broken"}}
    assert measurement_for(data, "a") == {"lift": 2.0}
    assert measurement_for(data, "b") is None
    assert measurement_for(data, "c") is None
    assert measurement_for(None, "a") is None


# ---------------------------------------------------------------------------
# pattern_hash

REFERENCE = {
    "id": "x-pattern",
    "name": "Straße “quoted”",
    "status": "candidate",
    "threshold": {"min_count": 2, "comparison": "gte"},
    "realizations": {"de": {"terms": ["maßgeblich"]}},
    "history": [{"date": "2026-11-17", "change": "Added."}],
}
#: Pinned so that a change of the canonical form (key order, separators, escaping) is caught:
#: such a change would silently invalidate every stored measurement.
REFERENCE_HASH = "bfcaf7ab541140bb14eb607eceab3643d07c79fbe1296b15797df67c303a81e3"


def test_pattern_hash_pinned_value():
    assert pattern_hash(REFERENCE) == REFERENCE_HASH


def test_pattern_hash_is_sha256_of_canonical_json_without_history():
    body = {k: v for k, v in REFERENCE.items() if k != "history"}
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert pattern_hash(REFERENCE) == hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_pattern_hash_ignores_key_order_history_and_catalog_fields():
    reordered = dict(reversed(list(REFERENCE.items())))
    reordered["threshold"] = {"comparison": "gte", "min_count": 2}
    assert pattern_hash(reordered) == REFERENCE_HASH
    longer = {**REFERENCE, "history": [*REFERENCE["history"], {"date": "2026-12-01", "change": "Edited."}]}
    assert pattern_hash(longer) == REFERENCE_HASH
    assert pattern_hash({k: v for k, v in REFERENCE.items() if k != "history"}) == REFERENCE_HASH
    catalog_entry = {**REFERENCE, "effective_status": "core", "weight": 2.5, "weight_source": "bootstrap"}
    assert pattern_hash(catalog_entry) == REFERENCE_HASH


def test_pattern_hash_does_not_mutate_input():
    pattern = make_pattern("cand-one", history=[{"date": dt.date(2026, 11, 17), "change": "Added."}])
    before = json.dumps(pattern, default=str, sort_keys=True)
    pattern_hash(pattern)
    assert json.dumps(pattern, default=str, sort_keys=True) == before


@pytest.mark.parametrize(
    "change",
    [
        {"summary": "A different summary for the same pattern."},
        {"threshold": {"min_count": 2}},
        {"status": "observation"},
        {"notes": "A new note."},
    ],
)
def test_pattern_hash_changes_with_content(change):
    base = make_pattern("cand-one")
    assert pattern_hash({**base, **change}) != pattern_hash(base)


def test_pattern_hash_equal_for_yaml_dates_and_iso_strings(tmp_path):
    text = (
        "id: dated\nstatus: candidate\nnotes: checked\n"
        "sources:\n  - {source: src-a, note: 'seen 2026-07-30'}\n"
        "history:\n  - {date: 2026-07-30, change: Added.}\n"
        "extra_date: 2026-08-16\n"
    )
    path = tmp_path / "dated.yaml"
    path.write_text(text, encoding="utf-8")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(raw["extra_date"], dt.date)
    as_strings = {**raw, "extra_date": "2026-08-16", "history": [{"date": "2026-07-30", "change": "Added."}]}
    assert pattern_hash(raw) == pattern_hash(as_strings)
    from slopcheck_dev.patterns import load_yaml

    assert pattern_hash(load_yaml(path)) == pattern_hash(as_strings)
