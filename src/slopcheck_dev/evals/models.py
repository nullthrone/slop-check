"""Self-updating model resolution (docs/architecture.md section 6.6).

``evals/models.yaml`` holds selectors per role. :func:`resolve` picks, per selector, the model
from ``https://openrouter.ai/api/v1/models`` (public, no key) with the newest ``created``
timestamp that passes every filter, and writes ``models/lock.json``. Renamed, added or retired
models are picked up on the next run without a code change; the lock records the exact
``canonical_slug`` and pricing every later job uses, and ``changes`` lists what moved since the
previous lock.

Consumers call :func:`load_lock`, which re-resolves live when the lock is missing or older
than ``max_age_days``, and :func:`refresh_entry` when a locked model turns out to be gone
mid-run (``ModelUnavailableError``).
"""

from __future__ import annotations

import datetime as _dt
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ._common import http_get_json, iso, load_yaml, parse_iso, read_json, repo_root, utc_now, write_json

MODELS_URL = "https://openrouter.ai/api/v1/models"
LOCK_VERSION = 1
DEFAULT_MAX_LOCK_AGE_DAYS = 8  # weekly resolver plus one day of slack
DEFAULT_EXCLUSIONS = (r":free$", r":batch$", r"-preview", r"-exp(-|$)")
# Dated snapshot aliases such as -20251001, -2025-10-01 or -06-05. Four-digit version suffixes
# (e.g. mistral-small-2603) are left to the selector regexes, since vendors use them as versions.
DATED_SNAPSHOT_RE = re.compile(r"-(?:20\d{6}|20\d{2}-\d{2}-\d{2}|\d{2}-\d{2})$")
ROLE_DEFAULT_INPUT = {"vision_judge": ["image"]}
ROLE_ORDER = ("generators", "judges", "conformance", "vision_judge")
ENTRY_FIELDS_FROM_SELECTOR = ("docs_per_language",)


class ResolveError(Exception):
    pass


# ---------------------------------------------------------------------------
# loading


def default_config_path() -> Path:
    return repo_root() / "evals" / "models.yaml"


def load_config(path: str | Path | None = None) -> dict:
    data = load_yaml(path or default_config_path()) or {}
    if not isinstance(data, dict):
        raise ResolveError("evals/models.yaml must be a mapping")
    return data


def fetch_models(source: str | None = None, *, timeout: float = 60.0) -> list[dict]:
    """Model list from the OpenRouter endpoint, or from a local JSON file (offline runs, tests)."""
    source = source or MODELS_URL
    if source.startswith("https://"):
        data = http_get_json(source, timeout=timeout)
    else:
        data = read_json(source)
    models = data.get("data") if isinstance(data, dict) else data
    if not isinstance(models, list):
        raise ResolveError("model list has no 'data' array")
    return [m for m in models if isinstance(m, dict) and m.get("id")]


def roles_of(config: dict) -> list[str]:
    """Role names in config order: every top-level list of selector mappings."""
    roles = [
        k
        for k, v in config.items()
        if isinstance(v, list) and v and all(isinstance(s, dict) and "match" in s for s in v)
    ]
    return sorted(roles, key=lambda r: (ROLE_ORDER.index(r) if r in ROLE_ORDER else len(ROLE_ORDER), r))


# ---------------------------------------------------------------------------
# filters


def _float(value: Any) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v


def _pricing(model: dict) -> dict:
    raw = model.get("pricing") or {}
    out: dict[str, float] = {}
    for k in ("prompt", "completion", "request", "input_cache_read"):
        v = _float(raw.get(k))
        if v is not None and (k in ("prompt", "completion") or v > 0):
            out[k] = v
    return out


def _modalities(model: dict, kind: str) -> list[str]:
    arch = model.get("architecture") or {}
    mods = arch.get(f"{kind}_modalities")
    if isinstance(mods, list):
        return [str(m) for m in mods]
    # fall back to "text+image->text"
    modality = str(arch.get("modality") or "")
    if "->" in modality:
        left, right = modality.split("->", 1)
        return (left if kind == "input" else right).split("+")
    return []


