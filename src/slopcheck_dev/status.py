"""Effective status and weight derivation (docs/architecture.md section 6.4).

``derive(pattern, measurement, thresholds) -> (effective_status, weight, weight_source)``

| declared          | measurement            | effective   | weight                     |
|-------------------|------------------------|-------------|----------------------------|
| observation       | any                    | observation | 0                          |
| candidate         | none or not meets_core | candidate   | 0                          |
| candidate         | meets_core             | core        | measured                   |
| core (initial)    | none                   | core        | provisional (initial_core) |
| core (initial)    | meets_core             | core        | measured                   |
| core (initial)    | meets_fading           | fading      | 0                          |
| core (initial)    | neither                | core        | measured                   |
| any measured core | meets_fading           | fading      | 0                          |

A measurement applies only while its ``pattern_hash`` equals the hash of the pattern as it
is now; an edited pattern falls back to its declared status until it is remeasured.
A measurement without a usable lift (no human or AI documents) does not cover the pattern:
an initial-core pattern then keeps its provisional weight from
``governance/thresholds.yaml: initial_core`` (section 5.3).

``weight_source`` is ``measured``, ``provisional`` or ``none`` (weight 0).
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from .patterns import normalize_dates

WEIGHT_DIGITS = 3


def canonical_json(obj: Any) -> str:
    """Sorted keys, compact separators, UTF-8 without ASCII escaping."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def pattern_hash(pattern: dict) -> str:
    """sha256 of the canonical JSON of the whole pattern (section 6.3).

    ``pattern`` is the pattern as its YAML file defines it, not a catalog entry (which
    carries ``effective_status``, ``weight`` and ``weight_source`` on top). Date values are
    written as ISO strings, as the loader does, so a parsed file and its normalized dict
    hash the same.
    """
    return hashlib.sha256(canonical_json(normalize_dates(pattern)).encode("utf-8")).hexdigest()


def measurement_applies(pattern: dict, measurement: dict | None) -> bool:
    """True if ``measurement`` exists and its ``pattern_hash`` matches ``pattern``."""
    if not isinstance(measurement, dict):
        return False
    recorded = measurement.get("pattern_hash")
    return bool(recorded) and recorded == pattern_hash(pattern)


def measured_weight(lift: float | None, thresholds: dict) -> float | None:
    """``clamp(ln(lift), weights.from_lift.min, weights.from_lift.max)``; None without a lift."""
    if lift is None:
        return None
    try:
        lift = float(lift)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(lift) or lift <= 0:
        return None
    cfg = (thresholds.get("weights") or {}).get("from_lift") or {}
    lo = float(cfg.get("min", 0.5))
    hi = float(cfg.get("max", 3.0))
    return round(max(lo, min(hi, math.log(lift))), WEIGHT_DIGITS)


def initial_core(thresholds: dict) -> dict[str, float]:
    """``governance/thresholds.yaml: initial_core`` as ``{pattern_id: provisional weight}``.

    Entries whose weight is not a number are left out (``slopcheck-dev validate`` reports them).
    """
    table = thresholds.get("initial_core")
    if not isinstance(table, dict):
        return {}
    out = {}
    for pid, weight in table.items():
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            continue
        out[str(pid)] = float(weight)
    return out


def provisional_weight(pattern: dict, thresholds: dict) -> float | None:
    """Provisional weight of an initial-core pattern; None if its id is not listed."""
    return initial_core(thresholds).get(str(pattern.get("id")))


def _core(pattern: dict, measurement: dict | None, thresholds: dict) -> tuple[str, float, str]:
    """Effective core: measured weight if the measurement has a lift, else provisional."""
    if measurement is not None:
        weight = measured_weight(measurement.get("lift"), thresholds)
        if weight is not None:
            return "core", weight, "measured"
    provisional = provisional_weight(pattern, thresholds)
    if provisional is None:
        return "core", 0.0, "none"
    return "core", provisional, "provisional"


def derive(
    pattern: dict,
    measurement: dict | None,
    thresholds: dict,
    *,
    check_hash: bool = True,
) -> tuple[str, float, str]:
    """Return ``(effective_status, weight, weight_source)`` for one pattern.

    ``measurement`` is the pattern's entry from ``measurements.json`` (or None). With
    ``check_hash=False`` the entry is applied even if the pattern changed since it was
    measured; the gate uses that to ask what the status is on the base branch.
    """
    declared = pattern.get("status") or "observation"
    if declared == "observation":
        return "observation", 0.0, "none"
    m = measurement if isinstance(measurement, dict) else None
    if m is not None and check_hash and not measurement_applies(pattern, m):
        m = None
    meets_core = bool(m and m.get("meets_core"))
    meets_fading = bool(m and m.get("meets_fading"))
    if declared == "candidate":
        if not meets_core:
            return "candidate", 0.0, "none"
        if meets_fading:  # inconsistent entry: fading wins for anything measured core
            return "fading", 0.0, "none"
        return _core(pattern, m, thresholds)
    if declared == "core":
        if m is None:
            return _core(pattern, None, thresholds)
        if meets_fading:
            return "fading", 0.0, "none"
        return _core(pattern, m, thresholds)
    raise ValueError(f"pattern {pattern.get('id')}: unknown status {declared!r}")


def measurement_for(measurements: dict | None, pattern_id: str) -> dict | None:
    """The entry for ``pattern_id`` in a measurements.json structure."""
    if not isinstance(measurements, dict):
        return None
    entry = (measurements.get("patterns") or {}).get(pattern_id)
    return entry if isinstance(entry, dict) else None
