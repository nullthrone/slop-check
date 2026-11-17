"""Subcommands of ``slopcheck-dev`` owned by the evaluation package (docs/architecture.md 6.7).

``slopcheck_dev.cli`` calls :func:`register` with its subparsers object. Every leaf parser sets
``func=<callable(args) -> int>``.

Exit codes: 0 ok, 1 check failed (``budget check``), 2 usage or input error, 3 stopped
because a budget cap would have been exceeded (partial output is still written).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_BUDGET = 0, 1, 2, 3
DEFAULT_LEDGER = ".eval-out/budget/ledger.json"
DEFAULT_LOCK = ".eval-out/models/lock.json"
DEFAULT_CACHE = ".cache/openrouter"


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _env_default(name: str, fallback: str) -> str:
    return os.environ.get(name) or fallback


# ---------------------------------------------------------------------------
# shared option groups


def _add_budget_opts(p: argparse.ArgumentParser, default_kind: str | None) -> None:
    p.add_argument(
        "--ledger",
        default=_env_default("SLOPCHECK_LEDGER", DEFAULT_LEDGER),
        help="spend ledger JSON (env SLOPCHECK_LEDGER)",
    )
    p.add_argument(
        "--run-kind",
        choices=["pull_request", "scheduled", "conformance"],
        default=default_kind,
        help="which run cap of thresholds.yaml applies",
    )
    p.add_argument("--run-id", default=None, help="run identifier (default: GITHUB_RUN_ID or a timestamp)")
    p.add_argument("--max-call-usd", type=float, default=None, help="per-call cap in USD (default 0.25)")


def _add_model_opts(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--lock",
        default=_env_default("SLOPCHECK_MODELS_LOCK", DEFAULT_LOCK),
        help="models/lock.json; re-resolved live when missing or older than --max-lock-age days",
    )
    p.add_argument("--max-lock-age", type=float, default=8.0)
    p.add_argument(
        "--models",
        nargs="*",
        default=None,
        help="restrict to these families, ids, canonical slugs or selector keys",
    )
    p.add_argument("--cache-dir", default=_env_default("SLOPCHECK_LLM_CACHE", DEFAULT_CACHE))
    p.add_argument("--no-cache-read", action="store_true", help="ignore cached responses (still writes)")
    p.add_argument("--workers", type=int, default=4)


def _thresholds(args: argparse.Namespace) -> dict:
    from ._common import load_thresholds, repo_root

    root = Path(args.root) if getattr(args, "root", None) else repo_root()
    return load_thresholds(root)


def _budget(args: argparse.Namespace, thresholds: dict, run_kind: str) -> Any:
    from .budget import Budget, Ledger, load_caps

    caps = load_caps(thresholds, run_kind, args.max_call_usd)
    return Budget(Ledger(args.ledger), caps, args.run_id)


def _lock(args: argparse.Namespace) -> dict:
    from .models import load_lock, write_lock

    lock, notices = load_lock(args.lock, max_age_days=args.max_lock_age)
    for n in notices:
        _err(f"notice: {n}")
    if notices and args.lock:
        try:
            write_lock(args.lock, lock)
        except OSError as exc:
            _err(f"notice: cannot write refreshed lock {args.lock}: {exc}")
    return lock


def _client(args: argparse.Namespace, budget: Any) -> Any:
    from .openrouter import OpenRouterClient

    return OpenRouterClient(budget=budget, cache_dir=args.cache_dir, read_cache=not args.no_cache_read)


def _refresher(lock: dict) -> Any:
    from .models import refresh_entry

    def refresh(entry: dict, failed: set[str]) -> dict | None:
        try:
            return refresh_entry(lock, entry.get("key", ""), exclude_ids=failed)
        except Exception as exc:
            _err(f"notice: live re-resolution failed: {exc}")
            return None

    return refresh


# ---------------------------------------------------------------------------
# corpus


def cmd_fetch_human(args: argparse.Namespace) -> int:
    from .corpus import fetch_human, load_human_spec

    try:
        spec = load_human_spec(args.spec)
    except (OSError, ValueError) as exc:
        _err(f"error: {exc}")
        return EXIT_USAGE
    if args.seed is not None:
        spec["seed"] = args.seed
    if args.docs_scale != 1.0:
        for s in spec["sources"]:
            s.docs = max(1, round(s.docs * args.docs_scale))
    try:
        manifest = fetch_human(
            args.out, spec, strict_revision=args.strict_revision, only=args.sources, log=lambda m: _err(m)
        )
    except Exception as exc:
        _err(f"error: {exc}")
        return EXIT_USAGE
    print(
        json.dumps({"out": args.out, "counts": manifest["counts"], "notices": manifest["notices"]}, indent=2)
    )
    return EXIT_OK


def cmd_generate_ai(args: argparse.Namespace) -> int:
    from .corpus import generate_ai, load_human_docs, load_prompts
    from .models import role_entries
    from .openrouter import MissingApiKeyError

    thresholds = _thresholds(args)
    try:
        human = load_human_docs(args.human)
        prompts = load_prompts(args.prompts)
        lock = _lock(args)
    except Exception as exc:
        _err(f"error: {exc}")
        return EXIT_USAGE
    gens = role_entries(lock, "generators", args.models)
    if not gens:
        _err("error: no generator models resolved")
        return EXIT_USAGE
    budget = _budget(args, thresholds, args.run_kind or "scheduled")
    client = _client(args, budget)
    if not client.has_key:
        _err("notice: OPENROUTER_API_KEY is not set; only cached responses can be used")
    try:
        summary = generate_ai(
            human,
            args.out,
            gens,
            client,
            prompts=prompts,
            languages=args.languages,
            limit=args.limit,
            workers=args.workers,
            refresh=_refresher(lock),
            log=_err,
        )
    except MissingApiKeyError as exc:
        _err(f"error: {exc}")
        return EXIT_USAGE
    out = summary.to_dict()
    out["budget"] = budget.status()
    print(json.dumps(out, indent=2))
    return EXIT_BUDGET if summary.aborted else EXIT_OK


# ---------------------------------------------------------------------------
# measure


def cmd_measure(args: argparse.Namespace) -> int:
    from ._common import load_patterns, read_json, repo_root, write_json
    from .corpus import load_ai_docs, load_human_docs
    from .measure import measure, render_report
    from .models import role_entries

    root = Path(args.root) if args.root else repo_root()
    thresholds = _thresholds(args)
    try:
        patterns = load_patterns(root, "text")
        human = load_human_docs(args.human)
        slugs = None
        lock = None
        if args.lock_filter or args.llm:
            lock = _lock(args)
        if args.lock_filter and lock:
            slugs = {e.get("canonical_slug") for e in role_entries(lock, "generators")}
        ai = load_ai_docs(args.ai, slugs=slugs)
        previous = read_json(args.measurements) if args.measurements else None
    except Exception as exc:
        _err(f"error: {exc}")
        return EXIT_USAGE

    judges = None
    reason = None
    models_used: dict[str, list] = {
        "generators": sorted({d.get("canonical_slug") for d in ai if d.get("canonical_slug")}),
    }
    budget = None
    if args.llm:
        from .judge import make_judge

        run_kind = args.run_kind or ("pull_request" if args.split == "dev" else "scheduled")
        budget = _budget(args, thresholds, run_kind)
        client = _client(args, budget)
        entries = role_entries(lock or {}, "judges")
        if not client.has_key:
            reason = "OPENROUTER_API_KEY is not set"
        elif len(entries) < 2:
            reason = f"need two resolved judges, have {len(entries)}"
        elif not budget.allows(0.01):
            reason = "budget cap reached before the run"
        else:
            refresh = _refresher(lock or {})
            judges = [make_judge(client, e, refresh=refresh) for e in entries[:2]]
            models_used["judges"] = [e.get("canonical_slug") for e in entries[:2]]
        if reason:
            _err(f"notice: llm patterns skipped: {reason}")

    def progress(i: int, n: int) -> None:
        if i == n or i % 200 == 0:
            _err(f"measured {i}/{n} documents")

    try:
        result = measure(
            human,
            ai,
            patterns,
            thresholds,
            split=args.split,
            pattern_ids=args.patterns or None,
            previous_measurements=previous,
            judges=judges,
            llm_ai_sample=args.llm_ai_sample,
            models_used=models_used,
            llm_unavailable_reason=reason,
            progress=progress,
        )
    except ValueError as exc:
        _err(f"error: {exc}")
        return EXIT_USAGE
    if budget is not None:
        result["budget"] = budget.status()
    write_json(args.out, result)
    if args.report:
        try:
            from slopcheck_dev.status import derive
        except ImportError:
            derive = None
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(
            render_report(result, patterns, thresholds=thresholds, derive_fn=derive), encoding="utf-8"
        )
    n = len(result["patterns"])
    _err(f"wrote {args.out} ({n} patterns)")
    budget_hit = any("budget cap" in s for s in result.get("notices") or [])
    return EXIT_BUDGET if budget_hit else EXIT_OK


# ---------------------------------------------------------------------------
# conformance


def cmd_conformance(args: argparse.Namespace) -> int:
    from ._common import write_json
    from .conformance import load_cases, run_conformance
    from .models import role_entries

    thresholds = _thresholds(args)
    try:
        cases = load_cases(args.cases)
        if args.case:
            cases = [c for c in cases if c["id"] in set(args.case)]
        lock = _lock(args)
    except Exception as exc:
        _err(f"error: {exc}")
        return EXIT_USAGE
    entries = role_entries(lock, "conformance", args.models)
    if not entries:
        _err("error: no conformance models resolved")
        return EXIT_USAGE
    budget = _budget(args, thresholds, args.run_kind or "conformance")
    client = _client(args, budget)
    if not client.has_key:
        _err("error: OPENROUTER_API_KEY is not set")
        return EXIT_USAGE
    try:
        result = run_conformance(
            args.skill, entries, client, cases=cases, workers=args.workers, refresh=_refresher(lock), log=_err
        )
    except FileNotFoundError as exc:
        _err(f"error: {exc}")
        return EXIT_USAGE
    result["budget"] = budget.status()
    write_json(args.out, result)
    for m in result["models"]:
        s = m["summary"]
        _err(
            f"{m['id']}: passed {s['passed']}/{s['cases']}, recall {s['recall']}, precision {s['precision']}"
        )
    return EXIT_BUDGET if result["aborted"] else EXIT_OK


# ---------------------------------------------------------------------------
# budget


def cmd_budget_status(args: argparse.Namespace) -> int:
    from .budget import Budget, Ledger, ledger_summary, load_caps

    thresholds = _thresholds(args)
    ledger = Ledger(args.ledger)
    caps = load_caps(thresholds, args.run_kind or "scheduled", args.max_call_usd)
    status = Budget(ledger, caps, args.run_id).status()
    status["summary"] = ledger_summary(ledger)
    print(json.dumps(status, indent=2))
    return EXIT_OK


def cmd_budget_check(args: argparse.Namespace) -> int:
    from .budget import Budget, BudgetExceeded, Ledger, load_caps

    thresholds = _thresholds(args)
    caps = load_caps(thresholds, args.run_kind or "scheduled", args.max_call_usd)
    # the amount is a planned run total, so only the monthly and run caps apply
    caps = type(caps)(
        monthly_usd=caps.monthly_usd,
        run_usd=caps.run_usd,
        call_usd=max(caps.run_usd, args.amount),
        run_kind=caps.run_kind,
    )
    budget = Budget(Ledger(args.ledger), caps, args.run_id)
    try:
        budget.check(args.amount)
    except BudgetExceeded as exc:
        print(json.dumps({"ok": False, "reason": str(exc), **budget.status()}, indent=2))
        return EXIT_FAIL
    print(json.dumps({"ok": True, "amount_usd": args.amount, **budget.status()}, indent=2))
    return EXIT_OK


# ---------------------------------------------------------------------------
# models


def cmd_models_resolve(args: argparse.Namespace) -> int:
    from .models import (
        MODELS_URL,
        fetch_models,
        format_lock_summary,
        load_config,
        read_lock,
        resolve,
        write_lock,
    )

    try:
        config = load_config(args.config)
        previous = read_lock(args.previous) if args.previous and Path(args.previous).is_file() else None
        models = fetch_models(args.source)
    except Exception as exc:
        _err(f"error: cannot resolve models: {exc}")
        return EXIT_USAGE
    lock = resolve(config, models, previous=previous, source=args.source or MODELS_URL)
    if not any(lock["roles"].values()):
        _err("error: no selector resolved; lock not written")
        _err(format_lock_summary(lock))
        return EXIT_FAIL
    if args.out:
        write_lock(args.out, lock)
    else:
        print(json.dumps(lock, indent=2))
    _err(format_lock_summary(lock))
    if args.report:
        lines = ["# Model resolution", "", f"Resolved at {lock['resolved_at']}.", ""]
        lines += [f"- {c}" for c in lock["changes"]] or ["- no changes"]
        if lock["errors"]:
            lines += ["", "## Unresolved selectors", ""] + [f"- {e}" for e in lock["errors"]]
        Path(args.report).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return EXIT_OK


# ---------------------------------------------------------------------------
# registration


def _group_help(parser: argparse.ArgumentParser) -> Any:
    def show(_args: argparse.Namespace) -> int:
        parser.print_help(sys.stderr)
        return EXIT_USAGE

    return show


def register(subparsers: Any) -> None:
    """Add corpus, measure, conformance, budget and models to slopcheck-dev."""
    # corpus ---------------------------------------------------------------
    p_corpus = subparsers.add_parser("corpus", help="fetch the human corpus or generate the AI corpus")
    p_corpus.set_defaults(func=_group_help(p_corpus))
    csub = p_corpus.add_subparsers(dest="corpus_command", metavar="{fetch-human,generate-ai}")

    fh = csub.add_parser("fetch-human", help="fetch pinned pre-2022-11 human texts (local only)")
    fh.add_argument("--out", required=True, help="output directory (texts stay local, never commit)")
    fh.add_argument("--spec", default=None, help="corpus spec (default evals/corpus/human.yaml)")
    fh.add_argument("--seed", type=int, default=None)
    fh.add_argument("--sources", nargs="*", default=None, help="only these source ids")
    fh.add_argument("--docs-scale", type=float, default=1.0, help="scale per-source document counts")
    fh.add_argument("--strict-revision", action="store_true", help="fail when a dataset moved from its pin")
    fh.set_defaults(func=cmd_fetch_human)

    ga = csub.add_parser("generate-ai", help="generate topic-matched AI documents per generator model")
    ga.add_argument("--human", required=True, help="directory written by fetch-human")
    ga.add_argument("--out", required=True, help="AI corpus directory (<slug>/<lang>.jsonl.gz)")
    ga.add_argument("--prompts", default=None, help="prompts directory (default evals/corpus/prompts)")
    ga.add_argument("--languages", nargs="*", default=None)
    ga.add_argument("--limit", type=int, default=None, help="max documents per model and language")
    ga.add_argument("--root", default=None)
    _add_model_opts(ga)
    _add_budget_opts(ga, None)
    ga.set_defaults(func=cmd_generate_ai)

    # measure --------------------------------------------------------------
    me = subparsers.add_parser("measure", help="measure patterns on the corpora (measurements.json)")
    me.add_argument("--human", required=True)
    me.add_argument("--ai", required=True)
    me.add_argument("--split", choices=["dev", "holdout", "all"], required=True)
    me.add_argument("--patterns", nargs="*", default=None, help="pattern ids (default: all text patterns)")
    me.add_argument("--llm", action="store_true", help="judge kind: llm patterns with both resolved judges")
    me.add_argument(
        "--llm-ai-sample",
        type=int,
        default=None,
        help="judge at most N AI documents per language (cost control)",
    )
    me.add_argument("--out", required=True)
    me.add_argument("--report", default=None, help="also write a Markdown report")
    me.add_argument("--measurements", default=None, help="previous measurements.json for the catalog")
    me.add_argument(
        "--lock-filter",
        action="store_true",
        help="use only AI documents of generators in the current lock (admission metrics)",
    )
    me.add_argument("--root", default=None)
    _add_model_opts(me)
    _add_budget_opts(me, None)
    me.set_defaults(func=cmd_measure)

    # conformance ----------------------------------------------------------
    co = subparsers.add_parser("conformance", help="run the built skill on each conformance model")
    co.add_argument("--skill", required=True, help="built skill folder, e.g. dist/slop-check")
    co.add_argument("--out", required=True)
    co.add_argument("--cases", default=None, help="cases directory (default evals/conformance/cases)")
    co.add_argument("--case", nargs="*", default=None, help="only these case ids")
    co.add_argument("--root", default=None)
    _add_model_opts(co)
    _add_budget_opts(co, None)
    co.set_defaults(func=cmd_conformance)

    # budget ---------------------------------------------------------------
    bu = subparsers.add_parser("budget", help="spend ledger status and cap checks")
    bu.set_defaults(func=_group_help(bu))
    bsub = bu.add_subparsers(dest="budget_command", metavar="{status,check}")
    bs = bsub.add_parser("status", help="month total and caps")
    bs.add_argument("--root", default=None)
    _add_budget_opts(bs, None)
    bs.set_defaults(func=cmd_budget_status)
    bc = bsub.add_parser("check", help="exit 1 if spending AMOUNT now would cross a cap")
    bc.add_argument("--amount", type=float, required=True, help="planned spend in USD")
    bc.add_argument("--root", default=None)
    _add_budget_opts(bc, None)
    bc.set_defaults(func=cmd_budget_check)

    # models ---------------------------------------------------------------
    mo = subparsers.add_parser("models", help="resolve model selectors against OpenRouter")
    mo.set_defaults(func=_group_help(mo))
    msub = mo.add_subparsers(dest="models_command", metavar="{resolve}")
    mr = msub.add_parser("resolve", help="write models/lock.json from evals/models.yaml")
    mr.add_argument("--out", default=None, help="lock file to write (default: print to stdout)")
    mr.add_argument("--previous", default=None, help="previous lock for the change list")
    mr.add_argument("--config", default=None, help="selector file (default evals/models.yaml)")
    mr.add_argument("--source", default=None, help="model list URL or local JSON file (default: OpenRouter)")
    mr.add_argument("--report", default=None, help="also write a Markdown change report")
    mr.set_defaults(func=cmd_models_resolve)


def main(argv: list[str] | None = None) -> int:
    """Standalone entry for the eval subcommands (the real entry is slopcheck_dev.cli)."""
    parser = argparse.ArgumentParser(prog="slopcheck-dev")
    sub = parser.add_subparsers(dest="command")
    register(sub)
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help(sys.stderr)
        return EXIT_USAGE
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
