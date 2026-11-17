"""slopcheck-dev entry point: subcommands, evals registration, exit codes."""

from __future__ import annotations

import subprocess
import sys

from slopcheck_dev import __version__
from slopcheck_dev.cli import build_parser, main

OWN = {"validate", "check-fixtures", "build", "gate", "guard"}
EVALS = {"corpus", "measure", "conformance", "budget", "models"}


def subcommands(parser) -> set[str]:
    action = next(a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction")
    return set(action.choices)


def test_no_command_prints_help_and_returns_2(capsys):
    assert main([]) == 2
    assert "usage: slopcheck-dev" in capsys.readouterr().err


def test_unknown_command_returns_2(capsys):
    assert main(["frobnicate"]) == 2
    assert "invalid choice" in capsys.readouterr().err


def test_version(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"slopcheck-dev {__version__}"


def test_evals_subcommands_are_registered():
    names = subcommands(build_parser())
    assert names >= OWN
    assert names >= EVALS


def test_cli_works_without_evals_module(monkeypatch):
    monkeypatch.setitem(sys.modules, "slopcheck_dev.evals.cli", None)  # import raises ImportError
    assert subcommands(build_parser()) == OWN


def test_every_subcommand_sets_func():
    parser = build_parser()
    action = next(a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction")
    for name, sub in action.choices.items():
        assert callable(sub.get_default("func")), name


def test_validate_changed_only_with_unknown_ref(repo, capsys):
    subprocess.run(["git", "init", "-q"], cwd=repo.root, check=True)
    code = main(["validate", "--root", str(repo.root), "--no-regex-timing", "--changed-only", "no-such-ref"])
    assert code == 2
    assert "cannot list changed files" in capsys.readouterr().err


def test_module_entry_point(repo):
    proc = subprocess.run(
        [sys.executable, "-m", "slopcheck_dev", "validate", "--root", str(repo.root), "--no-regex-timing"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "0 error(s)" in proc.stdout