def _parse_date(value: Any) -> _dt.date | None:
    if not value:
        return None
    try:
        return _dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def selector_key(role: str, selector: dict, index: int, seen: dict[str, int]) -> str:
    base = f"{role}/{selector.get('family', 'unknown')}/{selector.get('tier', 'default')}"
    if selector.get("key"):
        base = f"{role}/{selector['key']}"
    n = seen.get(base, 0)
    seen[base] = n + 1
    return base if n == 0 else f"{base}#{n + 1}"


def reject_reason(
    model: dict,
    selector: dict,
    role: str,
    exclusions: list[str],
    grace_days: int,
    today: _dt.date,
) -> str | None:
    """None if the model passes every non-regex filter, else a short reason."""
    mid = str(model["id"])
    if not selector.get("allow_preview"):
        for pattern in exclusions:
            if re.search(pattern, mid):
                return f"excluded by {pattern!r}"
    if not selector.get("allow_snapshot") and DATED_SNAPSHOT_RE.search(mid):
        return "dated snapshot alias"
    need_out = selector.get("require_output_modalities") or ["text"]
    need_in = selector.get("require_input_modalities") or ROLE_DEFAULT_INPUT.get(role) or ["text"]
    outs, ins = _modalities(model, "output"), _modalities(model, "input")
    if any(m not in outs for m in need_out):
        return f"output modalities {outs} lack {need_out}"
    if any(m not in ins for m in need_in):
        return f"input modalities {ins} lack {need_in}"
    pricing = _pricing(model)
    cap = selector.get("max_completion_usd_per_mtok", selector.get("max_price"))
    if cap is not None:
        completion = pricing.get("completion")
        if completion is None or completion < 0:
            return "no usable completion price"
        if completion * 1_000_000 > float(cap) + 1e-9:
            return f"completion price {completion * 1e6:.3f}/Mtok above {cap}"
    prompt_cap = selector.get("max_prompt_usd_per_mtok")
    if prompt_cap is not None:
        prompt = pricing.get("prompt")
        if prompt is None or prompt < 0 or prompt * 1_000_000 > float(prompt_cap) + 1e-9:
            return "prompt price above cap"
    expiry = _parse_date(model.get("expiration_date"))
    if expiry is not None and expiry <= today + _dt.timedelta(days=grace_days):
        return f"expires {expiry.isoformat()} (grace {grace_days} days)"
    if not isinstance(model.get("created"), (int, float)):
        return "no created timestamp"
    return None


def _entry(model: dict, selector: dict, key: str, via: str) -> dict:
    entry: dict[str, Any] = {
        "key": key,
        "family": selector.get("family"),
        "tier": selector.get("tier"),
        "id": model["id"],
        "canonical_slug": model.get("canonical_slug") or model["id"],
        "created": int(model["created"]),
        "pricing": _pricing(model),
        "via": via,
        "selector": selector.get(via),
    }
    for f in ENTRY_FIELDS_FROM_SELECTOR:
        if f in selector:
            entry[f] = selector[f]
    if model.get("context_length"):
        entry["context_length"] = model["context_length"]
    top = model.get("top_provider") or {}
    if top.get("max_completion_tokens"):
        entry["max_completion_tokens"] = top["max_completion_tokens"]
    if isinstance(model.get("reasoning"), dict):
        entry["reasoning"] = model["reasoning"]
    if isinstance(model.get("supported_parameters"), list):
        entry["supported_parameters"] = sorted(model["supported_parameters"])
    if model.get("expiration_date"):
        entry["expiration_date"] = model["expiration_date"]
    return entry


def resolve_selector(
    selector: dict,
    role: str,
    models: list[dict],
    *,
    key: str,
    exclusions: list[str],
    grace_days: int,
    today: _dt.date,
    exclude_ids: set[str] | None = None,
) -> tuple[dict | None, list[str]]:
    """Best model for one selector: newest ``created`` among models passing every filter."""
    notes: list[str] = []
    for via in ("match", "fallback_match"):
        pattern = selector.get(via)
        if not pattern:
            continue
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            notes.append(f"{key}: invalid {via} regex {pattern!r}: {exc}")
            continue
        matched = [m for m in models if rx.search(str(m["id"]))]
        passing = []
        for m in matched:
            if exclude_ids and m["id"] in exclude_ids:
                continue
            reason = reject_reason(m, selector, role, exclusions, grace_days, today)
            if reason is None:
                passing.append(m)
        if passing:
            best = max(passing, key=lambda m: (int(m["created"]), str(m["id"])))
            if via == "fallback_match":
                notes.append(f"{key}: no model for match {selector.get('match')!r}; used fallback_match")
            return _entry(best, selector, key, via), notes
        if matched:
            notes.append(
                f"{key}: {len(matched)} model(s) match {via} {pattern!r} but none passes the filters"
            )
    return None, notes


