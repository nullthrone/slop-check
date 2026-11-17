"""Fixtures for the evaluation tests. No test may touch the network or need an API key."""

from __future__ import annotations

import json
import urllib.request

import pytest
from evals_helpers import FIXTURES, FakeUrlopen, standin_compile, standin_derive


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(req, timeout=None):
        url = req.full_url if isinstance(req, urllib.request.Request) else str(req)
        raise AssertionError(f"network access attempted in tests: {url}")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)


@pytest.fixture
def fake_http(monkeypatch):
    fake = FakeUrlopen()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return fake


@pytest.fixture
def model_list():
    return json.loads((FIXTURES / "openrouter-models.json").read_text(encoding="utf-8"))["data"]


@pytest.fixture
def thresholds():
    return {
        "short_text_max_words": 150,
        "admission": {
            "core": {
                "max_fpr_human": 0.05,
                "min_lift": 2.0,
                "min_model_families": 2,
                "min_family_lift": 1.5,
                "min_ai_hits": 10,
                "min_human_docs_per_language": 100,
            },
            "fading": {"max_lift": 1.5, "min_fpr_human": 0.08},
        },
        "weights": {"from_lift": {"fn": "ln", "min": 0.5, "max": 3.0}},
        "verdict_provisional": {"yellow": 2.0, "red": 5.0},
        "initial_core": {"delta": 2.5, "antithesis-template": 2.5, "generic-opening": 2.5},
        "budget": {
            "monthly_usd_cap": 26.0,
            "per_pull_request_usd_cap": 0.5,
            "per_scheduled_run_usd_cap": 12.0,
            "conformance_run_usd_cap": 6.0,
        },
    }


@pytest.fixture
def compile_fn():
    return standin_compile


@pytest.fixture
def derive_fn():
    return standin_derive
