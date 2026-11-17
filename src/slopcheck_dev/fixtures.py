"""``slopcheck-dev check-fixtures``: contributor examples against the engine (section 3).

Each example runs through ``slopcheck.engine.analyze`` with a one-pattern catalog:

- ``examples.positive`` must produce at least one hit and ``examples.negative`` none. This
  is a detector-level check. For regex and lexicon detectors the threshold is relaxed to
  ``min_count: 1`` (no density, short-text or context overrides, no ``requires``), keeping
  the detector ``position``. Metric detectors keep their value rule, scope and
  ``min_units`` (a value metric has no hits without its rule); count metrics are relaxed
  to ``min_count: 1`` like the others.
- ``test_texts`` run with the full threshold (including short-text and context
  overrides). ``requires`` is dropped because it depends on other patterns.

``kind: llm`` and ``kind: vision`` patterns, and patterns without a detector, are skipped
and listed. Examples of a language realization run with that language; examples of the
``*`` realization run with automatic language detection.
"""

from __future__ import annotations

import copy
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .patterns import LoadError, load_patterns, load_thresholds, repo_root

DETERMINISTIC_KINDS = ("regex", "lexicon", "metric")


@dataclass
class Failure:
    pattern_id: str
    lang: str
    what: str  # positive | negative | test_text
    index: int
    text: str
    detail: str

    def render(self) -> str:
        excerpt = " ".join(self.text.split())
        if len(excerpt) > 120:
            excerpt = excerpt[:117] + "..."
        return f"{self.pattern_id} [{self.lang}] {self.what} #{self.index + 1}: {self.detail}: \"{excerpt}\""


@dataclass
class FixtureReport:
    checked: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)
    failures: list[Failure] = field(default_factory=list)
    examples_run: int = 0

    @property
    def ok(self) -> bool:
        return not self.failures

    def render(self) -> str:
        lines = []
        if self.failures:
            lines.append(f"Fixture failures ({len(self.failures)}):")
            lines.extend(f"  {f.render()}" for f in self.failures)
        if self.skipped:
            lines.append(f"Skipped ({len(self.skipped)}):")
            lines.extend(f"  {pid}: {why}" for pid, why in sorted(self.skipped.items()))
        lines.append(
            f"check-fixtures: {len(self.checked)} pattern(s) checked, {self.examples_run} example(s) run, "
            f"{len(self.failures)} failure(s), {len(self.skipped)} skipped"
        )
        return "\n".join(lines)


def relaxed_threshold(pattern: dict) -> dict:
    """Detector-level threshold for examples (see module docstring)."""
    detector = pattern.get("detector") or {}
    base = pattern.get("threshold") or {}
    if detector.get("kind") == "metric" and base.get("value"):
        out = {"min_count": 1, "value": base["value"]}
        for key in ("scope", "min_units"):
            if base.get(key) is not None:
                out[key] = base[key]
        return out
    return {"min_count": 1}


def _catalog(pattern: dict, short_text_max_words: int) -> dict:
    from slopcheck.catalog import make_catalog

    entry = copy.deepcopy(pattern)
    entry["effective_status"] = "candidate"
    entry["weight"] = 0.0
    entry["weight_source"] = "none"
    return make_catalog([entry], short_text_max_words=short_text_max_words)


def _run(text: str, catalog: dict, pattern: dict, lang: str, context: str = "default") -> dict:
    from slopcheck.engine import analyze

    result = analyze(
        text,
        catalog,
        lang=None if lang == "*" else lang,
        context=context,
        modality=pattern.get("modality", "text"),
    )
    return (result.get("all_patterns") or {}).get(pattern["id"]) or {"triggered": False, "count": 0}


def _example_outcome(info: dict, pattern: dict) -> tuple[bool, str]:
    """(hit, description) for one example under the relaxed threshold."""
    count = int(info.get("count") or 0)
    if (pattern.get("detector") or {}).get("kind") == "metric" and (pattern.get("threshold") or {}).get("value"):
        value = info.get("value")
        return bool(info.get("triggered")), f"triggered={bool(info.get('triggered'))}, value={value}"
    return count >= 1, f"{count} hit(s)"


