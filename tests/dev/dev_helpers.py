"""Helpers for the dev tooling tests: a minimal repository in a temporary directory.

The tests never read the real patterns or sources (other contributors change them); they
use the real JSON schemas, the real governance file (with a test ``initial_core``) and the
real engine.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
#: Test ``initial_core``: pattern id -> provisional weight.
INITIAL_CORE = {"core-one": 2.5, "core-two": 1.0, "core-three": 0.5}


def make_pattern(pid: str, status: str = "candidate", modality: str = "text", **over) -> dict:
    """A schema-valid pattern; ``over`` replaces top-level fields."""
    pattern = {
        "id": pid,
        "modality": modality,
        "name": f"Pattern {pid}",
        "summary": "A summary that is long enough for the schema.",
        "category": "rhetoric" if modality == "text" else "visual-style",
        "status": status,
        "detector": {"kind": "regex", "position": "any"},
        "threshold": {"min_count": 1},
        "realizations": {
            "en": {
                "patterns": [r"(?i)\bfoo\b"],
                "examples": {
                    "positive": ["A foo here.", "Foo again."],
                    "negative": ["A bar.", "Food is fine."],
                },
            }
        },
        "legitimate_use": "Quoting the word itself.",
        "fix": "Remove the foo.",
        "prevention": "Do not write foo.",
        "sources": [{"source": "src-a"}, {"source": "src-b"}],
    }
    if status == "observation":
        pattern["sources"] = [{"source": "src-a"}]
    pattern.update(over)
    return pattern


def governance_thresholds() -> dict:
    """The real governance file with the test ``initial_core``."""
    data = yaml.safe_load((REPO / "governance" / "thresholds.yaml").read_text(encoding="utf-8"))
    data["initial_core"] = dict(INITIAL_CORE)
    return data


def make_source(sid: str, **over) -> dict:
    source = {
        "id": sid,
        "title": f"Source {sid}",
        "publisher": f"Publisher {sid}",
        "accessed": "2026-11-17",
        "type": "blog",
    }
    source.update(over)
    return {k: v for k, v in source.items() if v is not None}


class MiniRepo:
    def __init__(self, root: Path) -> None:
        self.root = root
        (root / "schema").mkdir(parents=True)
        for name in ("pattern", "source"):
            shutil.copyfile(REPO / "schema" / f"{name}.schema.json", root / "schema" / f"{name}.schema.json")
        thresholds = governance_thresholds()
        self.thresholds = thresholds
        (root / "governance").mkdir()
        self.write_thresholds()
        (root / "patterns" / "text").mkdir(parents=True)
        (root / "sources").mkdir()

    def write_thresholds(self) -> None:
        path = self.root / "governance" / "thresholds.yaml"
        path.write_text(yaml.safe_dump(self.thresholds, sort_keys=False), encoding="utf-8")

    def write_pattern(self, pattern: dict, rel: str | None = None) -> Path:
        path = self.root / (rel or f"patterns/{pattern.get('modality', 'text')}/{pattern['id']}.yaml")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(pattern, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return path

    def write_source(self, source: dict, rel: str | None = None) -> Path:
        path = self.root / (rel or f"sources/{source['id']}.yaml")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(source, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return path

    def remove(self, rel: str) -> None:
        (self.root / rel).unlink()

    def add_engine(self) -> None:
        shutil.copytree(
            REPO / "src" / "slopcheck",
            self.root / "src" / "slopcheck",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "catalog.json"),
        )

    def add_skill(self, frontmatter: str | None = None, references: dict[str, str] | None = None) -> None:
        skill = self.root / "skill"
        (skill / "references").mkdir(parents=True, exist_ok=True)
        default_fm = "---\nname: slop-check\ndescription: Use when a text needs a style check.\n---\n"
        fm = frontmatter if frontmatter is not None else default_fm
        body = "\n# Slop-Check\n\nFollow the audit procedure.\n"
        (skill / "SKILL.md").write_text(fm + body, encoding="utf-8")
        refs = (
            references
            if references is not None
            else {
                "audit-procedure.md": "# Audit procedure\n\nStep one.\n",
                "report-format.md": "# Report format\n\nUse the structure.\n",
                "rewrite-procedure.md": "# Rewrite procedure\n\nChange little.\n",
                "prevention-procedure.md": "# Prevention procedure\n\nApply the rules.\n",
            }
        )
        for name, text in refs.items():
            (skill / "references" / name).write_text(text, encoding="utf-8")