def resolve(
    config: dict,
    models: list[dict],
    *,
    now: _dt.datetime | None = None,
    previous: dict | None = None,
    source: str = MODELS_URL,
) -> dict:
    """Resolve every selector of every role. Never raises for an unmatched selector."""
    now = now or utc_now()
    today = now.date()
    excl_cfg = config.get("exclusions") or {}
    exclusions = list(excl_cfg.get("id_regex") or DEFAULT_EXCLUSIONS)
    grace_days = int(excl_cfg.get("expiration_grace_days", 30))
    lock: dict[str, Any] = {
        "version": LOCK_VERSION,
        "resolved_at": iso(now),
        "source": source,
        "models_seen": len(models),
        "roles": {},
        "changes": [],
        "errors": [],
        "notes": [],
    }
    for role in roles_of(config):
        seen: dict[str, int] = {}
        entries = []
        for i, selector in enumerate(config[role]):
            key = selector_key(role, selector, i, seen)
            entry, notes = resolve_selector(
                selector, role, models, key=key, exclusions=exclusions, grace_days=grace_days, today=today
            )
            lock["notes"].extend(notes)
            if entry is None:
                lock["errors"].append(
                    f"{key}: no model matches {selector.get('match')!r}"
                    + (
                        f" or fallback {selector['fallback_match']!r}"
                        if selector.get("fallback_match")
                        else ""
                    )
                )
                continue
            entries.append(entry)
        lock["roles"][role] = entries
    lock["changes"] = diff_locks(previous, lock)
    return lock


# ---------------------------------------------------------------------------
# lock comparison and I/O


