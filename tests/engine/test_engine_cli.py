"""CLI (section 4.7): audit, patterns, version, exit codes."""

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from slopcheck import __version__
from slopcheck.cli import main
from slopcheck.llm import KEY_ENV, LOCK_ENV, MODEL_ENV

SRC = Path(__file__).resolve().parents[2] / "src"


@pytest.fixture
def catalog_file(tmp_path, pattern, catalog):
    cat = catalog(
        pattern("tokA", weight=2.5, realizations={"*": {"patterns": [r"\btokA\b"]}}),
        pattern("tokB", weight=1.0, realizations={"*": {"patterns": [r"\btokB\b"]}}),
        pattern("tokC", weight=2.5, realizations={"*": {"patterns": [r"\btokC\b"]}}),
        pattern("cand", status="candidate", realizations={"*": {"patterns": [r"\bcand\b"]}}),
        pattern("img", kind="vision", rubric="Waxy skin.", modality="image", status="candidate"),
        catalog_version="test-1",
    )
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(cat), encoding="utf-8")
    return path


@pytest.fixture
def files(tmp_path):
    def write(name, text):
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    return write


def set_stdin(monkeypatch, text):
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(text.encode("utf-8")), encoding="utf-8"))


# --- audit -----------------------------------------------------------------------------


def test_audit_markdown_exit_zero(catalog_file, files, capsys):
    path = files("draft.md", "A tokA here.")
    assert main(["audit", path, "--catalog", str(catalog_file)]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"# Slop-Check: {path}\n")
    assert "Verdict: YELLOW (score 2.5;" in out


def test_audit_json_single_and_multiple(catalog_file, files, capsys):
    a, b = files("a.txt", "tokA tokB"), files("b.txt", "clean")
    assert main(["audit", a, "--format", "json", "--catalog", str(catalog_file)]) == 0
    single = json.loads(capsys.readouterr().out)
    assert single["score"] == 3.5 and single["source"] == a and single["catalog_version"] == "test-1"
    assert main(["audit", a, b, "--format", "json", "--catalog", str(catalog_file)]) == 0
    many = json.loads(capsys.readouterr().out)
    assert [r["verdict"] for r in many] == ["YELLOW", "GREEN"]


def test_audit_multiple_markdown_reports(catalog_file, files, capsys):
    a, b = files("a.txt", "tokA"), files("b.txt", "clean")
    main(["audit", a, b, "--catalog", str(catalog_file)])
    out = capsys.readouterr().out
    assert out.count("# Slop-Check: ") == 2
    assert "\n---\n" in out


def test_audit_reads_stdin(catalog_file, capsys, monkeypatch):
    set_stdin(monkeypatch, "tokB tokB")
    assert main(["audit", "-", "--format", "json", "--catalog", str(catalog_file)]) == 0
    assert json.loads(capsys.readouterr().out)["source"] == "stdin"
    set_stdin(monkeypatch, "tokA")
    assert main(["audit", "--catalog", str(catalog_file), "--report-lang", "de"]) == 0
    assert "Gesamtbefund: GELB" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("text", "fail_on", "code"),
    [
        ("clean", "yellow", 0),
        ("tokA", "yellow", 1),
        ("tokA", "red", 0),
        ("tokA tokA tokB tokB tokB", "red", 0),
        ("tokA tokC", "red", 1),
        ("tokA", None, 0),
    ],
)
def test_fail_on_exit_codes(catalog_file, files, capsys, text, fail_on, code):
    args = ["audit", files("t.txt", text), "--catalog", str(catalog_file)]
    if fail_on:
        args += ["--fail-on", fail_on]
    assert main(args) == code


def test_fail_on_uses_worst_of_several_files(catalog_file, files, capsys):
    a, b = files("a.txt", "clean"), files("b.txt", "tokA")
    assert main(["audit", a, b, "--fail-on", "yellow", "--catalog", str(catalog_file)]) == 1


