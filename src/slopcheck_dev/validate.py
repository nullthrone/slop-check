"""``slopcheck-dev validate``: schema and rule checks (docs/architecture.md sections 3 and 5.2).

Per-file checks (limited to changed files with ``--changed-only``):

- JSON Schema validation of patterns and sources;
- rule 2 examples (per realization language, counts from ``admission.candidate``);
- rule 5 regex safety (compile, nested unbounded quantifiers, adversarial timing);
- rule 6 unique lexicon terms per language (case-insensitive);
- rule 7 realization keys;
- rule 8 file name and directory;
- detector payload present for regex and lexicon detectors.

Cross-file checks (always run on every file):

- duplicate pattern and source ids;
- rule 1 initial core (``governance/thresholds.yaml: initial_core``, a mapping of id to weight);
- rule 2 and 3 source counts, with independence clusters per section 5.2;
- rule 4 source references resolve, source ``derived_from`` resolves;
- ``related`` ids resolve.

Errors print as ``<path>: <message>``; the exit code is 1 if any error was found.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from . import regex_safety
from .patterns import (
    MODALITIES,
    PATTERN_DIR,
    SOURCE_DIR,
    THRESHOLDS_FILE,
    LoadError,
    Record,
    load_pattern_records,
    load_schema,
    load_source_records,
    load_thresholds,
    relpath,
    repo_root,
)

LANG_KEY = re.compile(r"^([a-z]{2,3}|\*)$")
OWN_OBSERVATION = "own-observation"
#: Changes below these paths make ``--changed-only`` validate everything.
FULL_RUN_PREFIXES = ("schema/", "governance/", "src/slopcheck_dev/")


@dataclass
class Issue:
    path: str
    message: str
    level: str = "error"

    def __str__(self) -> str:
        prefix = "" if self.level == "error" else f"{self.level}: "
        return f"{self.path}: {prefix}{self.message}"


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)
    patterns: int = 0
    sources: int = 0
    checked_files: int = 0
    regexes_timed: int = 0

    def error(self, path: str, message: str) -> None:
        self.issues.append(Issue(path, message))

    def warn(self, path: str, message: str) -> None:
        self.issues.append(Issue(path, message, "warning"))

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def sorted_issues(self) -> list[Issue]:
        return sorted(self.issues, key=lambda i: (i.path, i.level != "error", i.message))

    def render(self) -> str:
        lines = [str(i) for i in self.sorted_issues()]
        lines.append(
            f"validate: {len(self.errors)} error(s), {len(self.warnings)} warning(s); "
            f"{self.patterns} pattern(s), {self.sources} source(s), "
            f"{self.checked_files} file(s) checked in full, {self.regexes_timed} regex(es) timed"
        )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# source independence (section 5.2)


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            if rb < ra:
                ra, rb = rb, ra
            self.parent[rb] = ra


def _publisher_key(source: dict) -> str | None:
    publisher = source.get("publisher")
    if not isinstance(publisher, str) or not publisher.strip():
        return None
    return " ".join(publisher.split()).casefold()


def source_clusters(sources: dict[str, dict]) -> dict[str, str]:
    """Map each source id to a cluster id.

    Two sources share a cluster if one lists the other in ``derived_from`` (followed
    transitively, as connected components) or they have the same ``publisher``
    (case-insensitive). The cluster id is the smallest source id in the cluster.
    """
    uf = _UnionFind()
    by_publisher: dict[str, str] = {}
    for sid in sorted(sources):
        src = sources[sid] or {}
        uf.find(sid)
        for parent in src.get("derived_from") or []:
            if isinstance(parent, str) and parent in sources:
                uf.union(sid, parent)
        key = _publisher_key(src)
        if key is not None:
            if key in by_publisher:
                uf.union(sid, by_publisher[key])
            else:
                by_publisher[key] = sid
    return {sid: uf.find(sid) for sid in sources}


def independent_source_count(
    pattern: dict, sources: dict[str, dict], clusters: dict[str, str] | None = None
) -> int:
    """Distinct clusters among the pattern's resolvable sources; own-observation never counts."""
    clusters = clusters if clusters is not None else source_clusters(sources)
    seen = set()
    for ref in pattern.get("sources") or []:
        sid = ref.get("source") if isinstance(ref, dict) else None
        if sid not in sources:
            continue
        if (sources[sid] or {}).get("type") == OWN_OBSERVATION:
            continue
        seen.add(clusters.get(sid, sid))
    return len(seen)


