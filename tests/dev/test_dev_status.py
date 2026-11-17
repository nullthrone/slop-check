"""Status derivation (docs/architecture.md section 6.4) and pattern_hash."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math

import pytest
from dev_helpers import INITIAL_CORE, make_pattern

from slopcheck_dev.status import (
    derive,
    initial_core,
    measured_weight,
    measurement_applies,
    measurement_for,
    pattern_hash,
    provisional_weight,
)


def entry(
    pattern: dict, lift: float | None = 8.0, meets_core: bool = False, meets_fading: bool = False
) -> dict:
    """A measurements.json entry that matches ``pattern``."""
    return {
        "pattern_hash": pattern_hash(pattern),
        "fpr_human": 0.01,
        "hit_ai": 0.2,
        "lift": lift,
        "meets_core": meets_core,
        "meets_fading": meets_fading,
    }


def core(pid: str = "core-one", **over) -> dict:
    return make_pattern(pid, status="core", **over)


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


@pytest.mark.parametrize(("pid", "weight"), sorted(INITIAL_CORE.items()))
def test_row_initial_core_without_measurement_is_provisional(thresholds, pid, weight):
    assert derive(core(pid), None, thresholds) == ("core", weight, "provisional")


def test_row_initial_core_meets_core_measured(thresholds):
    pattern = core()
    status, weight, source = derive(pattern, entry(pattern, lift=4.0, meets_core=True), thresholds)
    assert (status, source) == ("core", "measured")
    assert weight == pytest.approx(math.log(4.0), abs=1e-3)


def test_row_initial_core_meets_fading(thresholds):
    pattern = core()
    assert derive(pattern, entry(pattern, lift=1.1, meets_fading=True), thresholds) == ("fading", 0.0, "none")


def test_row_initial_core_neither_keeps_core_with_measured_weight(thresholds):
    pattern = core("core-two")
    status, weight, source = derive(pattern, entry(pattern, lift=3.0), thresholds)
    assert (status, source) == ("core", "measured")
    assert weight == pytest.approx(math.log(3.0), abs=1e-3)


@pytest.mark.parametrize("pattern", [make_pattern("cand-one"), core()], ids=["candidate", "core"])
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
    fading = entry(core(), lift=1.0, meets_fading=True)
    edited_core = core(fix="A different fix.")
    assert derive(edited_core, fading, thresholds) == ("core", 2.5, "provisional")


def test_check_hash_false_applies_stale_measurement(thresholds):
    m = entry(make_pattern("cand-one"), lift=8.0, meets_core=True)
    edited = make_pattern("cand-one", fix="Another fix.")
    assert derive(edited, m, thresholds, check_hash=False)[0] == "core"


def test_measurement_without_hash_never_applies(thresholds):
    pattern = core()
    m = entry(pattern, lift=1.0, meets_fading=True)
    m.pop("pattern_hash")
    assert derive(pattern, m, thresholds) == ("core", 2.5, "provisional")


def test_measurement_without_lift_keeps_provisional_weight(thresholds):
    pattern = core("core-three")
    assert derive(pattern, entry(pattern, lift=None), thresholds) == ("core", 0.5, "provisional")


def test_core_outside_initial_core_has_no_weight(thresholds):
    # validate rejects such a file (rule 1); derive must still not invent a weight
    assert derive(core("not-listed"), None, thresholds) == ("core", 0.0, "none")


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


def test_initial_core_and_provisional_weight(thresholds):
    assert initial_core(thresholds) == INITIAL_CORE
    assert provisional_weight(core("core-two"), thresholds) == 1.0
    assert provisional_weight(make_pattern("cand-one"), thresholds) is None
    thresholds["initial_core"] = {"a": 2, "b": "heavy", "c": True}
    assert initial_core(thresholds) == {"a": 2.0}
    thresholds["initial_core"] = ["a"]
    assert initial_core(thresholds) == {}
    thresholds["initial_core"] = {"core-one": 1.75}
    assert derive(core(), None, thresholds) == ("core", 1.75, "provisional")


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
    "notes": "Checked 2026-11-17.",
}
#: Pinned so that a change of the canonical form (key order, separators, escaping) is caught:
#: such a change would silently invalidate every stored measurement.
REFERENCE_HASH = "1723ac7c278ef5a1b3640e090423ee1ded56e3f3a9314bd9322b564816477106"


def test_pattern_hash_pinned_value():
    assert pattern_hash(REFERENCE) == REFERENCE_HASH


def test_pattern_hash_is_sha256_of_canonical_json_of_whole_pattern():
    canonical = json.dumps(REFERENCE, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert pattern_hash(REFERENCE) == hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_pattern_hash_ignores_key_order():
    reordered = dict(reversed(list(REFERENCE.items())))
    reordered["threshold"] = {"comparison": "gte", "min_count": 2}
    assert pattern_hash(reordered) == REFERENCE_HASH


@pytest.mark.parametrize(
    "change",
    [
        {"summary": "A different summary for the same pattern."},
        {"threshold": {"min_count": 2}},
        {"status": "observation"},
        {"notes": "A new note."},
        {"related": [{"id": "other", "relation": "overlaps"}]},
        {"sources": [{"source": "src-a"}, {"source": "src-b", "note": "A new note on the source."}]},
    ],
)
def test_pattern_hash_covers_every_field(change):
    base = make_pattern("cand-one")
    assert pattern_hash({**base, **change}) != pattern_hash(base)


def test_pattern_hash_does_not_mutate_input():
    pattern = make_pattern("cand-one", notes="Seen on a date.")
    pattern["sources"][0]["accessed"] = dt.date(2026, 11, 17)
    before = json.dumps(pattern, default=str, sort_keys=True)
    pattern_hash(pattern)
    assert json.dumps(pattern, default=str, sort_keys=True) == before


def test_pattern_hash_equal_for_yaml_dates_and_iso_strings(tmp_path):
    import yaml

    from slopcheck_dev.patterns import load_yaml

    text = "id: dated\nstatus: candidate\nsources:\n  - {source: src-a, seen: 2026-07-30}\n"
    path = tmp_path / "dated.yaml"
    path.write_text(text, encoding="utf-8")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(raw["sources"][0]["seen"], dt.date)
    as_strings = {
        "id": "dated",
        "status": "candidate",
        "sources": [{"source": "src-a", "seen": "2026-07-30"}],
    }
    assert pattern_hash(raw) == pattern_hash(as_strings)
    assert pattern_hash(load_yaml(path)) == pattern_hash(as_strings)
