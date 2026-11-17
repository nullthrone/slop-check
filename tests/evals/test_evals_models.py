from __future__ import annotations

import datetime as dt
import json

import pytest
from evals_helpers import FIXTURES

from slopcheck_dev.evals import models

NOW = dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.timezone.utc)
EXCL = {"id_regex": [":free$", ":batch$", "-preview", "-exp(-|$)"], "expiration_grace_days": 30}


def config(**roles):
    cfg = {"exclusions": EXCL}
    cfg.update(roles)
    return cfg


def pick(lock, role, i=0):
    return lock["roles"][role][i]["id"]


def test_picks_newest_created_among_matches(model_list):
    cfg = config(
        generators=[
            {
                "family": "acme",
                "match": r"^acme/chat-[0-9.]+$",
                "tier": "cheap",
                "max_completion_usd_per_mtok": 6,
                "docs_per_language": 10,
            }
        ]
    )
    lock = models.resolve(cfg, model_list, now=NOW)
    entry = lock["roles"]["generators"][0]
    # chat-2.0 is newer but too expensive, chat-1.4 expires within the grace period
    assert entry["id"] == "acme/chat-1.1"
    assert entry["canonical_slug"] == "acme/chat-1.1-20250601"
    assert entry["pricing"] == {"prompt": 2e-07, "completion": 1e-06}
    assert entry["docs_per_language"] == 10
    assert entry["key"] == "generators/acme/cheap"
    assert entry["via"] == "match"
    assert lock["errors"] == []


def test_global_exclusions_and_snapshot_alias(model_list):
    cfg = config(judges=[{"family": "acme", "match": r"^acme/chat-", "tier": "x"}])
    lock = models.resolve(cfg, model_list, now=NOW)
    # without a price cap the newest acceptable is chat-2.0; :free, :batch, -preview, -exp and the
    # dated alias acme/chat-1.1-20250601 are all newer or equal but excluded
    assert pick(lock, "judges") == "acme/chat-2.0"


def test_allow_preview_lifts_id_exclusions(model_list):
    cfg = config(judges=[{"family": "acme", "match": r"^acme/chat-", "allow_preview": True}])
    lock = models.resolve(cfg, model_list, now=NOW)
    assert pick(lock, "judges") == "acme/chat-1.0-exp"


def test_allow_snapshot(model_list):
    cfg = config(judges=[{"family": "acme", "match": r"^acme/chat-1\.1", "allow_snapshot": True}])
    lock = models.resolve(cfg, model_list, now=NOW)
    assert pick(lock, "judges") == "acme/chat-1.1-20250601"


def test_vision_role_requires_image_input(model_list):
    cfg = config(vision_judge=[{"family": "acme", "match": r"^acme/", "max_completion_usd_per_mtok": 6}])
    lock = models.resolve(cfg, model_list, now=NOW)
    # draw-1.0 is newest but has no text output; only chat-1.1 accepts images
    assert pick(lock, "vision_judge") == "acme/chat-1.1"


def test_explicit_input_modalities(model_list):
    cfg = config(
        conformance=[
            {
                "family": "acme",
                "match": r"^acme/",
                "require_input_modalities": ["image"],
                "max_completion_usd_per_mtok": 100,
            }
        ]
    )
    lock = models.resolve(cfg, model_list, now=NOW)
    assert pick(lock, "conformance") == "acme/chat-1.1"


def test_price_filter_and_negative_prices(model_list):
    cfg = config(judges=[{"family": "other", "match": r"^other/router$", "max_completion_usd_per_mtok": 6}])
    lock = models.resolve(cfg, model_list, now=NOW)
    assert lock["roles"]["judges"] == []
    assert len(lock["errors"]) == 1
    assert any("none passes the filters" in n for n in lock["notes"])


def test_expiration_grace(model_list):
    sel = {"family": "acme", "match": r"^acme/chat-1\.4$"}
    early = models.resolve(config(judges=[sel]), model_list, now=NOW)
    assert early["roles"]["judges"] == []
    late = models.resolve(
        config(judges=[sel]), model_list, now=dt.datetime(2025, 11, 1, tzinfo=dt.timezone.utc)
    )
    assert pick(late, "judges") == "acme/chat-1.4"


