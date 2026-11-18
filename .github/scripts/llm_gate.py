"""LLM gate for pull requests (docs/architecture.md section 8, workflow llm-eval.yml).

Runs only trusted code from the default branch. Files of the pull request are fetched
through the GitHub REST API at the head commit and handled as data: size-limited,
parsed with ``yaml.safe_load`` and validated with ``slopcheck-dev validate`` on a copy of
the trusted checkout in which only ``patterns/`` and ``sources/`` change.

Subcommands (run in this order by the workflow):

    prepare   find the pull request, fetch its pattern and source files, build the candidate
              copy, list changed ``kind: llm`` patterns (writes prepare.json)
    status    post the commit status ``llm-gate`` on the head commit
    examples  judge every example of the changed llm patterns with both resolved judges
              (leave-one-out: the example under test is removed from the prompt)
    decide    combine validation, example results and the dev-split measurement
              (``slopcheck-dev measure --llm``) into the final status, a job summary and one
              pull request comment that is updated in place

Admission rules: ``governance/thresholds.yaml`` (``admission.candidate.pr_gate`` for
candidates, ``meets_core`` for patterns that are effective core). Missing key or exhausted
monthly budget (section 6.5): candidates pass with a notice, effective-core llm patterns fail.
Everything else that leaves a pattern unchecked fails it, including a run that uses up its
own per-pull-request cap, so a pull request cannot buy a notice with an oversized rubric.

Environment: GITHUB_TOKEN or GH_TOKEN, GITHUB_REPOSITORY, GITHUB_API_URL, HEAD_SHA,
HEAD_REPO, RUN_URL, OPENROUTER_API_KEY (examples only), GITHUB_STEP_SUMMARY, GITHUB_OUTPUT.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

CONTEXT = "llm-gate"
MARKER = "<!-- slop-check:llm-gate -->"
MAX_FILE_BYTES = 256 * 1024
MAX_DATA_FILES = 200
MAX_PAGES = 30
#: The pull request files endpoint lists at most 3000 files; a longer list is cut off.
MAX_PR_FILES = 3000
#: Budget caps that the pull request's own size can exhaust (per run and per call), as
#: opposed to the monthly cap that other runs exhaust.
OWN_CAPS = ("run", "call")
DATA_PATH = re.compile(
    r"^(?:patterns/(?:text|image|web|code|audio|video)/[a-z0-9]+(?:-[a-z0-9]+)*\.yaml"
    r"|sources/[a-z0-9]+(?:-[a-z0-9]+)*\.yaml)$"
)
COPY_IGNORE = (".git", ".venv", "venv", "__pycache__", ".cache", ".corpus", ".eval-out", "dist")


# ---------------------------------------------------------------------------
# GitHub REST


def _token() -> str:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not set")
    return token


def api(path: str, *, method: str = "GET", body: Any = None, raw: bool = False, limit: int | None = None):
    base = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(  # noqa: S310 - fixed https API base
        base + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {_token()}",
            "Accept": "application/vnd.github.raw+json" if raw else "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "slop-check-llm-gate",
            **({"Content-Type": "application/json"} if data else {}),
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        payload = response.read(limit + 1) if limit else response.read()
    if raw:
        return payload
    return json.loads(payload) if payload else None


def paged(path: str) -> list:
    sep = "&" if "?" in path else "?"
    items: list = []
    for page in range(1, MAX_PAGES + 1):
        batch = api(f"{path}{sep}per_page=100&page={page}") or []
        items.extend(batch)
        if len(batch) < 100:
            break
    return items


def find_pull_request(repo: str, sha: str) -> dict | None:
    """The open pull request whose head is ``sha`` (works for forks, where the event lists none)."""
    try:
        for pr in api(f"/repos/{repo}/commits/{sha}/pulls") or []:
            if pr.get("state") == "open" and (pr.get("head") or {}).get("sha") == sha:
                return pr
    except urllib.error.HTTPError:
        pass
    for pr in paged(f"/repos/{repo}/pulls?state=open"):
        if (pr.get("head") or {}).get("sha") == sha:
            return pr
    return None


def post_status(state: str, description: str) -> None:
    repo, sha = os.environ["GITHUB_REPOSITORY"], os.environ["HEAD_SHA"]
    body = {"state": state, "context": CONTEXT, "description": description[:140]}
    if os.environ.get("RUN_URL"):
        body["target_url"] = os.environ["RUN_URL"]
    api(f"/repos/{repo}/statuses/{sha}", method="POST", body=body)
    print(f"{CONTEXT}: {state}: {description}")


def upsert_comment(pr_number: int, text: str) -> None:
    repo = os.environ["GITHUB_REPOSITORY"]
    body = f"{MARKER}\n{text}"
    for comment in paged(f"/repos/{repo}/issues/{pr_number}/comments"):
        user = (comment.get("user") or {}).get("login")
        if MARKER in (comment.get("body") or "") and user == "github-actions[bot]":
            api(f"/repos/{repo}/issues/comments/{comment['id']}", method="PATCH", body={"body": body})
            return
    api(f"/repos/{repo}/issues/{pr_number}/comments", method="POST", body={"body": body})


# ---------------------------------------------------------------------------
# helpers


def write_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")


def append_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text)
    else:
        print(text)


def read_json(path: str | None) -> dict | None:
    if not path or not Path(path).is_file():
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def load_pattern(candidate: Path, pid: str) -> dict:
    from slopcheck_dev.patterns import load_yaml

    return load_yaml(candidate / "patterns" / "text" / f"{pid}.yaml")


def fmt(x: float | None) -> str:
    return "-" if x is None else f"{x:.2f}"


# ---------------------------------------------------------------------------
# prepare


def cmd_prepare(args: argparse.Namespace) -> int:
    import yaml

    repo = os.environ["GITHUB_REPOSITORY"]
    sha = os.environ["HEAD_SHA"]
    head_repo = os.environ.get("HEAD_REPO") or repo
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {"pr": None, "errors": [], "ignored": [], "data_files": [], "llm_ids": []}
    result["skipped"] = {}

    pr = find_pull_request(repo, sha)
    if pr is None:
        print(f"no open pull request has head {sha}; nothing to gate")
        (out / "prepare.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        write_output("pr", "")
        return 0
    result["pr"] = pr["number"]
    result["pr_url"] = pr.get("html_url")
    write_output("pr", str(pr["number"]))  # early, so a later failure can still be reported

    files = paged(f"/repos/{repo}/pulls/{pr['number']}/files")
    # The file list belongs to the pull request as it is now, the status to ``sha``. If the
    # head moved in between, the list may not describe ``sha`` (a force-push back to ``sha``
    # would then reuse a status computed from another commit's files): fail instead.
    head_now = ((api(f"/repos/{repo}/pulls/{pr['number']}") or {}).get("head") or {}).get("sha")
    if head_now != sha:
        result["errors"].append("the pull request head moved while its files were read; push again")
    if len(files) >= MAX_PR_FILES:
        result["errors"].append(f"{len(files)} changed files; GitHub lists at most {MAX_PR_FILES}, split it")
    candidate = Path(args.candidate)
    if candidate.exists():
        shutil.rmtree(candidate)
    shutil.copytree(Path.cwd(), candidate, ignore=shutil.ignore_patterns(*COPY_IGNORE))

    changed_patterns: list[str] = []
    data_count = 0
    touched = 0
    for f in files:
        name, status = f.get("filename", ""), f.get("status", "")
        previous = f.get("previous_filename")
        in_data = name.startswith(("patterns/", "sources/"))
        if in_data or (previous or "").startswith(("patterns/", "sources/")):
            touched += 1
        if previous and DATA_PATH.match(previous):
            (candidate / previous).unlink(missing_ok=True)
        if not in_data:
            continue
        if not DATA_PATH.match(name):
            result["ignored"].append(name)
            continue
        target = candidate / name
        if status == "removed":
            target.unlink(missing_ok=True)
            continue
        data_count += 1
        if data_count > MAX_DATA_FILES:
            result["errors"].append(f"more than {MAX_DATA_FILES} pattern or source files changed")
            break
        quoted = urllib.parse.quote(name)
        ref = urllib.parse.quote(sha)
        content = api(f"/repos/{head_repo}/contents/{quoted}?ref={ref}", raw=True, limit=MAX_FILE_BYTES)
        if len(content) > MAX_FILE_BYTES:
            result["errors"].append(f"{name}: larger than {MAX_FILE_BYTES // 1024} KiB")
            continue
        try:
            text = content.decode("utf-8")
            parsed = yaml.safe_load(text)
        except (UnicodeDecodeError, yaml.YAMLError) as exc:
            result["errors"].append(f"{name}: not valid UTF-8 YAML ({type(exc).__name__})")
            continue
        if not isinstance(parsed, dict):
            result["errors"].append(f"{name}: top level is not a mapping")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        result["data_files"].append(name)
        if name.startswith("patterns/text/"):
            changed_patterns.append(name[len("patterns/text/") : -len(".yaml")])

    for pid in sorted(set(changed_patterns)):
        try:
            pattern = load_pattern(candidate, pid)
        except Exception as exc:
            result["errors"].append(f"{pid}: {exc}")
            continue
        kind = (pattern.get("detector") or {}).get("kind")
        if kind != "llm":
            continue
        if pattern.get("status") == "observation":
            result["skipped"][pid] = "observation (not scored, no gate)"
            continue
        result["llm_ids"].append(pid)
    if result["errors"]:
        result["llm_ids"] = []  # the gate fails on these errors; spend no budget on judging

    (out / "prepare.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    write_output("data_files", str(touched))
    write_output("llm_ids", " ".join(result["llm_ids"]))
    print(
        f"pull request #{pr['number']}: {len(result['data_files'])} data files, "
        f"llm patterns: {' '.join(result['llm_ids']) or 'none'}"
    )
    return 0


# ---------------------------------------------------------------------------
# status


def cmd_status(args: argparse.Namespace) -> int:
    post_status(args.state, args.description)
    return 0


# ---------------------------------------------------------------------------
# examples


def _without_example(pattern: dict, lang: str, label: str, index: int) -> dict:
    trimmed = copy.deepcopy(pattern)
    items = trimmed["realizations"][lang]["examples"][label]
    del items[index]
    return trimmed


def cmd_examples(args: argparse.Namespace) -> int:
    from slopcheck_dev.evals.budget import Budget, BudgetExceeded, Ledger, load_caps
    from slopcheck_dev.evals.judge import make_judge
    from slopcheck_dev.evals.models import load_lock, role_entries
    from slopcheck_dev.evals.openrouter import OpenRouterClient
    from slopcheck_dev.patterns import load_thresholds

    candidate = Path(args.candidate)
    result: dict[str, Any] = {"available": False, "reason": None, "patterns": {}, "notices": []}

    def finish() -> int:
        Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")
        write_output("examples_ok", "true" if result["available"] and result.get("all_pass") else "false")
        return 0

    if not os.environ.get("OPENROUTER_API_KEY"):
        result["reason"] = "OPENROUTER_API_KEY is not set"
        return finish()
    thresholds = load_thresholds(candidate)
    try:
        lock, notices = load_lock(args.lock)
    except Exception as exc:
        result["reason"] = f"no model lock: {exc}"
        return finish()
    result["notices"].extend(notices)
    entries = role_entries(lock, "judges")[:2]
    if len(entries) < 2:
        result["reason"] = f"need two resolved judges, have {len(entries)}"
        return finish()
    budget = Budget(Ledger(args.ledger), load_caps(thresholds, "pull_request"))
    if not budget.allows(0.01):
        result["reason"] = "budget cap reached before the run"
        return finish()
    client = OpenRouterClient(budget=budget, cache_dir=args.cache_dir)
    judges = [make_judge(client, e) for e in entries]
    result["judges"] = [e.get("canonical_slug") or e.get("id") for e in entries]
    result["available"] = True

    pr_gate = ((thresholds.get("admission") or {}).get("candidate") or {}).get("pr_gate") or {}
    min_recall = float(pr_gate.get("llm_min_positive_recall", 0.8))
    max_negative = float(pr_gate.get("llm_max_negative_flag_rate", 0.2))
    result["rules"] = {"min_positive_recall": min_recall, "max_negative_flag_rate": max_negative}
    all_pass = True
    try:
        for pid in args.ids:
            pattern = load_pattern(candidate, pid)
            row: dict[str, Any] = {"positive": [0, 0], "negative": [0, 0], "errors": [], "misses": []}
            for lang, real in sorted((pattern.get("realizations") or {}).items()):
                examples = (real or {}).get("examples") or {}
                judge_lang = "und" if lang == "*" else lang
                for label in ("positive", "negative"):
                    for i, text in enumerate(examples.get(label) or []):
                        probe = _without_example(pattern, lang, label, i)
                        try:
                            flags = [bool(j(text, [probe], judge_lang).get(pid)) for j in judges]
                        except BudgetExceeded:
                            raise
                        except Exception as exc:
                            row["errors"].append(f"{lang} {label} {i + 1}: {type(exc).__name__}")
                            continue
                        row[label][1] += 1
                        flagged = all(flags)
                        row[label][0] += int(flagged)
                        if flagged != (label == "positive"):
                            row["misses"].append(f"{lang} {label} example {i + 1}")
            pos_k, pos_n = row["positive"]
            neg_k, neg_n = row["negative"]
            row["recall"] = pos_k / pos_n if pos_n else None
            row["negative_rate"] = neg_k / neg_n if neg_n else None
            row["pass"] = (
                not row["errors"]
                and row["recall"] is not None
                and row["recall"] >= min_recall
                and (row["negative_rate"] or 0.0) <= max_negative
            )
            all_pass = all_pass and row["pass"]
            result["patterns"][pid] = row
    except BudgetExceeded as exc:
        result["available"] = False
        result["reason"] = f"budget cap reached during the example checks ({exc})"
        result["budget_cap"] = exc.cap
    result["all_pass"] = all_pass
    result["budget"] = budget.status()
    return finish()


# ---------------------------------------------------------------------------
# decide


def _fpr_reasons(entry: dict, max_fpr: float) -> list[str]:
    reasons = []
    fpr = entry.get("fpr_human")
    if fpr is None:
        reasons.append("no human documents measured")
    elif fpr > max_fpr:
        reasons.append(f"fpr_human {fpr:.3f} above {max_fpr:.3f}")
    for lang, pl in sorted((entry.get("per_language") or {}).items()):
        if pl.get("fpr_human") is not None and pl["fpr_human"] > max_fpr:
            reasons.append(f"fpr_human ({lang}) {pl['fpr_human']:.3f} above {max_fpr:.3f}")
    return reasons


def _own_budget_exhausted(examples: dict | None, measure: dict | None, measure_state: str) -> bool:
    """True if this run stopped at its own per-run or per-call cap rather than the monthly cap.

    Candidates pass without a check only when the key is missing or the monthly budget is used
    up (section 6.5). A pull request whose rubric or examples are large enough to use up its
    own cap must not pass that way.
    """
    if (examples or {}).get("budget_cap") in OWN_CAPS:
        return True
    if measure_state != "budget":
        return False
    b = (measure or {}).get("budget") or {}
    try:
        run_left = float(b["run_cap_usd"]) - float(b["run_total_usd"])
        month_left = float(b["monthly_cap_usd"]) - float(b["month_total_usd"])
    except (KeyError, TypeError, ValueError):
        return True  # cannot tell which cap stopped the run, so it earns no notice
    return run_left < month_left


def evaluate(
    prepare: dict,
    validate_ok: bool,
    examples: dict | None,
    measure: dict | None,
    measure_state: str,
    current: dict | None,
    thresholds: dict,
    patterns: dict[str, dict],
) -> tuple[str, str, list[dict], list[str]]:
    """Return (state, description, rows, notes). Pure function, unit-testable."""
    from slopcheck_dev.status import derive, measurement_for

    notes: list[str] = list(prepare.get("errors") or [])
    if not validate_ok:
        notes.append("the changed pattern or source files do not validate (see the ci run)")
    ids = list(prepare.get("llm_ids") or [])
    pr_gate = ((thresholds.get("admission") or {}).get("candidate") or {}).get("pr_gate") or {}
    max_fpr = float(pr_gate.get("max_fpr_human", 0.15))
    own_budget = _own_budget_exhausted(examples, measure, measure_state)
    rows: list[dict] = []
    for pid in ids:
        pattern = patterns[pid]
        now, _w, _src = derive(pattern, measurement_for(current, pid), thresholds, check_hash=False)
        core_rule = now == "core" or pattern.get("status") == "core"
        row = {"id": pid, "rule": "core" if core_rule else "candidate", "result": "pass", "reasons": []}
        row["notices"] = []
        rows.append(row)

        def unavailable(reason: str, row: dict = row, core_rule: bool = core_rule, own: bool = False) -> None:
            if core_rule:
                row["result"] = "fail"
                row["reasons"].append(f"{reason}; effective-core llm patterns cannot pass without a check")
            elif own:
                row["result"] = "fail"
                row["reasons"].append(
                    f"{reason}; candidates pass without a check only when the key is missing or the "
                    "monthly budget is used up (shorten the rubric and examples if the run cap stopped it)"
                )
            else:
                row["notices"].append(f"{reason}; candidates pass with this notice (weight 0)")

        ex = (examples or {}).get("patterns", {}).get(pid)
        if not examples or not examples.get("available") or ex is None:
            reason = (examples or {}).get("reason") or "example checks did not run"
            unavailable(reason, own=(examples or {}).get("budget_cap") in OWN_CAPS)
            continue
        row["recall"], row["negative_rate"] = ex.get("recall"), ex.get("negative_rate")
        if ex.get("errors"):
            row["result"] = "fail"
            row["reasons"].append(f"{len(ex['errors'])} judge calls failed; re-run the workflow")
        rules = examples.get("rules") or {}
        if ex.get("recall") is None or ex["recall"] < rules.get("min_positive_recall", 0.8):
            row["result"] = "fail"
            row["reasons"].append(f"positive examples recall {fmt(ex.get('recall'))}")
        if (ex.get("negative_rate") or 0.0) > rules.get("max_negative_flag_rate", 0.2):
            row["result"] = "fail"
            row["reasons"].append(f"negative examples flagged {fmt(ex.get('negative_rate'))}")
        if ex.get("misses"):
            row["notices"].append("misjudged: " + ", ".join(ex["misses"][:8]))
        if row["result"] == "fail":
            continue
        if measure_state == "no-corpus":
            row["notices"].append("dev-split fpr not measured: no corpus on branch data yet")
            continue
        entry = measurement_for(measure, pid)
        if entry is None:
            measure_notes = "; ".join((measure or {}).get("notices") or []) or measure_state
            # judges answered the examples, so only an exhausted monthly budget earns a notice;
            # errors, failed judge calls on the corpus and the run's own cap fail the pattern
            own = measure_state != "budget" or own_budget
            unavailable(f"dev-split measurement missing ({measure_notes})", own=own)
            continue
        row["fpr_human"], row["lift"] = entry.get("fpr_human"), entry.get("lift")
        if core_rule:
            if not entry.get("meets_core"):
                row["result"] = "fail"
                row["reasons"].append("does not meet the core criteria on the dev split")
        else:
            reasons = _fpr_reasons(entry, max_fpr)
            if reasons:
                row["result"] = "fail"
                row["reasons"].extend(reasons)

    failed = [r for r in rows if r["result"] == "fail"]
    if notes or failed:
        state = "failure"
        if failed:
            description = f"{len(failed)} of {len(rows)} llm-kind patterns failed"
        else:
            description = notes[0]
    elif not rows:
        state, description = "success", "no llm-kind patterns changed"
    else:
        noticed = sum(1 for r in rows if r["notices"])
        description = f"{len(rows)} llm-kind patterns passed"
        if noticed:
            description += f" ({noticed} with notices)"
        state = "success"
    return state, description, rows, notes


def render(state: str, description: str, rows: list[dict], notes: list[str], prepare: dict) -> str:
    lines = ["## LLM gate", "", f"Result: {state}, {description}.", ""]
    for note in notes:
        lines.append(f"Error: {note}")
    if notes:
        lines.append("")
    if rows:
        lines += [
            "| Pattern | Rule | Example recall | Negatives flagged | fpr_human (dev) | Result |",
            "|---|---|---|---|---|---|",
        ]
        for r in rows:
            lines.append(
                f"| `{r['id']}` | {r['rule']} | {fmt(r.get('recall'))} | {fmt(r.get('negative_rate'))} "
                f"| {fmt(r.get('fpr_human'))} | {r['result']} |"
            )
        details = [r for r in rows if r["reasons"] or r["notices"]]
        if details:
            lines += ["", "Details:", ""]
            for r in details:
                lines.append(f"- `{r['id']}`: " + "; ".join(r["reasons"] + r["notices"]))
    skipped = prepare.get("skipped") or {}
    if skipped:
        lines += ["", "Not gated: " + ", ".join(f"`{k}` ({v})" for k, v in sorted(skipped.items()))]
    lines.append("")
    return "\n".join(lines)


def cmd_decide(args: argparse.Namespace) -> int:
    from slopcheck_dev.patterns import load_thresholds

    prepare = read_json(args.prepare) or {}
    if not prepare.get("pr"):
        print("no pull request; nothing to decide")
        return 0
    candidate = Path(args.candidate)
    thresholds = load_thresholds(candidate)
    patterns = {pid: load_pattern(candidate, pid) for pid in prepare.get("llm_ids") or []}
    state, description, rows, notes = evaluate(
        prepare,
        args.validate != "failed",
        read_json(args.examples),
        read_json(args.measure),
        args.measure_state,
        read_json(args.current),
        thresholds,
        patterns,
    )
    text = render(state, description, rows, notes, prepare)
    append_summary(text)
    post_status(state, description)
    if rows:
        upsert_comment(int(prepare["pr"]), text + f"\n[Workflow run]({os.environ.get('RUN_URL', '')})\n")
    return 0


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LLM gate for pull requests")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("prepare")
    p.add_argument("--candidate", required=True, help="directory for the candidate repository copy")
    p.add_argument("--out", required=True, help="directory for prepare.json")
    p.set_defaults(func=cmd_prepare)

    p = sub.add_parser("status")
    p.add_argument("--state", required=True, choices=["pending", "success", "failure", "error"])
    p.add_argument("--description", required=True)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("examples")
    p.add_argument("--candidate", required=True)
    p.add_argument("--lock", default=None, help="models/lock.json (re-resolved live when missing or stale)")
    p.add_argument("--ledger", required=True)
    p.add_argument("--cache-dir", default=".cache/openrouter")
    p.add_argument("--out", required=True)
    p.add_argument("ids", nargs="+")
    p.set_defaults(func=cmd_examples)

    p = sub.add_parser("decide")
    p.add_argument("--candidate", required=True)
    p.add_argument("--prepare", required=True)
    p.add_argument("--validate", choices=["ok", "failed", "skipped"], default="skipped")
    p.add_argument("--examples", default=None)
    p.add_argument("--measure", default=None)
    p.add_argument(
        "--measure-state",
        default="not-run",
        help="ok, budget, no-corpus, no-key, error or not-run (how the measure step ended)",
    )
    p.add_argument("--current", default=None, help="measurements.json from branch data")
    p.set_defaults(func=cmd_decide)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except urllib.error.HTTPError as exc:
        print(f"llm_gate: GitHub API error {exc.code} for {exc.url}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