# ---------------------------------------------------------------------------
# schema


def _validator(schema: dict):
    from jsonschema import Draft202012Validator

    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def _schema_errors(validator, data: object) -> list[str]:
    out = []
    for err in validator.iter_errors(data):
        loc = ".".join(str(p) for p in err.absolute_path) or "(root)"
        out.append(f"schema: {loc}: {err.message}")
    return sorted(set(out))


# ---------------------------------------------------------------------------
# per-file pattern checks


def _realizations(pattern: dict) -> dict[str, dict]:
    real = pattern.get("realizations")
    if not isinstance(real, dict):
        return {}
    return {str(k): v for k, v in real.items() if isinstance(v, dict)}


def _check_location(report: Report, rel: str, path: Path, root: Path, pattern: dict) -> None:
    """Rule 8: ``patterns/<modality>/<id>.yaml``."""
    pid = pattern.get("id")
    modality = pattern.get("modality")
    expected_dir = (root / PATTERN_DIR / str(modality)).resolve()
    if path.suffix != ".yaml":
        report.error(rel, "rule 8: pattern files use the extension .yaml")
    if isinstance(pid, str) and path.stem != pid:
        report.error(rel, f"rule 8: file name must be '{pid}.yaml' (id is '{pid}')")
    if path.parent.resolve() != expected_dir:
        where = relpath(path.parent, root)
        report.error(rel, f"rule 8: modality '{modality}' goes in patterns/{modality}/, found in {where}/")


def _check_realization_keys(report: Report, rel: str, pattern: dict) -> None:
    """Rule 7."""
    real = pattern.get("realizations")
    if not isinstance(real, dict):
        return
    for key in real:
        if not isinstance(key, str) or not LANG_KEY.match(key):
            report.error(rel, f"rule 7: realization key {key!r} is neither a language subtag nor '*'")


def _check_terms(report: Report, rel: str, pattern: dict) -> None:
    """Rule 6: lexicon terms unique per language (matching is case-insensitive)."""
    for lang, real in _realizations(pattern).items():
        seen: dict[str, str] = {}
        for term in real.get("terms") or []:
            if not isinstance(term, str):
                continue
            key = " ".join(term.split()).lower()  # the engine matches with re.IGNORECASE
            if key in seen:
                dup = f"duplicate term {term!r} (also {seen[key]!r})"
                report.error(rel, f"rule 6: realizations.{lang}.terms: {dup}")
            else:
                seen[key] = term


def _check_payload(report: Report, rel: str, pattern: dict) -> None:
    """Regex and lexicon detectors need a payload for every language they apply to
    (an error for candidate and core, a warning for observations)."""
    detector = pattern.get("detector")
    if not isinstance(detector, dict):
        return
    kind = detector.get("kind")
    field_name = {"regex": "patterns", "lexicon": "terms"}.get(kind)
    if field_name is None:
        return
    real = _realizations(pattern)
    star = bool((real.get("*") or {}).get(field_name))
    emit = report.warn if pattern.get("status") == "observation" else report.error
    for lang, body in sorted(real.items()):
        if not body.get(field_name) and not star:
            emit(rel, f"detector kind {kind}: realizations.{lang} lacks '{field_name}' (so does '*')")


