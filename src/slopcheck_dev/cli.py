"""``slopcheck-dev``: development and CI commands (docs/architecture.md section 6.7).

Subcommands defined here: ``validate``, ``check-fixtures``, ``build``, ``gate``.
The evaluation subcommands (``corpus``, ``measure``, ``conformance``, ``budget``,
``models``) come from :func:`slopcheck_dev.evals.cli.register` when that module is present.
Every subcommand sets ``func`` (``callable(args) -> int``) via ``set_defaults``.

Exit codes: 0 ok, 1 check failed, 2 usage or input error.
"""

from __future__ import annotations

import argparse
import sys

from . import __version__

EXIT_USAGE = 2


def _add_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--root",
        default=None,
        help="repository root (default: env SLOPCHECK_ROOT or the nearest parent with governance/)",
    )


def _validate(args: argparse.Namespace) -> int:
    from .validate import run

    return run(args)


def _check_fixtures(args: argparse.Namespace) -> int:
    from .fixtures import run

    return run(args)


def _build(args: argparse.Namespace) -> int:
    from .build import run

    return run(args)


def _gate(args: argparse.Namespace) -> int:
    from .gate import run

    return run(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="slopcheck-dev", description="slop-check development tooling")
    parser.add_argument("--version", action="version", version=f"slopcheck-dev {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    p = sub.add_parser("validate", help="validate patterns and sources against schema and rules")
    p.add_argument(
        "--changed-only",
        metavar="BASE_REF",
        default=None,
        help="limit per-file checks to files changed against BASE_REF (cross-file rules always run)",
    )
    p.add_argument("--no-regex-timing", action="store_true", help="skip the adversarial regex timing run")
    _add_root(p)
    p.set_defaults(func=_validate)

    p = sub.add_parser("check-fixtures", help="run pattern examples and test texts through the engine")
    p.add_argument("ids", nargs="*", metavar="ID", help="pattern ids (default: all)")
    _add_root(p)
    p.set_defaults(func=_check_fixtures)

    p = sub.add_parser("build", help="compile the catalog and build the skill package")
    p.add_argument("--out", default="dist", help="output directory (default: dist)")
    p.add_argument("--measurements", default=None, metavar="PATH", help="measurements.json from branch data")
    p.add_argument("--version", default=None, help="catalog version (default: YYYY.MM.DD)")
    _add_root(p)
    p.set_defaults(func=_build)

    p = sub.add_parser("gate", help="apply pull request admission rules to a dev-split measurement")
    p.add_argument("--measure", required=True, metavar="FILE", help="output of `measure --split dev`")
    p.add_argument("--patterns", nargs="*", default=[], metavar="ID", help="pattern ids to gate")
    p.add_argument("--current", default=None, metavar="FILE", help="current measurements.json (branch data)")
    p.add_argument("--summary", default=None, metavar="FILE", help="append the Markdown summary to FILE")
    _add_root(p)
    p.set_defaults(func=_gate)

    try:
        from slopcheck_dev.evals.cli import register
    except ImportError:
        register = None
    if register is not None:
        register(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run ``slopcheck-dev`` and return the exit code."""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else EXIT_USAGE
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help(sys.stderr)
        return EXIT_USAGE
    return int(func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
