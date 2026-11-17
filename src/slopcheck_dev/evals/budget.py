"""Spend ledger and hard budget caps (docs/architecture.md section 6.5).

The ledger is a JSON file (``budget/ledger.json`` on branch ``data``). It aggregates spend per
(month, run id, role, model) so it stays small. Every privileged job checks the month total
and its run total against ``governance/thresholds.yaml: budget`` before it spends and raises
:class:`BudgetExceeded` when a cap would be crossed. Callers catch it and stop cleanly.

Thread safe: :class:`Budget` serializes reservations so parallel workers cannot overshoot.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._common import iso, load_thresholds, read_json, utc_now, write_json

LEDGER_VERSION = 1
DEFAULT_MAX_CALL_USD = 0.25
RUN_KIND_CAPS = {
    "pull_request": "per_pull_request_usd_cap",
    "scheduled": "per_scheduled_run_usd_cap",
    "conformance": "conformance_run_usd_cap",
}


class BudgetExceeded(Exception):
    """Raised before a spend that would cross a cap. Nothing has been spent for that call."""

    def __init__(self, message: str, *, cap: str, limit: float, would_be: float):
        super().__init__(message)
        self.cap = cap
        self.limit = limit
        self.would_be = would_be


@dataclass(frozen=True)
class Caps:
    monthly_usd: float
    run_usd: float
    call_usd: float
    run_kind: str


def load_caps(
    thresholds: dict | None = None,
    run_kind: str = "scheduled",
    max_call_usd: float | None = None,
) -> Caps:
    """Read caps from thresholds.yaml. The per-call cap never exceeds the run cap."""
    thresholds = thresholds if thresholds is not None else load_thresholds()
    budget = thresholds.get("budget") or {}
    if run_kind not in RUN_KIND_CAPS:
        raise ValueError(f"unknown run kind {run_kind!r}; expected one of {sorted(RUN_KIND_CAPS)}")
    try:
        monthly = float(budget["monthly_usd_cap"])
        run = float(budget[RUN_KIND_CAPS[run_kind]])
    except KeyError as exc:
        raise ValueError(f"governance/thresholds.yaml budget is missing {exc}") from None
    call = float(max_call_usd) if max_call_usd is not None else DEFAULT_MAX_CALL_USD
    return Caps(monthly_usd=monthly, run_usd=min(run, monthly), call_usd=min(call, run), run_kind=run_kind)


def current_month(now: Any = None) -> str:
    now = now or utc_now()
    return now.strftime("%Y-%m")


def default_run_id() -> str:
    gh = os.environ.get("GITHUB_RUN_ID")
    if gh:
        attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
        return f"gh-{gh}-{attempt}"
    return "local-" + utc_now().strftime("%Y%m%dT%H%M%SZ")


class Ledger:
    """Aggregated spend records persisted as JSON."""

    def __init__(self, path: str | Path | None = None, data: dict | None = None):
        self.path = Path(path) if path else None
        if data is None and self.path and self.path.is_file():
            data = read_json(self.path)
        data = data or {}
        self.entries: list[dict] = list(data.get("entries") or [])
        self.version = int(data.get("version") or LEDGER_VERSION)

    # -- queries -----------------------------------------------------------
    def month_total(self, month: str | None = None) -> float:
        month = month or current_month()
        return round(sum(float(e.get("usd") or 0.0) for e in self.entries if e.get("month") == month), 8)

    def run_total(self, run_id: str) -> float:
        return round(sum(float(e.get("usd") or 0.0) for e in self.entries if e.get("run_id") == run_id), 8)

    # -- updates -----------------------------------------------------------
    def add(
        self,
        *,
        run_id: str,
        run_kind: str,
        role: str,
        model: str,
        usd: float,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        canonical_slug: str | None = None,
        estimated: bool = False,
        month: str | None = None,
        now: Any = None,
    ) -> dict:
        now = now or utc_now()
        month = month or current_month(now)
        key = (month, run_id, role, model)
        entry = next(
            (
                e
                for e in self.entries
                if (e.get("month"), e.get("run_id"), e.get("role"), e.get("model")) == key
            ),
            None,
        )
        if entry is None:
            entry = {
                "month": month,
                "run_id": run_id,
                "run_kind": run_kind,
                "role": role,
                "model": model,
                "canonical_slug": canonical_slug,
                "calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "usd": 0.0,
                "estimated_usd": 0.0,
                "first_at": iso(now),
                "last_at": iso(now),
            }
            self.entries.append(entry)
        entry["calls"] += 1
        entry["prompt_tokens"] += int(prompt_tokens or 0)
        entry["completion_tokens"] += int(completion_tokens or 0)
        entry["usd"] = round(float(entry["usd"]) + float(usd), 8)
        if estimated:
            entry["estimated_usd"] = round(float(entry.get("estimated_usd") or 0.0) + float(usd), 8)
        if canonical_slug:
            entry["canonical_slug"] = canonical_slug
        entry["last_at"] = iso(now)
        return entry

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "currency": "USD",
            "updated_at": iso(utc_now()),
            "entries": self.entries,
        }

    def save(self) -> None:
        if self.path:
            write_json(self.path, self.to_dict())


class Budget:
    """Cap enforcement for one run. Use reserve/settle around each paid call."""

    def __init__(
        self,
        ledger: Ledger,
        caps: Caps,
        run_id: str | None = None,
        *,
        autosave: bool = True,
        now: Any = None,
    ):
        self.ledger = ledger
        self.caps = caps
        self.run_id = run_id or default_run_id()
        self.autosave = autosave
        self._now = now
        self._reserved = 0.0
        self._lock = threading.Lock()

    @property
    def month(self) -> str:
        return current_month(self._now)

    def _projected(self, amount: float) -> tuple[float, float]:
        month_total = self.ledger.month_total(self.month) + self._reserved + amount
        run_total = self.ledger.run_total(self.run_id) + self._reserved + amount
        return month_total, run_total

    def _check_locked(self, amount: float) -> None:
        if amount < 0:
            raise ValueError("amount must be >= 0")
        if amount > self.caps.call_usd:
            raise BudgetExceeded(
                f"single call estimate {amount:.4f} USD exceeds per-call cap {self.caps.call_usd:.4f} USD",
                cap="call",
                limit=self.caps.call_usd,
                would_be=amount,
            )
        month_total, run_total = self._projected(amount)
        if month_total > self.caps.monthly_usd:
            raise BudgetExceeded(
                f"monthly cap {self.caps.monthly_usd:.2f} USD would be exceeded ({month_total:.4f} USD)",
                cap="monthly",
                limit=self.caps.monthly_usd,
                would_be=month_total,
            )
        if run_total > self.caps.run_usd:
            raise BudgetExceeded(
                f"{self.caps.run_kind} run cap {self.caps.run_usd:.2f} USD would be exceeded "
                f"({run_total:.4f} USD)",
                cap="run",
                limit=self.caps.run_usd,
                would_be=run_total,
            )

    def check(self, amount: float) -> None:
        """Raise BudgetExceeded if spending ``amount`` now would cross any cap."""
        with self._lock:
            self._check_locked(float(amount))

    def allows(self, amount: float) -> bool:
        try:
            self.check(amount)
        except BudgetExceeded:
            return False
        return True

    def reserve(self, amount: float) -> float:
        """Check and hold ``amount`` until settle() or release()."""
        amount = float(amount)
        with self._lock:
            self._check_locked(amount)
            self._reserved += amount
        return amount

    def release(self, reserved: float) -> None:
        with self._lock:
            self._reserved = max(0.0, self._reserved - float(reserved))

    def settle(
        self,
        reserved: float,
        usd: float,
        *,
        role: str,
        model: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        canonical_slug: str | None = None,
        estimated: bool = False,
    ) -> None:
        """Replace a reservation by the actual cost and record it in the ledger."""
        with self._lock:
            self._reserved = max(0.0, self._reserved - float(reserved))
            self.ledger.add(
                run_id=self.run_id,
                run_kind=self.caps.run_kind,
                role=role,
                model=model,
                usd=float(usd),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                canonical_slug=canonical_slug,
                estimated=estimated,
            )
            if self.autosave:
                self.ledger.save()

    def status(self) -> dict:
        with self._lock:
            month_total = self.ledger.month_total(self.month)
            run_total = self.ledger.run_total(self.run_id)
        return {
            "month": self.month,
            "month_total_usd": round(month_total, 6),
            "monthly_cap_usd": self.caps.monthly_usd,
            "month_remaining_usd": round(max(0.0, self.caps.monthly_usd - month_total), 6),
            "run_id": self.run_id,
            "run_kind": self.caps.run_kind,
            "run_total_usd": round(run_total, 6),
            "run_cap_usd": self.caps.run_usd,
            "call_cap_usd": self.caps.call_usd,
        }


def ledger_summary(ledger: Ledger, month: str | None = None) -> dict:
    """Month total plus a breakdown by role and model, for `budget status`."""
    month = month or current_month()
    by_role: dict[str, float] = {}
    by_model: dict[str, float] = {}
    runs: set[str] = set()
    for e in ledger.entries:
        if e.get("month") != month:
            continue
        usd = float(e.get("usd") or 0.0)
        by_role[e.get("role", "?")] = round(by_role.get(e.get("role", "?"), 0.0) + usd, 6)
        by_model[e.get("model", "?")] = round(by_model.get(e.get("model", "?"), 0.0) + usd, 6)
        runs.add(str(e.get("run_id")))
    return {
        "month": month,
        "month_total_usd": ledger.month_total(month),
        "runs": len(runs),
        "by_role": dict(sorted(by_role.items())),
        "by_model": dict(sorted(by_model.items(), key=lambda kv: -kv[1])),
    }
