"""``slopcheck-dev guard``: scored patterns stay in the gate (docs/architecture.md sections 5.3, 6.4, 8).

Content pull requests merge without review (D10) once the gates pass. The gates measure the
patterns a pull request changes, but they skip what they cannot measure: deleted files,
observations, non-text modalities and the detector kinds ``vision`` and none. A content pull
request could therefore take a scored pattern out of the score without any measurement, by
deleting or renaming its file, or by changing its status, modality or detector kind.

The guard compares every scored pattern on the base commit with the working tree and fails if

- its file is gone from its path (deleted, renamed or moved),
- its ``id``, ``status``, ``modality`` or ``detector.kind`` changed.

Edits to thresholds, examples, regexes, word lists and rubrics stay open to content pull
requests; the empirical gate and the LLM gate measure them.

Scored ("guarded") patterns:

- every id in ``governance/thresholds.yaml: initial_core`` (base commit and working tree),
- every pattern that declares ``status: core`` on the base commit,
- with ``--measurements``, every pattern that is effective core on the base commit according to
  that file (``slopcheck_dev.status.derive``, with the hash check against the base version).

Such a change is a maintainer decision. A pull request that also changes ``governance/`` needs
code-owner review (.github/CODEOWNERS), so the guard then reports the changes as notices and
passes, leaving the decision to that review.

The base is the merge base of BASE_REF and HEAD, or the BASE_REF commit itself when git finds no
merge base (for example in a shallow clone).

Exit codes: 0 ok, 1 a guarded pattern changed, 2 usage, git or input error.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .patterns import (
    PATTERN_DIR,
    THRESHOLDS_FILE,
    LoadError,
    load_pattern_records,
    load_yaml,
    normalize_dates,
    repo_root,
)
from .status import derive, measurement_for
from .validate import git, paths_changed_since

#: A pull request that changes a path below this prefix needs code-owner review.
GOVERNANCE_PREFIX = "governance/"


def _detector_kind(pattern: dict):
    detector = pattern.get("detector")
    return detector.get("kind") if isinstance(detector, dict) else None


#: Fields whose change takes a pattern out of the score or out of the gates.
GUARDED_FIELDS = (
    ("status", lambda p: p.get("status")),
    ("modality", lambda p: p.get("modality")),
    ("detector.kind", _detector_kind),
)

MAINTAINER_NOTE = (
    "A content pull request cannot take a scored pattern out of the score or out of the gates "
    "that measure it: deleting or renaming its file, or changing its status, modality or detector "
    "kind, needs a maintainer. Such a change has to come with a governance/ change in the same pull "
    "request (for example removing the id from governance/thresholds.yaml: initial_core), which "
    "requires code-owner review. Edits to thresholds, examples, regexes, word lists and rubrics "
    "remain open to everyone; the empirical gate and the LLM gate measure them."
)


class GuardError(RuntimeError):
    """The guard cannot run (unknown base ref, git failure, unreadable input)."""


@dataclass
class Finding:
    path: str
    pattern_id: str
    guarded_as: str
    changes: list[str]

    def __str__(self) -> str:
        return f"`{self.path}` (`{self.pattern_id}`, {self.guarded_as}): " + "; ".join(self.changes)


@dataclass
class GuardResult:
    base: str
    guarded: dict[str, str] = field(default_factory=dict)  # pattern id -> why it is guarded
    findings: list[Finding] = field(default_factory=list)
    governance_changed: bool = False
    notices: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings or self.governance_changed


# ---------------------------------------------------------------------------
# reading the base commit


def resolve_base(base_ref: str, root: Path) -> str:
    """Commit id to compare with: merge base of ``base_ref`` and HEAD, else ``base_ref`` itself."""
    try:
        commit = git(root, "rev-parse", "--verify", "--quiet", f"{base_ref}^{{commit}}").strip()
    except RuntimeError:
        commit = ""
    if not commit:
        raise GuardError(f"unknown base ref {base_ref!r} (fetch it first, for example with fetch-depth 2)")
    try:
        merge_base = git(root, "merge-base", commit, "HEAD").strip()
    except RuntimeError:
        merge_base = ""
    return merge_base or commit


def _parse_yaml(text: str):
    """Parse YAML text like ``load_yaml`` does; raise LoadError on invalid YAML."""
    import yaml  # dev dependency

    try:
        return normalize_dates(yaml.safe_load(text))
    except yaml.YAMLError as exc:
        raise LoadError(f"invalid YAML: {type(exc).__name__}") from exc


def _show(root: Path, base: str, rel: str) -> str | None:
    try:
        return git(root, "show", f"{base}:./{rel}")
    except RuntimeError:
        return None


def base_patterns(base: str, root: Path, notices: list[str]) -> dict[str, dict]:
    """Pattern files on commit ``base``: relative path -> parsed mapping."""
    listing = git(root, "ls-tree", "-r", "-z", "--name-only", base, "--", PATTERN_DIR)
    out: dict[str, dict] = {}
    for rel in sorted(n for n in listing.split("\0") if n.endswith((".yaml", ".yml"))):
        text = _show(root, base, rel)
        try:
            data = _parse_yaml(text) if text is not None else None
        except LoadError as exc:
            notices.append(f"{rel}: cannot parse the base version ({exc}); not compared")
            continue
        if isinstance(data, dict) and isinstance(data.get("id"), str):
            out[rel] = data
    return out


def base_thresholds(base: str, root: Path) -> dict:
    text = _show(root, base, THRESHOLDS_FILE.as_posix())
    if text is None:
        return {}
    try:
        data = _parse_yaml(text)
    except LoadError:
        return {}
    return data if isinstance(data, dict) else {}


def _initial_core_ids(thresholds: dict) -> set[str]:
    table = thresholds.get("initial_core")
    return {str(k) for k in table} if isinstance(table, dict) else set()


def _working_thresholds(root: Path) -> dict:
    path = root / THRESHOLDS_FILE
    if not path.is_file():
        return {}
    try:
        data = load_yaml(path)
    except LoadError:
        return {}
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# guard


def guarded_patterns(
    base_files: dict[str, dict],
    thresholds_base: dict,
    thresholds_work: dict,
    measurements: dict | None,
) -> dict[str, str]:
    """Pattern id -> why it is guarded, for every scored pattern of the base commit."""
    reasons: dict[str, list[str]] = {}

    def add(pid: str, why: str) -> None:
        if why not in reasons.setdefault(pid, []):
            reasons[pid].append(why)

    for pid in sorted(_initial_core_ids(thresholds_base) | _initial_core_ids(thresholds_work)):
        add(pid, "initial core")
    for data in base_files.values():
        pid = data["id"]
        if data.get("status") == "core":
            add(pid, "declares status core")
        if measurements is None:
            continue
        try:
            status, _weight, source = derive(data, measurement_for(measurements, pid), thresholds_base)
        except ValueError:
            continue
        if status == "core":
            add(pid, f"effective core ({source} weight)")
    return {pid: ", ".join(why) for pid, why in sorted(reasons.items())}


def _fmt(value) -> str:
    return "none" if value is None else str(value)


def guard(
    root: str | Path,
    base_ref: str,
    measurements: dict | None = None,
) -> GuardResult:
    """Compare the guarded patterns on the base commit with the working tree at ``root``."""
    root = Path(root).resolve()
    try:
        base = resolve_base(base_ref, root)
        result = GuardResult(base=base)
        old_files = base_patterns(base, root, result.notices)
        thresholds_old = base_thresholds(base, root)
        changed = paths_changed_since(base, root)
    except RuntimeError as exc:
        raise GuardError(str(exc)) from exc
    result.governance_changed = any(p.startswith(GOVERNANCE_PREFIX) for p in changed)
    result.guarded = guarded_patterns(old_files, thresholds_old, _working_thresholds(root), measurements)

    work = {rec.rel(root): rec for rec in load_pattern_records(root)}
    work_ids: dict[str, list[str]] = {}
    for rel, rec in work.items():
        if isinstance(rec.data, dict) and isinstance(rec.data.get("id"), str):
            work_ids.setdefault(rec.data["id"], []).append(rel)

    for rel, old in sorted(old_files.items()):
        pid = old["id"]
        if pid not in result.guarded:
            continue
        changes: list[str] = []
        rec = work.get(rel)
        if rec is None:
            elsewhere = [r for r in work_ids.get(pid, []) if r != rel]
            if elsewhere:
                changes.append(f"file moved to `{elsewhere[0]}`")
            else:
                changes.append("file deleted or renamed")
        elif not isinstance(rec.data, dict):
            changes.append("file no longer parses as a pattern, so it cannot be compared")
        else:
            new = rec.data
            if new.get("id") != pid:
                changes.append(f"id changed from {pid} to {_fmt(new.get('id'))}")
            for label, get in GUARDED_FIELDS:
                before, after = get(old), get(new)
                if before != after:
                    changes.append(f"{label} changed from {_fmt(before)} to {_fmt(after)}")
        if changes:
            result.findings.append(Finding(rel, pid, result.guarded[pid], changes))
    return result


def render(result: GuardResult, base_ref: str) -> str:
    lines = ["## Scored-pattern guard", ""]
    lines.append(
        f"Base: `{result.base[:12]}` ({base_ref}). Guarded: {len(result.guarded)} scored pattern(s)."
    )
    lines.append("")
    for notice in result.notices:
        lines.append(f"Notice: {notice}")
    if result.notices:
        lines.append("")
    if not result.findings:
        lines.append("No scored pattern was deleted, renamed or taken out of the gates.")
        lines.append("")
        lines.append("Result: passed.")
        return "\n".join(lines) + "\n"
    heading = "Changes that take scored patterns out of the score or out of the gates:"
    lines += [heading, ""]
    lines += [f"- {f}" for f in result.findings]
    lines += ["", MAINTAINER_NOTE, ""]
    if result.governance_changed:
        lines.append(
            "This pull request also changes governance/, so it needs code-owner review; the guard "
            "leaves the decision to that review."
        )
        lines.append("")
        lines.append(f"Result: passed with {len(result.findings)} notice(s).")
    else:
        lines.append(f"Result: failed ({len(result.findings)} pattern(s)).")
    return "\n".join(lines) + "\n"


def run(args) -> int:
    """CLI handler for ``slopcheck-dev guard``."""
    root = Path(args.root).resolve() if getattr(args, "root", None) else repo_root()
    measurements = None
    if getattr(args, "measurements", None):
        try:
            measurements = json.loads(Path(args.measurements).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"guard: cannot read {args.measurements}: {exc}", file=sys.stderr)
            return 2
        if not isinstance(measurements, dict):
            print(f"guard: {args.measurements}: expected a JSON object", file=sys.stderr)
            return 2
    try:
        result = guard(root, args.base, measurements)
    except GuardError as exc:
        print(f"guard: {exc}", file=sys.stderr)
        return 2
    text = render(result, args.base)
    print(text, end="", file=sys.stdout if result.ok else sys.stderr)
    if getattr(args, "summary", None):
        with open(args.summary, "a", encoding="utf-8") as fh:
            fh.write(text)
    return 0 if result.ok else 1
