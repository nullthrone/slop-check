"""Fixtures for the dev tooling tests (helpers live in dev_helpers.py)."""

from __future__ import annotations

import pytest
from dev_helpers import MiniRepo, governance_thresholds, make_pattern, make_source


@pytest.fixture
def mini_repo(tmp_path) -> MiniRepo:
    """Empty repository skeleton (schemas, governance, empty patterns and sources)."""
    return MiniRepo(tmp_path / "repo")


@pytest.fixture
def repo(mini_repo: MiniRepo) -> MiniRepo:
    """A valid repository: three sources, one candidate, one initial-core pattern."""
    mini_repo.write_source(make_source("src-a"))
    mini_repo.write_source(make_source("src-b"))
    mini_repo.write_source(make_source("src-own", type="own-observation", publisher="slop-check"))
    mini_repo.write_pattern(make_pattern("cand-one"))
    mini_repo.write_pattern(make_pattern("core-one", status="core"))
    return mini_repo


@pytest.fixture
def thresholds() -> dict:
    """The real governance file with the test ``initial_core``."""
    return governance_thresholds()