def check_pattern(pattern: dict, short_text_max_words: int, report: FixtureReport) -> None:
    pid = pattern["id"]
    relaxed = copy.deepcopy(pattern)
    relaxed["threshold"] = relaxed_threshold(pattern)
    relaxed["requires"] = None
    relaxed_catalog = _catalog(relaxed, short_text_max_words)
    full = copy.deepcopy(pattern)
    full["requires"] = None
    full_catalog = _catalog(full, short_text_max_words)
    realizations = pattern.get("realizations") or {}
    for lang in sorted(realizations):
        body = realizations[lang] or {}
        examples = body.get("examples") or {}
        for what, want_hit in (("positive", True), ("negative", False)):
            for i, text in enumerate(examples.get(what) or []):
                if not isinstance(text, str):
                    continue
                report.examples_run += 1
                info = _run(text, relaxed_catalog, relaxed, lang)
                hit, detail = _example_outcome(info, pattern)
                if hit != want_hit:
                    expected = "expected at least one hit" if want_hit else "expected no hit"
                    report.failures.append(Failure(pid, lang, what, i, text, f"{expected}, got {detail}"))
        for i, case in enumerate(body.get("test_texts") or []):
            if not isinstance(case, dict) or not isinstance(case.get("text"), str):
                continue
            report.examples_run += 1
            context = case.get("context") or "default"
            info = _run(case["text"], full_catalog, full, lang, context)
            want = case.get("expect") == "trigger"
            got = bool(info.get("triggered"))
            if got != want:
                detail = (
                    f"expected {case.get('expect')} (context {context}), got "
                    f"{'trigger' if got else 'no_trigger'} with {info.get('count', 0)} hit(s)"
                )
                if info.get("value") is not None:
                    detail += f", value={info['value']}"
                report.failures.append(Failure(pid, lang, "test_text", i, case["text"], detail))
    report.checked.append(pid)


def check_fixtures(
    patterns: list[dict], thresholds: dict, ids: list[str] | None = None
) -> FixtureReport:
    """Check examples and test texts of ``patterns`` (optionally only ``ids``)."""
    report = FixtureReport()
    by_id = {p["id"]: p for p in patterns}
    if ids:
        unknown = [i for i in ids if i not in by_id]
        if unknown:
            raise KeyError(", ".join(unknown))
        selected = [by_id[i] for i in ids]
    else:
        selected = list(patterns)
    short_max = int(thresholds.get("short_text_max_words") or 150)
    for pattern in sorted(selected, key=lambda p: p["id"]):
        kind = (pattern.get("detector") or {}).get("kind")
        if kind not in DETERMINISTIC_KINDS:
            reason = {
                "llm": "kind llm (needs a language model judge; checked by the LLM gate)",
                "vision": "kind vision (needs an image judge)",
                None: "no detector",
            }.get(kind, f"kind {kind}")
            report.skipped[pattern["id"]] = reason
            continue
        check_pattern(pattern, short_max, report)
    return report


def run(args) -> int:
    """CLI handler for ``slopcheck-dev check-fixtures``."""
    root = Path(args.root).resolve() if getattr(args, "root", None) else repo_root()
    try:
        patterns = load_patterns(root)
        thresholds = load_thresholds(root)
    except LoadError as exc:
        print(f"check-fixtures: {exc}", file=sys.stderr)
        return 2
    try:
        report = check_fixtures(patterns, thresholds, list(args.ids or []))
    except KeyError as exc:
        print(f"check-fixtures: unknown pattern id(s): {exc.args[0]}", file=sys.stderr)
        return 2
    print(report.render(), file=sys.stdout if report.ok else sys.stderr)
    return 0 if report.ok else 1
