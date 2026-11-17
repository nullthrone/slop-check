"""Factories for small inline catalogs used by the engine tests."""

from __future__ import annotations

import pytest

from slopcheck.catalog import make_catalog


def build_pattern(
    pattern_id: str = "p",
    kind: str = "regex",
    status: str = "core",
    weight: float = 1.0,
    weight_source: str = "provisional",
    realizations: dict | None = None,
    threshold: dict | None = None,
    position: str = "any",
    metric: str | None = None,
    params: dict | None = None,
    rubric: str | None = None,
    requires: dict | None = None,
    modality: str = "text",
    **extra,
) -> dict:
    """A catalog pattern dict with ``effective_status`` equal to ``status``."""
    detector: dict = {"kind": kind, "position": position}
    if metric:
        detector["metric"] = metric
    if params is not None:
        detector["params"] = params
    if rubric:
        detector["rubric"] = rubric
    pattern = {
        "id": pattern_id,
        "modality": modality,
        "name": extra.pop("name", pattern_id.replace("-", " ").capitalize()),
        "status": status,
        "effective_status": status,
        "weight": weight if status == "core" else 0.0,
        "weight_source": weight_source if status == "core" else "none",
        "detector": detector,
        "threshold": threshold if threshold is not None else {"min_count": 1},
        "requires": requires,
        "realizations": realizations if realizations is not None else {"*": {}},
        "fix": extra.pop("fix", "Rewrite the passage."),
    }
    pattern.update(extra)
    return pattern


@pytest.fixture
def pattern():
    """Factory fixture: ``pattern(id, kind=..., ...)`` returns a pattern dict."""
    return build_pattern


@pytest.fixture
def catalog():
    """Factory fixture: ``catalog(*patterns, **kwargs)`` returns a catalog dict."""

    def factory(*patterns: dict, **kwargs) -> dict:
        return make_catalog(list(patterns), **kwargs)

    return factory