def test_language_and_context_options(catalog_file, files, capsys):
    path = files("t.txt", "Das ist gut und wir sind froh.")
    main(["audit", path, "--format", "json", "--catalog", str(catalog_file)])
    assert json.loads(capsys.readouterr().out)["language"] == "de"
    main(
        [
            "audit",
            path,
            "--lang",
            "en",
            "--context",
            "technical",
            "--format",
            "json",
            "--catalog",
            str(catalog_file),
        ]
    )
    result = json.loads(capsys.readouterr().out)
    assert (result["language"], result["context"]) == ("en", "technical")


def test_usage_and_input_errors_exit_two(catalog_file, tmp_path, capsys):
    assert main(["audit", str(tmp_path / "missing.txt"), "--catalog", str(catalog_file)]) == 2
    assert "cannot read input" in capsys.readouterr().err
    assert main(["audit", "--format", "xml"]) == 2
    assert main([]) == 2
    bad = tmp_path / "bad.txt"
    bad.write_bytes(b"\xff\xfe\xfa")
    assert main(["audit", str(bad), "--catalog", str(catalog_file)]) == 2


def test_missing_or_broken_catalog_exits_two(tmp_path, files, capsys, monkeypatch):
    path = files("t.txt", "text")
    assert main(["audit", path, "--catalog", str(tmp_path / "nope.json")]) == 2
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert main(["audit", path, "--catalog", str(broken)]) == 2
    assert "catalog" in capsys.readouterr().err


def test_catalog_from_environment(catalog_file, files, capsys, monkeypatch):
    monkeypatch.setenv("SLOPCHECK_CATALOG", str(catalog_file))
    assert main(["audit", files("t.txt", "tokA"), "--fail-on", "yellow"]) == 1


# --- llm flags ---------------------------------------------------------------------------


def test_llm_without_key_warns_and_continues(catalog_file, files, capsys, monkeypatch):
    monkeypatch.delenv(KEY_ENV, raising=False)
    assert main(["audit", files("t.txt", "tokA"), "--llm", "--catalog", str(catalog_file)]) == 0
    assert KEY_ENV in capsys.readouterr().err


def test_llm_with_key_needs_a_model(catalog_file, files, capsys, monkeypatch):
    monkeypatch.setenv(KEY_ENV, "dummy")
    monkeypatch.delenv(MODEL_ENV, raising=False)
    monkeypatch.delenv(LOCK_ENV, raising=False)
    assert main(["audit", files("t.txt", "tokA"), "--llm", "--catalog", str(catalog_file)]) == 2
    assert "--llm-model" in capsys.readouterr().err


# --- patterns and version ------------------------------------------------------------


def test_patterns_command_filters(catalog_file, capsys):
    assert main(["patterns", "--catalog", str(catalog_file)]) == 0
    table = capsys.readouterr().out
    assert "`tokA`" in table and "`img`" in table
    main(
        [
            "patterns",
            "--modality",
            "text",
            "--status",
            "candidate",
            "--format",
            "json",
            "--catalog",
            str(catalog_file),
        ]
    )
    assert [p["id"] for p in json.loads(capsys.readouterr().out)] == ["cand"]
    main(["patterns", "--modality", "image", "--format", "json", "--catalog", str(catalog_file)])
    assert [p["id"] for p in json.loads(capsys.readouterr().out)] == ["img"]


def test_version(catalog_file, capsys, monkeypatch):
    assert main(["version", "--catalog", str(catalog_file)]) == 0
    assert capsys.readouterr().out == f"slopcheck {__version__} (catalog test-1, 5 patterns)\n"
    monkeypatch.setenv("SLOPCHECK_CATALOG", "/nonexistent/catalog.json")
    assert main(["version"]) == 0
    assert "no catalog found" in capsys.readouterr().out


def test_python_dash_m_entry_point(catalog_file, tmp_path):
    env = {"PYTHONPATH": str(SRC), "PATH": "/usr/bin:/bin", "SLOPCHECK_CATALOG": str(catalog_file)}
    proc = subprocess.run(
        [sys.executable, "-m", "slopcheck", "audit", "-", "--fail-on", "yellow"],
        input=b"tokA",
        capture_output=True,
        env=env,
        cwd=tmp_path,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 1
    assert b"Verdict: YELLOW" in proc.stdout