def _check_examples(report: Report, rel: str, pattern: dict, thresholds: dict) -> None:
    """Rule 2 (examples part): per realization language >= N positive and negative examples."""
    if pattern.get("status") != "candidate":
        return
    cfg = ((thresholds.get("admission") or {}).get("candidate") or {}).get("min_examples_per_language") or {}
    need_pos = int(cfg.get("positive", 2))
    need_neg = int(cfg.get("negative", 2))
    for lang, body in sorted(_realizations(pattern).items()):
        examples = body.get("examples") or {}
        pos = len([e for e in examples.get("positive") or [] if isinstance(e, str) and e.strip()])
        neg = len([e for e in examples.get("negative") or [] if isinstance(e, str) and e.strip()])
        if pos < need_pos or neg < need_neg:
            report.error(
                rel,
                f"rule 2: candidate needs at least {need_pos} positive and {need_neg} negative examples "
                f"per realization language; realizations.{lang} has {pos} positive, {neg} negative",
            )


def _regex_items(pattern: dict) -> list[tuple[str, str, str, list[str]]]:
    """(lang, location, regex, positive examples) for every regex payload entry."""
    out = []
    for lang, body in sorted(_realizations(pattern).items()):
        positives = [e for e in (body.get("examples") or {}).get("positive") or [] if isinstance(e, str)]
        for i, rx in enumerate(body.get("patterns") or []):
            if isinstance(rx, str):
                out.append((lang, f"realizations.{lang}.patterns[{i}]", rx, positives))
    return out


def _check_regexes(
    report: Report, files: list[tuple[str, dict]], timing: bool, limit_ms: float = regex_safety.TIME_LIMIT_MS
) -> None:
    """Rule 5 for every pattern in ``files``."""
    inputs = regex_safety.generic_inputs()
    generic = sorted(inputs)
    items: list[regex_safety.TimingItem] = []
    owners: list[tuple[str, str]] = []
    for rel, pattern in files:
        for lang, loc, rx, positives in _regex_items(pattern):
            err = regex_safety.compile_error(rx)
            if err:
                report.error(rel, f"rule 5: {loc}: does not compile: {err}")
                continue
            nested = regex_safety.nested_quantifiers(rx)
            if nested:
                frag = ", ".join(repr(n) for n in nested)
                report.error(rel, f"rule 5: {loc}: nested unbounded quantifier {frag}")
                continue
            names = list(generic)
            example = regex_safety.example_input(positives)
            if example is not None:
                key = f"examples:{pattern.get('id')}:{lang}"
                inputs[key] = example
                names.append(key)
            items.append(regex_safety.TimingItem(pattern=rx, inputs=names, label=loc))
            owners.append((rel, loc))
    if not timing or not items:
        return
    results = regex_safety.time_patterns(items, inputs, limit_ms=limit_ms)
    report.regexes_timed += len(results)
    for (rel, loc), res in zip(owners, results, strict=True):
        for problem in res.problems(limit_ms):
            report.error(rel, f"rule 5: {loc}: {problem}")


# ---------------------------------------------------------------------------
# cross-file checks


def _check_sources_cross(report: Report, records: list[tuple[str, dict]], sources: dict[str, dict]) -> None:
    for rel, src in records:
        sid = src.get("id")
        for parent in src.get("derived_from") or []:
            if parent == sid:
                report.error(rel, "derived_from lists the source itself")
            elif parent not in sources:
                report.error(rel, f"derived_from '{parent}' does not resolve to sources/{parent}.yaml")


