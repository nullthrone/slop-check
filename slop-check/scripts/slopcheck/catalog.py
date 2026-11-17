"""Catalog loading (architecture section 4.4). The runtime reads ``catalog.json`` only.

``load_catalog(None)`` looks in this order:

1. the path in environment variable ``SLOPCHECK_CATALOG``;
2. ``catalog.json`` inside the package directory (installed package);
3. ``catalog.json`` next to the package directory (skill layout:
   ``scripts/catalog.json`` beside ``scripts/slopcheck/``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ENV_VAR = "SLOPCHECK_CATALOG"
FILE_NAME = "catalog.json"
STATUSES = ("observation", "candidate", "core", "fading")


class CatalogError(ValueError):
    """Raised when a catalog file is missing or malformed."""


def default_locations() -> list[Path]:
    """Candidate catalog paths when no explicit path is given."""
    env = os.environ.get(ENV_VAR)
    if env:
        return [Path(env)]
    package_dir = Path(__file__).resolve().parent
    return [package_dir / FILE_NAME, package_dir.parent / FILE_NAME]


def load_catalog(path: str | None = None) -> dict:
    """Load and check a catalog. Raises :class:`CatalogError` if none is found or it is malformed."""
    candidates = [Path(path)] if path else default_locations()
    for candidate in candidates:
        if candidate.is_file():
            return _read(candidate)
    tried = ", ".join(str(c) for c in candidates)
    raise CatalogError(f"catalog not found (tried: {tried}); build one with `slopcheck-dev build`")


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"cannot read catalog {path}: {exc}") from exc
    check_catalog(data, str(path))
    return data


def check_catalog(data: object, origin: str = "catalog") -> None:
    """Minimal structural check: a dict with a list of patterns that have ids."""
    if not isinstance(data, dict) or not isinstance(data.get("patterns"), list):
        raise CatalogError(f"{origin}: expected an object with a 'patterns' list")
    for i, pattern in enumerate(data["patterns"]):
        if not isinstance(pattern, dict) or not pattern.get("id"):
            raise CatalogError(f"{origin}: pattern #{i} has no id")


def make_catalog(
    patterns: list[dict],
    short_text_max_words: int = 150,
    verdict_thresholds: dict | None = None,
    catalog_version: str = "dev",
) -> dict:
    """Wrap pattern dicts into a catalog structure (tests and fixture checks)."""
    return {
        "catalog_version": catalog_version,
        "generated_at": None,
        "short_text_max_words": short_text_max_words,
        "verdict_thresholds": verdict_thresholds or {"yellow": 2.0, "red": 5.0, "source": "provisional"},
        "patterns": patterns,
    }


def select_patterns(catalog: dict, modality: str | None = None, status: str | None = None) -> list[dict]:
    """Patterns filtered by modality and effective status (declared status as fallback)."""
    selected = []
    for pattern in catalog.get("patterns", []):
        if modality and pattern.get("modality", "text") != modality:
            continue
        effective = pattern.get("effective_status") or pattern.get("status")
        if status and effective != status:
            continue
        selected.append(pattern)
    return selected
