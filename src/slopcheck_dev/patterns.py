"""Load pattern, source and governance files (docs/architecture.md sections 2, 3 and 5).

YAML loaders turn date values into ISO strings (``YYYY-MM-DD``) before anything else
sees them, so contributors can write unquoted dates and schema validation, hashing and
JSON output all work on plain strings.

Two layers:

- ``load_*_records`` return one :class:`Record` per file with its path and either the
  parsed data or a parse error. Validation uses them to report problems per file.
- ``load_patterns``, ``load_sources`` and ``load_thresholds`` return plain dicts and raise
  :class:`LoadError` on unreadable files. Build, fixture checks and the gate use them.
"""

from __future__ import annotations

import datetime as _dt
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MODALITIES = ("text", "image", "code", "audio", "video")
PATTERN_DIR = "patterns"
SOURCE_DIR = "sources"
THRESHOLDS_FILE = Path("governance") / "thresholds.yaml"
SCHEMA_DIR = "schema"


class LoadError(ValueError):
    """Raised when a YAML file cannot be read or parsed."""


@dataclass
class Record:
    """One YAML file: its path, the parsed data (None on error) and a parse error."""

    path: Path
    data: Any = None
    error: str | None = None

    def rel(self, root: Path) -> str:
        return relpath(self.path, root)


def relpath(path: Path, root: Path) -> str:
    """``path`` relative to ``root`` with forward slashes, or the absolute path."""
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def repo_root(start: str | Path | None = None) -> Path:
    """Repository root: env ``SLOPCHECK_ROOT``, else the first parent of ``start`` (or the
    working directory, then this file) that holds ``governance/thresholds.yaml``."""
    env = os.environ.get("SLOPCHECK_ROOT")
    if env:
        return Path(env).resolve()
    starts = [Path(start).resolve()] if start else [Path.cwd().resolve(), Path(__file__).resolve()]
    for base in starts:
        for parent in [base, *base.parents]:
            if (parent / THRESHOLDS_FILE).is_file():
                return parent
    return starts[0]


def normalize_dates(obj: Any) -> Any:
    """Convert ``date``/``datetime`` values to ISO strings, recursively."""
    if isinstance(obj, dict):
        return {k: normalize_dates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [normalize_dates(v) for v in obj]
    if isinstance(obj, (_dt.date, _dt.datetime)):
        return obj.isoformat()
    return obj


def load_yaml(path: str | Path) -> Any:
    """Parse one YAML file with ``yaml.safe_load`` and normalize dates."""
    import yaml  # dev dependency

    try:
        with open(path, encoding="utf-8") as fh:
            return normalize_dates(yaml.safe_load(fh))
    except (OSError, UnicodeDecodeError) as exc:
        raise LoadError(f"{path}: cannot read: {exc}") from exc
    except yaml.YAMLError as exc:
        raise LoadError(f"{path}: invalid YAML: {exc}") from exc


def _record(path: Path) -> Record:
    try:
        return Record(path=path, data=load_yaml(path))
    except LoadError as exc:
        return Record(path=path, error=str(exc).split(": ", 1)[-1])


def pattern_files(root: Path) -> list[Path]:
    """Every YAML file below ``patterns/`` (also misplaced ones, so validation can flag them)."""
    base = Path(root) / PATTERN_DIR
    if not base.is_dir():
        return []
    files = [p for p in base.rglob("*") if p.is_file() and p.suffix in (".yaml", ".yml")]
    return sorted(files, key=lambda p: p.as_posix())


def source_files(root: Path) -> list[Path]:
    base = Path(root) / SOURCE_DIR
    if not base.is_dir():
        return []
    files = [p for p in base.rglob("*") if p.is_file() and p.suffix in (".yaml", ".yml")]
    return sorted(files, key=lambda p: p.as_posix())


def load_pattern_records(root: str | Path | None = None) -> list[Record]:
    root = Path(root) if root else repo_root()
    return [_record(p) for p in pattern_files(root)]


def load_source_records(root: str | Path | None = None) -> list[Record]:
    root = Path(root) if root else repo_root()
    return [_record(p) for p in source_files(root)]


def load_patterns(root: str | Path | None = None, modality: str | None = None) -> list[dict]:
    """All patterns from ``patterns/<modality>/*.yaml``, sorted by (modality, id).

    Raises :class:`LoadError` if a file cannot be parsed or is not a mapping with an id.
    """
    root = Path(root) if root else repo_root()
    out = []
    for path in pattern_files(root):
        if path.parent.parent != root / PATTERN_DIR or path.suffix != ".yaml":
            continue
        if modality and path.parent.name != modality:
            continue
        data = load_yaml(path)
        if not isinstance(data, dict) or not data.get("id"):
            raise LoadError(f"{relpath(path, root)}: not a pattern mapping with an id")
        out.append(data)
    out.sort(key=lambda p: (str(p.get("modality", "")), str(p["id"])))
    return out


def load_sources(root: str | Path | None = None) -> dict[str, dict]:
    """All sources keyed by id."""
    root = Path(root) if root else repo_root()
    out: dict[str, dict] = {}
    for path in source_files(root):
        data = load_yaml(path)
        if not isinstance(data, dict) or not data.get("id"):
            raise LoadError(f"{relpath(path, root)}: not a source mapping with an id")
        out[str(data["id"])] = data
    return dict(sorted(out.items()))


def load_thresholds(root: str | Path | None = None) -> dict:
    """``governance/thresholds.yaml`` as a dict."""
    root = Path(root) if root else repo_root()
    path = root / THRESHOLDS_FILE
    if not path.is_file():
        raise LoadError(f"{relpath(path, root)}: file not found")
    data = load_yaml(path)
    if not isinstance(data, dict):
        raise LoadError(f"{relpath(path, root)}: expected a mapping")
    return data


def load_schema(root: str | Path | None, name: str) -> dict:
    """``schema/<name>.schema.json``."""
    import json

    root = Path(root) if root else repo_root()
    path = root / SCHEMA_DIR / f"{name}.schema.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LoadError(f"{relpath(path, root)}: cannot load schema: {exc}") from exc