def test_fallback_match(model_list):
    cfg = config(
        generators=[
            {
                "family": "other",
                "match": r"^acme/none$",
                "fallback_match": r"^other/small-mini$",
                "max_completion_usd_per_mtok": 6,
            }
        ]
    )
    lock = models.resolve(cfg, model_list, now=NOW)
    entry = lock["roles"]["generators"][0]
    assert entry["id"] == "other/small-mini"
    assert entry["via"] == "fallback_match"
    assert any("fallback_match" in n for n in lock["notes"])


def test_unmatched_selector_is_reported_not_raised(model_list):
    cfg = config(
        generators=[
            {"family": "zzz", "match": r"^zzz/", "fallback_match": r"^yyy/"},
            {"family": "acme", "match": r"^acme/chat-1\.0$"},
        ]
    )
    lock = models.resolve(cfg, model_list, now=NOW)
    assert [e["id"] for e in lock["roles"]["generators"]] == ["acme/chat-1.0"]
    assert len(lock["errors"]) == 1 and "zzz" in lock["errors"][0]


def test_duplicate_keys_get_suffix(model_list):
    sel = {"family": "acme", "match": r"^acme/chat-1\.0$", "tier": "cheap"}
    lock = models.resolve(config(generators=[sel, dict(sel)]), model_list, now=NOW)
    assert [e["key"] for e in lock["roles"]["generators"]] == [
        "generators/acme/cheap",
        "generators/acme/cheap#2",
    ]


def test_diff_locks_reports_renames_snapshots_and_prices(model_list):
    cfg = config(
        generators=[
            {
                "family": "acme",
                "match": r"^acme/chat-[0-9.]+$",
                "tier": "cheap",
                "max_completion_usd_per_mtok": 6,
            }
        ]
    )
    current = models.resolve(cfg, model_list, now=NOW)
    prev = json.loads(json.dumps(current))
    prev["roles"]["generators"][0]["id"] = "acme/chat-0.9"
    prev["roles"]["generators"].append({"key": "generators/gone/cheap", "id": "gone/model"})
    changes = models.diff_locks(prev, current)
    assert "generators/acme/cheap: acme/chat-0.9 -> acme/chat-1.1 [acme/chat-1.1-20250601]" in changes
    assert "generators/gone/cheap: gone/model -> (unresolved)" in changes

    prev2 = json.loads(json.dumps(current))
    prev2["roles"]["generators"][0]["canonical_slug"] = "acme/chat-1.1-20250101"
    assert any(
        "snapshot acme/chat-1.1-20250101 -> acme/chat-1.1-20250601" in c
        for c in models.diff_locks(prev2, current)
    )

    prev3 = json.loads(json.dumps(current))
    prev3["roles"]["generators"][0]["pricing"] = {"prompt": 1e-07, "completion": 4e-07}
    assert any("pricing" in c for c in models.diff_locks(prev3, current))
    assert models.diff_locks(None, current) == []
    assert models.diff_locks(current, current) == []


def test_resolve_with_previous_fills_changes(model_list):
    cfg = config(
        generators=[
            {
                "family": "acme",
                "match": r"^acme/chat-[0-9.]+$",
                "tier": "cheap",
                "max_completion_usd_per_mtok": 6,
            }
        ]
    )
    first = models.resolve(cfg, [m for m in model_list if m["id"] != "acme/chat-1.1"], now=NOW)
    assert pick(first, "generators") == "acme/chat-1.0"
    second = models.resolve(cfg, model_list, now=NOW, previous=first)
    assert second["changes"] == [
        "generators/acme/cheap: acme/chat-1.0 -> acme/chat-1.1 [acme/chat-1.1-20250601]"
    ]


def test_repository_models_yaml_parses_and_resolves(model_list):
    cfg = models.load_config()
    assert set(models.roles_of(cfg)) >= {"generators", "judges", "conformance", "vision_judge"}
    lock = models.resolve(cfg, model_list, now=NOW)
    # the fixture has no matching vendors, so everything is unresolved but nothing raises
    assert lock["errors"]


def test_load_lock_fresh_does_not_fetch(tmp_path, model_list):
    cfg = config(judges=[{"family": "acme", "match": r"^acme/chat-1\.0$"}])
    lock = models.resolve(cfg, model_list, now=NOW)
    path = tmp_path / "lock.json"
    models.write_lock(path, lock)

    def boom():
        raise AssertionError("must not fetch")

    got, notices = models.load_lock(path, config=cfg, fetch=boom, now=NOW + dt.timedelta(days=2))
    assert got["roles"] == lock["roles"] and notices == []


