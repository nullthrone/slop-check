"""Command line interface (architecture section 4.7).

    slopcheck audit [PATH ...|-] [--lang de|en|auto] [--context ...] [--format md|json]
                    [--report-lang en|de] [--fail-on yellow|red] [--catalog PATH]
                    [--llm] [--llm-model MODEL]
    slopcheck patterns [--modality text|image] [--status ...] [--format md|json] [--catalog PATH]
    slopcheck version

Exit codes: 0 ok (or verdict below ``--fail-on``), 1 verdict reached ``--fail-on``,
2 usage or input error.
"""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .catalog import CatalogError, load_catalog, select_patterns
from .engine import analyze
from .llm import KEY_ENV, LOCK_ENV, MODEL_ENV, make_llm_judge, resolve_model
from .report import render_json, render_markdown, render_pattern_list

CONTEXTS = ("default", "informal", "technical", "academic", "marketing")
VERDICT_RANK = {"GREEN": 0, "YELLOW": 1, "RED": 2}
FAIL_ON_RANK = {"yellow": 1, "red": 2}

EXIT_OK, EXIT_FAIL, EXIT_USAGE = 0, 1, 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="slopcheck", description="Detect generic writing patterns in texts."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="analyze texts and print a report")
    audit.add_argument(
        "paths", nargs="*", metavar="PATH", help="files to analyze; '-' or nothing reads stdin"
    )
    audit.add_argument("--lang", choices=("de", "en", "auto"), default="auto")
    audit.add_argument("--context", choices=CONTEXTS, default="default")
    audit.add_argument("--format", choices=("md", "json"), default="md")
    audit.add_argument("--report-lang", choices=("en", "de"), default="en")
    audit.add_argument("--fail-on", choices=("yellow", "red"), default=None)
    audit.add_argument("--catalog", default=None, help="catalog.json path (default: bundled catalog)")
    audit.add_argument("--llm", action="store_true", help=f"evaluate llm patterns via OpenRouter ({KEY_ENV})")
    audit.add_argument("--llm-model", default=None, help=f"OpenRouter model id (default: {MODEL_ENV})")
    audit.set_defaults(func=cmd_audit)

    patterns = sub.add_parser("patterns", help="list catalog patterns")
    patterns.add_argument("--modality", choices=("text", "image"), default=None)
    patterns.add_argument("--status", choices=("core", "candidate", "observation", "fading"), default=None)
    patterns.add_argument("--format", choices=("md", "json"), default="md")
    patterns.add_argument("--catalog", default=None)
    patterns.set_defaults(func=cmd_patterns)

    version = sub.add_parser("version", help="print engine and catalog version")
    version.add_argument("--catalog", default=None)
    version.set_defaults(func=cmd_version)
    return parser


def _error(message: str) -> int:
    print(f"slopcheck: {message}", file=sys.stderr)
    return EXIT_USAGE


def _read_inputs(paths: list[str]) -> list[tuple[str, str]]:
    """Read all inputs as UTF-8. Raises OSError or UnicodeDecodeError."""
    inputs = []
    for path in paths or ["-"]:
        if path == "-":
            data = (
                sys.stdin.buffer.read() if hasattr(sys.stdin, "buffer") else sys.stdin.read().encode("utf-8")
            )
            inputs.append(("stdin", data.decode("utf-8-sig")))
        else:
            with open(path, encoding="utf-8-sig") as handle:
                inputs.append((path, handle.read()))
    return inputs


def _make_judge(args: argparse.Namespace):
    """Return (judge, error message). Without an API key the llm patterns stay unevaluated."""
    if not args.llm:
        return None, None
    if not os.environ.get(KEY_ENV):
        print(f"slopcheck: warning: {KEY_ENV} is not set; llm patterns are not evaluated", file=sys.stderr)
        return None, None
    model = resolve_model(args.llm_model)
    if not model:
        hint = f"pass --llm-model, set {MODEL_ENV}, or point {LOCK_ENV} to a models lockfile"
        return None, f"--llm needs a model: {hint}"
    return make_llm_judge(model), None


def _write(text: str) -> None:
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(text.encode("utf-8"))


def cmd_audit(args: argparse.Namespace) -> int:
    try:
        catalog = load_catalog(args.catalog)
    except CatalogError as exc:
        return _error(str(exc))
    judge, problem = _make_judge(args)
    if problem:
        return _error(problem)
    try:
        inputs = _read_inputs(args.paths)
    except (OSError, UnicodeDecodeError) as exc:
        return _error(f"cannot read input: {exc}")
    lang = None if args.lang == "auto" else args.lang
    results = []
    for source, text in inputs:
        try:
            result = analyze(text, catalog, lang=lang, context=args.context, llm_judge=judge)
        except ValueError as exc:
            return _error(f"catalog error: {exc}")
        result["source"] = source
        results.append(result)
    if args.format == "json":
        _write(render_json(results[0] if len(results) == 1 else results))
    else:
        reports = [render_markdown(r, title=r["source"], lang=args.report_lang) for r in results]
        _write("\n---\n\n".join(reports))
    if args.fail_on:
        worst = max(VERDICT_RANK[r["verdict"]] for r in results)
        if worst >= FAIL_ON_RANK[args.fail_on]:
            return EXIT_FAIL
    return EXIT_OK


def cmd_patterns(args: argparse.Namespace) -> int:
    try:
        catalog = load_catalog(args.catalog)
    except CatalogError as exc:
        return _error(str(exc))
    patterns = select_patterns(catalog, modality=args.modality, status=args.status)
    _write(render_json(patterns) if args.format == "json" else render_pattern_list(patterns))
    return EXIT_OK


def cmd_version(args: argparse.Namespace) -> int:
    line = f"slopcheck {__version__}"
    try:
        catalog = load_catalog(args.catalog)
        line += f" (catalog {catalog.get('catalog_version', 'unknown')}, {len(catalog['patterns'])} patterns)"
    except CatalogError:
        line += " (no catalog found)"
    _write(line + "\n")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return the exit code."""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else EXIT_USAGE
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
