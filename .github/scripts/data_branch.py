"""Read and write the bot-owned branches ``data`` and ``dist`` from GitHub Actions.

Both branches are orphans that only workflows write (docs/architecture.md section 2).

    python .github/scripts/data_branch.py checkout --branch data --dir DIR
        Copy the branch tree into DIR (a plain directory, no git metadata). DIR is created
        empty when the branch does not exist yet. Writes ``present=true|false`` to
        $GITHUB_OUTPUT when that variable is set.

    python .github/scripts/data_branch.py publish --branch data --source DIR --path P ... \
            [--ledger budget/ledger.json] [--replace] --message MSG
        Commit files from DIR onto the current tip of the branch and push. Each ``--path``
        (file or directory, relative to DIR) replaces the same path on the branch.
        ``--ledger`` merges the spend ledger instead of replacing it, so runs that spend in
        parallel keep each other's entries. ``--replace`` makes the branch tree equal to DIR.
        A rejected push (someone else pushed first) is retried on the new tip.

    python .github/scripts/data_branch.py merge-ledger --base FILE --run FILE --out FILE
        The ledger merge on its own.

Standard library only. Runs from the root of a checkout whose ``origin`` remote can push.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
ATTEMPTS = 5


def git(*args: str, env: dict | None = None, check: bool = True, binary: bool = False):
    result = subprocess.run(  # noqa: S603 - fixed git argv, no shell
        ["git", *args],  # noqa: S607
        capture_output=True,
        env={**os.environ, **(env or {})},
        check=False,
    )
    if check and result.returncode != 0:
        err = result.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {err}")
    if binary:
        return result
    result.stdout = result.stdout.decode("utf-8", "replace")
    return result


def remote_tip(branch: str) -> str | None:
    """Fetch the branch tip (depth 1) and return its commit id, or None if it does not exist."""
    probe = git("ls-remote", "--exit-code", "--heads", "origin", branch, check=False)
    if probe.returncode == 2:
        return None
    if probe.returncode != 0:
        raise RuntimeError(f"cannot list remote branch {branch}")
    git("fetch", "--no-tags", "--depth=1", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}")
    return git("rev-parse", f"refs/remotes/origin/{branch}").stdout.strip()


def extract(commit: str | None, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if not commit:
        return
    archive = git("archive", "--format=tar", commit, binary=True)
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        tar.extractall(dest, filter="data")


def write_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")


# ---------------------------------------------------------------------------
# ledger


def _key(entry: dict) -> tuple:
    return (entry.get("month"), entry.get("run_id"), entry.get("role"), entry.get("model"))


def merge_ledgers(base: dict | None, run: dict | None) -> dict:
    """Union of entries keyed by (month, run_id, role, model).

    Every entry only grows during a run, so on a key collision the entry with more calls is
    the newer one. Entries that exist on one side only are kept.
    """
    base = base or {}
    merged: dict[tuple, dict] = {}
    order: list[tuple] = []
    for entry in list(base.get("entries") or []) + list((run or {}).get("entries") or []):
        key = _key(entry)
        if key not in merged:
            order.append(key)
            merged[key] = entry
        elif int(entry.get("calls") or 0) > int(merged[key].get("calls") or 0):
            merged[key] = entry
    entries = [merged[k] for k in order]
    if base and entries == list(base.get("entries") or []):
        return base
    out = {k: v for k, v in base.items() if k != "entries"}
    out.setdefault("version", (run or {}).get("version", 1))
    out.setdefault("currency", "USD")
    out["updated_at"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out["entries"] = entries
    return out


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def merge_ledger_files(base: Path, run: Path, out: Path) -> None:
    merged = merge_ledgers(_read_json(base), _read_json(run))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# commands


def cmd_checkout(args: argparse.Namespace) -> int:
    dest = Path(args.dir)
    if dest.exists() and any(dest.iterdir()):
        print(f"{dest} is not empty", file=sys.stderr)
        return 2
    tip = remote_tip(args.branch)
    extract(tip, dest)
    write_output("present", "true" if tip else "false")
    write_output("commit", tip or "")
    print(f"branch {args.branch}: {'checked out ' + tip if tip else 'does not exist yet'}")
    return 0


def _overlay(source: Path, tree: Path, paths: list[str], ledger: str | None, replace: bool) -> None:
    if replace:
        for child in tree.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        shutil.copytree(source, tree, dirs_exist_ok=True)
        return
    for rel in paths:
        if Path(rel).is_absolute() or ".." in Path(rel).parts:
            raise ValueError(f"path must be relative and inside the branch: {rel}")
        src, dst = source / rel, tree / rel
        if dst.is_dir():
            shutil.rmtree(dst)
        elif dst.exists():
            dst.unlink()
        if src.is_dir():
            shutil.copytree(src, dst)
        elif src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    if ledger:
        merge_ledger_files(tree / ledger, source / ledger, tree / ledger)


def _commit(tree: Path, parent: str | None, message: str) -> str | None:
    """Commit ``tree`` with ``parent``; None if the tree equals the parent's tree."""
    with tempfile.TemporaryDirectory() as tmp:
        env = {
            "GIT_INDEX_FILE": str(Path(tmp) / "index"),
            "GIT_AUTHOR_NAME": BOT_NAME,
            "GIT_AUTHOR_EMAIL": BOT_EMAIL,
            "GIT_COMMITTER_NAME": BOT_NAME,
            "GIT_COMMITTER_EMAIL": BOT_EMAIL,
        }
        git(f"--work-tree={tree}", "add", "--all", "--force", ".", env=env)
        new_tree = git("write-tree", env=env).stdout.strip()
        if parent and git("rev-parse", f"{parent}^{{tree}}").stdout.strip() == new_tree:
            return None
        cmd = ["commit-tree", new_tree, "-m", message]
        if parent:
            cmd += ["-p", parent]
        return git(*cmd, env=env).stdout.strip()