def _check_patterns_cross(
    report: Report,
    records: list[tuple[str, dict]],
    sources: dict[str, dict],
    pattern_ids: set[str],
    thresholds: dict,
) -> None:
    table = thresholds.get("initial_core")
    initial = {str(k) for k in table} if isinstance(table, dict) else set()
    admission = thresholds.get("admission") or {}
    min_independent = int((admission.get("candidate") or {}).get("min_independent_sources", 2))
    min_obs = int((admission.get("observation") or {}).get("min_sources", 1))
    clusters = source_clusters(sources)
    for rel, pattern in records:
        pid = pattern.get("id")
        status = pattern.get("status")
        refs = [r for r in pattern.get("sources") or [] if isinstance(r, dict)]
        # rule 4
        for ref in refs:
            sid = ref.get("source")
            if sid not in sources:
                report.error(rel, f"rule 4: source '{sid}' does not resolve to sources/{sid}.yaml")
        # rule 1
        if status == "core" and pid not in initial:
            report.error(
                rel,
                "rule 1: status core is reserved for ids listed in governance/thresholds.yaml: "
                "initial_core; new patterns start as candidate or observation",
            )
        # rule 2 (sources) and rule 3
        if status == "candidate":
            n = independent_source_count(pattern, sources, clusters)
            if n < min_independent:
                report.error(
                    rel,
                    f"rule 2: candidate needs at least {min_independent} independent sources, has {n} "
                    "(same publisher or derived_from chains form one cluster; own-observation never counts)",
                )
        if status == "observation":
            n = len({r.get("source") for r in refs if r.get("source") in sources})
            if n < min_obs:
                report.error(rel, f"rule 3: observation needs at least {min_obs} source(s), has {n}")
        # related
        for rel_entry in pattern.get("related") or []:
            if not isinstance(rel_entry, dict):
                continue
            target = rel_entry.get("id")
            if target == pid:
                report.error(rel, "related: a pattern cannot relate to itself")
            elif target not in pattern_ids:
                report.error(rel, f"related: id '{target}' does not resolve to a pattern")


def _check_initial_core(report: Report, thresholds: dict, pattern_ids: set[str]) -> None:
    """``initial_core`` maps pattern ids to non-negative provisional weights."""
    rel = THRESHOLDS_FILE.as_posix()
    table = thresholds.get("initial_core")
    if table is None:
        return
    if not isinstance(table, dict):
        report.error(rel, "initial_core must be a mapping of pattern id to provisional weight")
        return
    for pid, weight in table.items():
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or weight < 0:
            report.error(rel, f"initial_core: weight of '{pid}' must be a non-negative number, is {weight!r}")
        if pid not in pattern_ids:
            report.warn(rel, f"initial_core: '{pid}' has no pattern file")


def _duplicates(report: Report, records: list[tuple[str, dict]], what: str) -> None:
    seen: dict[str, str] = {}
    for rel, data in records:
        rid = data.get("id")
        if not isinstance(rid, str):
            continue
        if rid in seen:
            report.error(rel, f"duplicate {what} id '{rid}' (also in {seen[rid]})")
        else:
            seen[rid] = rel


# ---------------------------------------------------------------------------
# changed files


