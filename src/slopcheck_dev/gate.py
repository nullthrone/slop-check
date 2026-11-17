"""``slopcheck-dev gate``: pull request admission rules on the dev split (sections 5 and 6).

Input: a measurement file written by ``slopcheck-dev measure --split dev`` for the
patterns a pull request touches, the patterns as they are in the pull request, and
optionally the current ``measurements.json`` from branch ``data``.

Rules per pattern:

- Patterns that score after the merge must meet the core criteria on the dev split
  (``meets_core`` in the measurement). That covers patterns that are effective core now
  (by measurement or bootstrap) and every declared ``core`` pattern, because an edited
  pattern falls back to its declared status until it is remeasured.
- Other candidates need ``fpr_human <= admission.candidate.pr_gate.max_fpr_human``, pooled
  and in every measured language.
- The measurement must come from the dev split and its ``pattern_hash`` must match the
  pattern as it is in the pull request.
- Observations, ``kind: llm`` (gated by the LLM workflow), ``kind: vision`` and non-text
  patterns are skipped and listed.

Prints a Markdown summary; exit code 1 if any pattern fails.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .patterns import LoadError, load_patterns, load_thresholds, repo_root
from .status import derive, measurement_for, pattern_hash


@dataclass
class GateRow:
    pattern_id: str
    rule: str
    result: str  # pass | fail | skipped
    fpr_human: float | None = None
    lift: float | None = None
    reasons: list[str] = field(default_factory=list)


@dataclass
class GateResult:
    rows: list[GateRow]
    errors: list[str] = field(default_factory=list)
    markdown: str = ""

    @property
    def ok(self) -> bool:
        return not self.errors and all(r.result != "fail" for r in self.rows)


def _fmt(x: float | None, digits: int = 3) -> str:
    if x is None:
        return "-"
    return f"{float(x):.{digits}f}".rstrip("0").rstrip(".") if float(x) != 0 else "0"


def _core_reasons(entry: dict, thresholds: dict) -> list[str]:
    """Which core criteria the entry visibly misses (explanation only; the decision is meets_core)."""
    core = (thresholds.get("admission") or {}).get("core") or {}
    reasons = []
    fpr, lift = entry.get("fpr_human"), entry.get("lift")
    max_fpr = float(core.get("max_fpr_human", 0.05))
    if fpr is None or lift is None:
        reasons.append("no human or AI documents measured")
        return reasons
    if fpr > max_fpr:
        reasons.append(f"fpr_human {_fmt(fpr)} above {_fmt(max_fpr)}")
    for lang, pl in sorted((entry.get("per_language") or {}).items()):
        if pl.get("fpr_human") is not None and pl["fpr_human"] > max_fpr:
            reasons.append(f"fpr_human ({lang}) {_fmt(pl['fpr_human'])} above {_fmt(max_fpr)}")
        min_docs = int(core.get("min_human_docs_per_language", 100))
        if (pl.get("n_human") or 0) < min_docs:
            reasons.append(f"only {pl.get('n_human') or 0} human documents ({lang}), need {min_docs}")
    min_lift = float(core.get("min_lift", 2.0))
    if lift < min_lift:
        reasons.append(f"lift {_fmt(lift)} below {_fmt(min_lift)}")
    fam_lift = float(core.get("min_family_lift", 1.5))
    families = [f for f, v in (entry.get("per_family") or {}).items() if (v.get("lift") or 0) >= fam_lift]
    need_fam = int(core.get("min_model_families", 2))
    if len(families) < need_fam:
        reasons.append(f"{len(families)} model families with lift >= {_fmt(fam_lift)}, need {need_fam}")
    if not reasons:
        reasons.append("meets_core is false (for example too few triggered AI documents)")
    return reasons


def _skip_reason(pattern: dict) -> str | None:
    kind = (pattern.get("detector") or {}).get("kind")
    if pattern.get("status") == "observation":
        return "observation (not scored, no empirical gate)"
    if pattern.get("modality", "text") != "text":
        return f"modality {pattern.get('modality')} (no benchmark for this modality yet)"
    if kind is None:
        return "no detector"
    if kind == "llm":
        return "kind llm (gated by the llm-gate workflow)"
    if kind == "vision":
        return "kind vision (no image benchmark yet)"
    return None


def gate(
    measure_json: dict,
    patterns: list[dict],
    thresholds: dict,
    current_measurements: dict | None = None,
) -> GateResult:
    """Apply the admission rules to ``patterns`` (the patterns to gate, as in the pull request)."""
    errors: list[str] = []
    rows: list[GateRow] = []
    corpus = measure_json.get("corpus") or {}
    split = corpus.get("split")
    if split not in (None, "dev"):
        errors.append(f"the measurement comes from split '{split}'; the pull request gate uses dev only")
    candidate_cfg = (thresholds.get("admission") or {}).get("candidate") or {}
    max_fpr = float((candidate_cfg.get("pr_gate") or {}).get("max_fpr_human", 0.15))
    for pattern in sorted(patterns, key=lambda p: p["id"]):
        pid = pattern["id"]
        skip = _skip_reason(pattern)
        if skip:
            rows.append(GateRow(pid, "-", "skipped", reasons=[skip]))
            continue
        current = measurement_for(current_measurements, pid)
        now_status, _w, _src = derive(pattern, current, thresholds, check_hash=False)
        core_rule = now_status == "core" or pattern.get("status") == "core"
        rule = "core criteria (dev split)" if core_rule else f"fpr_human <= {_fmt(max_fpr)}"
        entry = measurement_for(measure_json, pid)
        if entry is None:
            rows.append(GateRow(pid, rule, "fail", reasons=["no measurement for this pattern in the file"]))
            continue
        row = GateRow(pid, rule, "pass", entry.get("fpr_human"), entry.get("lift"))
        if entry.get("pattern_hash") != pattern_hash(pattern):
            row.result = "fail"
            row.reasons.append("stale measurement: pattern_hash differs from the pattern file; rerun measure")
        elif core_rule:
            if not entry.get("meets_core"):
                row.result = "fail"
                row.reasons.extend(_core_reasons(entry, thresholds))
        else:
            fpr = entry.get("fpr_human")
            if fpr is None:
                row.result = "fail"
                row.reasons.append("no human documents measured")
            elif fpr > max_fpr:
                row.result = "fail"
                row.reasons.append(f"fpr_human {_fmt(fpr)} above {_fmt(max_fpr)}")
            for lang, pl in sorted((entry.get("per_language") or {}).items()):
                lf = pl.get("fpr_human")
                if lf is not None and lf > max_fpr:
                    row.result = "fail"
                    row.reasons.append(f"fpr_human ({lang}) {_fmt(lf)} above {_fmt(max_fpr)}")
        rows.append(row)
    result = GateResult(rows=rows, errors=errors)
    result.markdown = render_markdown(result, measure_json)
    return result


def render_markdown(result: GateResult, measure_json: dict) -> str:
    corpus = measure_json.get("corpus") or {}
    lines = ["## Empirical gate (dev split)", ""]
    human = corpus.get("human_docs") or {}
    ai = corpus.get("ai_docs") or {}
    if human or ai:
        h = ", ".join(f"{k} {v}" for k, v in sorted(human.items())) or "none"
        a = ", ".join(f"{k} {v}" for k, v in sorted(ai.items())) or "none"
        lines.append(f"Human documents: {h}. AI documents: {a}.")
        lines.append("")
    for err in result.errors:
        lines.append(f"Error: {err}")
        lines.append("")
    if not result.rows:
        lines.append("No patterns to gate.")
    else:
        lines.append("| Pattern | Rule | fpr_human | lift | Result |")
        lines.append("|---|---|---|---|---|")
        for r in result.rows:
            fpr, lift = _fmt(r.fpr_human), _fmt(r.lift)
            lines.append(f"| `{r.pattern_id}` | {r.rule} | {fpr} | {lift} | {r.result} |")
        notes = [r for r in result.rows if r.reasons]
        if notes:
            lines.append("")
            lines.append("Details:")
            lines.append("")
            for r in notes:
                lines.append(f"- `{r.pattern_id}` ({r.result}): " + "; ".join(r.reasons))
    lines.append("")
    failed = sum(1 for r in result.rows if r.result == "fail")
    if result.ok:
        lines.append("Result: passed.")
    else:
        lines.append(f"Result: failed ({failed} pattern(s), {len(result.errors)} error(s)).")
    return "\n".join(lines) + "\n"


def _read_json(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return data


def run(args) -> int:
    """CLI handler for ``slopcheck-dev gate``."""
    root = Path(args.root).resolve() if getattr(args, "root", None) else repo_root()
    try:
        measure_json = _read_json(args.measure)
        current = _read_json(args.current) if getattr(args, "current", None) else None
        all_patterns = load_patterns(root)
        thresholds = load_thresholds(root)
    except (OSError, ValueError, LoadError) as exc:
        print(f"gate: {exc}", file=sys.stderr)
        return 2
    by_id = {p["id"]: p for p in all_patterns}
    ids = list(dict.fromkeys(args.patterns or []))
    result = gate(measure_json, [by_id[i] for i in ids if i in by_id], thresholds, current)
    missing = [i for i in ids if i not in by_id]
    if missing:
        # deleted pattern files need no admission; list them so a typo stays visible
        for i in missing:
            result.rows.append(GateRow(i, "-", "skipped", reasons=["no pattern file with this id"]))
        result.rows.sort(key=lambda r: r.pattern_id)
        result.markdown = render_markdown(result, measure_json)
    print(result.markdown, end="")
    if getattr(args, "summary", None):
        with open(args.summary, "a", encoding="utf-8") as fh:
            fh.write(result.markdown)
    return 0 if result.ok else 1