def _entries_by_key(lock: dict | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not lock:
        return out
    for role, entries in (lock.get("roles") or {}).items():
        for i, e in enumerate(entries or []):
            key = e.get("key") or f"{role}/{e.get('family', 'unknown')}/{e.get('tier', i)}"
            out[key] = e
    return out


def diff_locks(previous: dict | None, current: dict) -> list[str]:
    """Human-readable changes per selector key: new, removed, renamed, new snapshot, price."""
    if previous is None:
        return []
    old, new = _entries_by_key(previous), _entries_by_key(current)
    changes = []
    for key in sorted(set(old) | set(new)):
        a, b = old.get(key), new.get(key)
        if a and not b:
            changes.append(f"{key}: {a.get('id')} -> (unresolved)")
        elif b and not a:
            changes.append(f"{key}: (new) -> {b.get('id')} [{b.get('canonical_slug')}]")
        elif a and b:
            if a.get("id") != b.get("id"):
                changes.append(f"{key}: {a.get('id')} -> {b.get('id')} [{b.get('canonical_slug')}]")
            elif a.get("canonical_slug") != b.get("canonical_slug"):
                changes.append(
                    f"{key}: {b.get('id')} snapshot {a.get('canonical_slug')} -> {b.get('canonical_slug')}"
                )
            elif (a.get("pricing") or {}) != (b.get("pricing") or {}):
                changes.append(f"{key}: {b.get('id')} pricing {a.get('pricing')} -> {b.get('pricing')}")
    return changes


def write_lock(path: str | Path, lock: dict) -> None:
    write_json(path, lock)


def read_lock(path: str | Path) -> dict:
    data = read_json(path)
    if not isinstance(data, dict) or "roles" not in data:
        raise ResolveError(f"{path} is not a model lock file")
    return data


def lock_age_days(lock: dict, now: _dt.datetime | None = None) -> float | None:
    try:
        resolved = parse_iso(str(lock["resolved_at"]))
    except (KeyError, ValueError):
        return None
    now = now or utc_now()
    return (now - resolved).total_seconds() / 86400.0


def load_lock(
    path: str | Path | None,
    *,
    max_age_days: float | None = DEFAULT_MAX_LOCK_AGE_DAYS,
    config: dict | None = None,
    fetch: Callable[[], list[dict]] | None = None,
    now: _dt.datetime | None = None,
) -> tuple[dict, list[str]]:
    """Return (lock, notices). Re-resolve live when the lock is missing, unreadable or stale.

    When the live list cannot be fetched, a stale lock is still used (with a notice); without
    any lock a ResolveError is raised.
    """
    notices: list[str] = []
    old: dict | None = None
    if path and Path(path).is_file():
        try:
            old = read_lock(path)
        except (ResolveError, ValueError, OSError) as exc:
            notices.append(f"cannot read lock {path}: {exc}")
    if old is not None:
        age = lock_age_days(old, now)
        if max_age_days is None or (age is not None and age <= max_age_days):
            return old, notices
        notices.append(f"lock {path} is {age if age is None else round(age, 1)} days old; re-resolving live")
    else:
        notices.append("no model lock available; resolving live")
    try:
        models = fetch() if fetch else fetch_models()
        lock = resolve(config if config is not None else load_config(), models, now=now, previous=old)
    except Exception as exc:
        if old is not None:
            notices.append(f"live resolution failed ({exc}); using stale lock")
            return old, notices
        raise ResolveError(f"no usable model lock and live resolution failed: {exc}") from exc
    notices.extend(f"model change: {c}" for c in lock["changes"])
    notices.extend(f"model resolution error: {e}" for e in lock["errors"])
    return lock, notices


def role_entries(lock: dict, role: str, only: list[str] | None = None) -> list[dict]:
    """Entries of a role, optionally filtered by family, id, canonical_slug or key."""
    entries = list((lock.get("roles") or {}).get(role) or [])
    if not only:
        return entries
    wanted = {o.strip() for o in only if o.strip()}
    return [
        e
        for e in entries
        if wanted & {str(e.get("family")), str(e.get("id")), str(e.get("canonical_slug")), str(e.get("key"))}
    ]


def refresh_entry(
    lock: dict,
    key: str,
    *,
    exclude_ids: set[str],
    config: dict | None = None,
    fetch: Callable[[], list[dict]] | None = None,
    now: _dt.datetime | None = None,
) -> dict | None:
    """Re-resolve one selector live, skipping ``exclude_ids`` (models that just failed).

    Updates ``lock`` in place and returns the new entry, or None when nothing else qualifies.
    """
    config = config if config is not None else load_config()
    now = now or utc_now()
    excl_cfg = config.get("exclusions") or {}
    exclusions = list(excl_cfg.get("id_regex") or DEFAULT_EXCLUSIONS)
    grace_days = int(excl_cfg.get("expiration_grace_days", 30))
    models = fetch() if fetch else fetch_models()
    for role in roles_of(config):
        seen: dict[str, int] = {}
        for i, selector in enumerate(config[role]):
            if selector_key(role, selector, i, seen) != key:
                continue
            entry, _ = resolve_selector(
                selector,
                role,
                models,
                key=key,
                exclusions=exclusions,
                grace_days=grace_days,
                today=now.date(),
                exclude_ids=exclude_ids,
            )
            entries = (lock.setdefault("roles", {})).setdefault(role, [])
            for j, e in enumerate(entries):
                if e.get("key") == key:
                    if entry is None:
                        entries.pop(j)
                    else:
                        entries[j] = entry
                    break
            else:
                if entry is not None:
                    entries.append(entry)
            lock.setdefault("changes", []).append(
                f"{key}: refreshed mid-run after failure of {sorted(exclude_ids)} -> "
                f"{entry.get('id') if entry else '(unresolved)'}"
            )
            return entry
    return None


def format_lock_summary(lock: dict) -> str:
    lines = [f"resolved_at {lock.get('resolved_at')} ({lock.get('models_seen', '?')} models listed)"]
    for role, entries in (lock.get("roles") or {}).items():
        for e in entries:
            p = e.get("pricing") or {}
            p_in, p_out = p.get("prompt", 0) * 1e6, p.get("completion", 0) * 1e6
            lines.append(
                f"  {e.get('key')}: {e.get('id')} [{e.get('canonical_slug')}] "
                f"prompt {p_in:.3f}/Mtok, completion {p_out:.3f}/Mtok"
            )
        if not entries:
            lines.append(f"  {role}: (none resolved)")
    for c in lock.get("changes") or []:
        lines.append(f"change: {c}")
    for e in lock.get("errors") or []:
        lines.append(f"ERROR: {e}")
    return "\n".join(lines)