def changed_files(base_ref: str, root: Path) -> set[str]:
    """Paths (relative to ``root``) changed against the merge base with ``base_ref``,
    including uncommitted and untracked files."""

    def git(*args: str) -> str:
        proc = subprocess.run(  # noqa: S603 - fixed git invocation
            ["git", *args],  # noqa: S607
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
        return proc.stdout

    base = git("merge-base", base_ref, "HEAD").strip() or base_ref
    names = set(git("diff", "--name-only", "--no-renames", base).split("\n"))
    names |= set(git("ls-files", "--others", "--exclude-standard").split("\n"))
    prefix = git("rev-parse", "--show-prefix").strip()
    out = set()
    for name in names:
        name = name.strip()
        if not name:
            continue
        if prefix and name.startswith(prefix):
            name = name[len(prefix) :]
        out.add(name)
    return out


# ---------------------------------------------------------------------------
# entry point


def validate(
    root: str | Path | None = None,
    changed: Iterable[str] | None = None,
    regex_timing: bool = True,
    limit_ms: float = regex_safety.TIME_LIMIT_MS,
) -> Report:
    """Validate the repository at ``root``.

    ``changed`` limits per-file checks to these paths (relative to ``root``); None checks
    every file. Cross-file checks always cover every file.
    """
    root = Path(root).resolve() if root else repo_root()
    report = Report()
    try:
        thresholds = load_thresholds(root)
        pattern_validator = _validator(load_schema(root, "pattern"))
        source_validator = _validator(load_schema(root, "source"))
    except LoadError as exc:
        report.error("(setup)", str(exc))
        return report

    changed_set = None if changed is None else {c.replace("\\", "/") for c in changed}
    if changed_set is not None and any(c.startswith(FULL_RUN_PREFIXES) for c in changed_set):
        changed_set = None

    def in_scope(rel: str) -> bool:
        return changed_set is None or rel in changed_set

    pattern_records = load_pattern_records(root)
    source_records = load_source_records(root)

    # --- sources
    sources_ok: list[tuple[str, dict]] = []
    for rec in source_records:
        rel = rec.rel(root)
        data = _parsed(report, rec, rel, "source")
        if data is None:
            continue
        sources_ok.append((rel, data))
        if in_scope(rel):
            report.checked_files += 1
            for msg in _schema_errors(source_validator, data):
                report.error(rel, msg)
            sid = data.get("id")
            if isinstance(sid, str) and rec.path.stem != sid:
                report.error(rel, f"file name must be '{sid}.yaml' (id is '{sid}')")
            if rec.path.parent.resolve() != (root / SOURCE_DIR).resolve() or rec.path.suffix != ".yaml":
                report.error(rel, f"sources live directly in {SOURCE_DIR}/ with the extension .yaml")
    report.sources = len(sources_ok)
    _duplicates(report, sources_ok, "source")
    sources = {}
    for _rel, data in sources_ok:
        if isinstance(data.get("id"), str):
            sources.setdefault(data["id"], data)
    _check_sources_cross(report, sources_ok, sources)

    # --- patterns
    patterns_ok: list[tuple[str, dict]] = []
    timed: list[tuple[str, dict]] = []
    for rec in pattern_records:
        rel = rec.rel(root)
        data = _parsed(report, rec, rel, "pattern")
        if data is None:
            continue
        patterns_ok.append((rel, data))
        if not in_scope(rel):
            continue
        report.checked_files += 1
        for msg in _schema_errors(pattern_validator, data):
            report.error(rel, msg)
        if data.get("modality") not in MODALITIES:
            report.error(rel, f"rule 8: unknown modality {data.get('modality')!r}")
        _check_location(report, rel, rec.path, root, data)
        _check_realization_keys(report, rel, data)
        _check_terms(report, rel, data)
        _check_payload(report, rel, data)
        _check_examples(report, rel, data, thresholds)
        timed.append((rel, data))
    report.patterns = len(patterns_ok)
    _duplicates(report, patterns_ok, "pattern")
    ids = {d["id"] for _r, d in patterns_ok if isinstance(d.get("id"), str)}
    _check_initial_core(report, thresholds, ids)
    _check_patterns_cross(report, patterns_ok, sources, ids, thresholds)
    _check_regexes(report, timed, regex_timing, limit_ms)
    return report


def _parsed(report: Report, rec: Record, rel: str, what: str) -> dict | None:
    if rec.error:
        report.error(rel, rec.error)
        return None
    if not isinstance(rec.data, dict):
        report.error(rel, f"expected a {what} mapping")
        return None
    return rec.data


def run(args) -> int:
    """CLI handler for ``slopcheck-dev validate``."""
    root = Path(args.root).resolve() if getattr(args, "root", None) else repo_root()
    changed = None
    if getattr(args, "changed_only", None):
        try:
            changed = changed_files(args.changed_only, root)
        except (RuntimeError, OSError) as exc:
            print(f"validate: cannot list changed files: {exc}", file=sys.stderr)
            return 2
    report = validate(root, changed=changed, regex_timing=not getattr(args, "no_regex_timing", False))
    stream = sys.stdout if report.ok else sys.stderr
    print(report.render(), file=stream)
    return 0 if report.ok else 1