def test_load_lock_stale_or_missing_resolves_live(tmp_path, model_list):
    cfg = config(judges=[{"family": "acme", "match": r"^acme/chat-1\.[01]$"}])
    old = models.resolve(cfg, [m for m in model_list if m["id"] != "acme/chat-1.1"], now=NOW)
    path = tmp_path / "lock.json"
    models.write_lock(path, old)
    later = NOW + dt.timedelta(days=20)
    got, notices = models.load_lock(path, config=cfg, fetch=lambda: model_list, now=later)
    assert pick(got, "judges") == "acme/chat-1.1"
    assert any("re-resolving" in n for n in notices)
    assert any("model change" in n for n in notices)

    got2, notices2 = models.load_lock(
        tmp_path / "missing.json", config=cfg, fetch=lambda: model_list, now=NOW
    )
    assert pick(got2, "judges") == "acme/chat-1.1"
    assert any("resolving live" in n for n in notices2)


def test_load_lock_fetch_failure(tmp_path, model_list):
    cfg = config(judges=[{"family": "acme", "match": r"^acme/chat-1\.0$"}])
    path = tmp_path / "lock.json"
    models.write_lock(path, models.resolve(cfg, model_list, now=NOW))

    def fail():
        raise OSError("offline")

    got, notices = models.load_lock(path, config=cfg, fetch=fail, now=NOW + dt.timedelta(days=30))
    assert pick(got, "judges") == "acme/chat-1.0"
    assert any("using stale lock" in n for n in notices)
    with pytest.raises(models.ResolveError):
        models.load_lock(tmp_path / "none.json", config=cfg, fetch=fail, now=NOW)


def test_refresh_entry_skips_failed_model(model_list):
    cfg = config(generators=[{"family": "acme", "match": r"^acme/chat-1\.[01]$", "tier": "cheap"}])
    lock = models.resolve(cfg, model_list, now=NOW)
    assert pick(lock, "generators") == "acme/chat-1.1"
    entry = models.refresh_entry(
        lock,
        "generators/acme/cheap",
        exclude_ids={"acme/chat-1.1"},
        config=cfg,
        fetch=lambda: model_list,
        now=NOW,
    )
    assert entry["id"] == "acme/chat-1.0"
    assert pick(lock, "generators") == "acme/chat-1.0"
    assert any("refreshed mid-run" in c for c in lock["changes"])
    none = models.refresh_entry(
        lock,
        "generators/acme/cheap",
        exclude_ids={"acme/chat-1.1", "acme/chat-1.0"},
        config=cfg,
        fetch=lambda: model_list,
        now=NOW,
    )
    assert none is None and lock["roles"]["generators"] == []


def test_role_entries_filter(model_list):
    cfg = config(
        generators=[
            {"family": "acme", "match": r"^acme/chat-1\.0$", "tier": "a"},
            {"family": "other", "match": r"^other/small-mini$", "tier": "b"},
        ]
    )
    lock = models.resolve(cfg, model_list, now=NOW)
    assert [e["id"] for e in models.role_entries(lock, "generators", ["other"])] == ["other/small-mini"]
    assert [e["id"] for e in models.role_entries(lock, "generators", ["acme/chat-1.0"])] == ["acme/chat-1.0"]
    assert len(models.role_entries(lock, "generators")) == 2


def test_fetch_models_over_mocked_http(fake_http):
    payload = json.loads((FIXTURES / "openrouter-models.json").read_text(encoding="utf-8"))
    fake_http.add("openrouter.ai/api/v1/models", payload)
    got = models.fetch_models()
    assert len(got) == len(payload["data"])
    req = fake_http.requests[0]
    assert req.full_url == models.MODELS_URL
    assert "Authorization" not in req.headers  # public endpoint, no key


def test_fetch_models_from_file():
    got = models.fetch_models(str(FIXTURES / "openrouter-models.json"))
    assert any(m["id"] == "acme/chat-1.1" for m in got)


def test_lock_summary_text(model_list):
    cfg = config(
        generators=[{"family": "acme", "match": r"^acme/chat-1\.0$", "tier": "cheap"}],
        judges=[{"family": "zzz", "match": r"^zzz/"}],
    )
    text = models.format_lock_summary(models.resolve(cfg, model_list, now=NOW))
    assert "acme/chat-1.0" in text and "ERROR" in text