def cmd_publish(args: argparse.Namespace) -> int:
    source = Path(args.source)
    if not source.is_dir():
        print(f"source directory {source} does not exist", file=sys.stderr)
        return 2
    if not args.replace and not args.path and not args.ledger:
        print("nothing to publish: give --path, --ledger or --replace", file=sys.stderr)
        return 2
    for attempt in range(1, ATTEMPTS + 1):
        tip = remote_tip(args.branch)
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "tree"
            extract(tip, tree)
            _overlay(source, tree, args.path or [], args.ledger, args.replace)
            commit = _commit(tree, tip, args.message)
        if commit is None:
            print(f"branch {args.branch}: no changes")
            write_output("pushed", "false")
            return 0
        push = git("push", "origin", f"{commit}:refs/heads/{args.branch}", check=False)
        if push.returncode == 0:
            print(f"branch {args.branch}: pushed {commit}")
            write_output("pushed", "true")
            return 0
        print(f"push to {args.branch} rejected (attempt {attempt}/{ATTEMPTS}); retrying", file=sys.stderr)
        time.sleep(3 * attempt)
    print(f"could not push to {args.branch} after {ATTEMPTS} attempts", file=sys.stderr)
    return 1


def cmd_merge_ledger(args: argparse.Namespace) -> int:
    merge_ledger_files(Path(args.base), Path(args.run), Path(args.out))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("checkout", help="copy a branch tree into a directory")
    p.add_argument("--branch", required=True)
    p.add_argument("--dir", required=True)
    p.set_defaults(func=cmd_checkout)

    p = sub.add_parser("publish", help="commit files onto a branch and push")
    p.add_argument("--branch", required=True)
    p.add_argument("--source", required=True, help="directory laid out like the branch")
    p.add_argument("--path", action="append", help="file or directory relative to --source")
    p.add_argument("--ledger", default=None, help="ledger path relative to --source, merged by key")
    p.add_argument("--replace", action="store_true", help="make the branch tree equal to --source")
    p.add_argument("--message", required=True)
    p.set_defaults(func=cmd_publish)

    p = sub.add_parser("merge-ledger", help="merge two spend ledgers")
    p.add_argument("--base", required=True)
    p.add_argument("--run", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_merge_ledger)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"data_branch: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
