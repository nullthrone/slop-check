from __future__ import annotations

import argparse
import json

import pytest
import yaml
from evals_helpers import FIXTURES

from slopcheck_dev.evals import cli
from slopcheck_dev.evals._common import iso, sha256_text, split_of, utc_now, write_json, write_jsonl
from slopcheck_dev.evals.budget import Ledger, current_month

LEAVES = [
    ["corpus", "fetch-human", "--out", "x"],
    ["corpus", "generate-ai", "--human", "h", "--out", "o"],
    ["measure", "--human", "h", "--ai", "a", "--split", "dev", "--out", "f"],
    ["conformance", "--skill", "s", "--out", "f"],
    ["budget", "status"],
    ["budget", "check", "--amount", "1.5"],
    ["models", "resolve"],
]


def parser():
    p = argparse.ArgumentParser(prog="slopcheck-dev")
    cli.register(p.add_subparsers(dest="command"))
    return p


@pytest.mark.parametrize("argv", LEAVES)
def test_every_leaf_sets_func(argv):
    args = parser().parse_args(argv)
    assert callable(args.func)


def test_group_without_subcommand_prints_help():
    args = parser().parse_args(["budget"])
    assert args.func(args) == cli.EXIT_USAGE


def test_registered_in_tooling_cli():
    tooling = pytest.importorskip("slopcheck_dev.cli")
    p = tooling.build_parser()
    for argv in LEAVES:
        assert callable(p.parse_args(argv).func)


# ---------------------------------------------------------------------------
# models


def test_models_resolve_cli(tmp_path, capsys):
    cfg = {
        "exclusions": {"id_regex": [":free$", ":batch$", "-preview"], "expiration_grace_days": 30},
        "generators": [{"family": "acme", "match": r"^acme/chat-1\.[01]$", "tier": "cheap"}],
        "judges": [{"family": "zzz", "match": r"^zzz/"}],
    }
    cfg_path = tmp_path / "models.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg))
    prev = {
        "resolved_at": "2025-01-01T00:00:00Z",
        "roles": {
            "generators": [
                {
                    "key": "generators/acme/cheap",
                    "id": "acme/chat-1.0",
                    "canonical_slug": "acme/chat-1.0-20250101",
                }
            ]
        },
    }
    write_json(tmp_path / "prev.json", prev)
    out = tmp_path / "lock.json"
    report = tmp_path / "report.md"
    code = cli.main(
        [
            "models",
            "resolve",
            "--config",
            str(cfg_path),
            "--source",
            str(FIXTURES / "openrouter-models.json"),
            "--previous",
            str(tmp_path / "prev.json"),
            "--out",
            str(out),
            "--report",
            str(report),
        ]
    )
    assert code == 0
    lock = json.loads(out.read_text())
    assert lock["roles"]["generators"][0]["id"] == "acme/chat-1.1"
    assert lock["changes"] == [
        "generators/acme/cheap: acme/chat-1.0 -> acme/chat-1.1 [acme/chat-1.1-20250601]"
    ]
    assert lock["errors"]
    assert "acme/chat-1.0 -> acme/chat-1.1" in report.read_text()
    assert "ERROR" in capsys.readouterr().err


def test_models_resolve_cli_nothing_resolved(tmp_path):
    cfg_path = tmp_path / "models.yaml"
    cfg_path.write_text(yaml.safe_dump({"judges": [{"family": "z", "match": "^zzz/"}]}))
    out = tmp_path / "lock.json"
    code = cli.main(
        [
            "models",
            "resolve",
            "--config",
            str(cfg_path),
            "--source",
            str(FIXTURES / "openrouter-models.json"),
            "--out",
            str(out),
        ]
    )
    assert code == cli.EXIT_FAIL and not out.exists()


def test_models_resolve_cli_fetch_failure(tmp_path):
    code = cli.main(["models", "resolve", "--source", str(tmp_path / "missing.json")])
    assert code == cli.EXIT_USAGE


# ---------------------------------------------------------------------------
# budget


def test_budget_cli(tmp_path, capsys):
    ledger_path = tmp_path / "ledger.json"
    code = cli.main(["budget", "status", "--ledger", str(ledger_path)])
    assert code == 0
    status = json.loads(capsys.readouterr().out)
    assert status["month_total_usd"] == 0 and status["monthly_cap_usd"] > 0
    assert cli.main(["budget", "check", "--amount", "1.0", "--ledger", str(ledger_path)]) == 0
    capsys.readouterr()
    ledger = Ledger(ledger_path)
    ledger.add(
        run_id="x", run_kind="scheduled", role="generators", model="m", usd=25.5, month=current_month()
    )
    ledger.save()
    assert cli.main(["budget", "check", "--amount", "1.0", "--ledger", str(ledger_path)]) == cli.EXIT_FAIL
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and "monthly cap" in out["reason"]
    # a planned run larger than the run cap fails even with an empty month
    assert (
        cli.main(
            [
                "budget",
                "check",
                "--amount",
                "1.0",
                "--run-kind",
                "pull_request",
                "--ledger",
                str(tmp_path / "empty.json"),
            ]
        )
        == cli.EXIT_FAIL
    )


# ---------------------------------------------------------------------------
# corpora and measurement with mocked HTTP

PLAIN = (
    "The bridge opened in 1932 and trams used it until the line closed in 1961. "
    "The town repaid the loan for it over thirty years. "
) * 6
SLOP = "In today's fast-paced world, this is not just a bridge, it's a movement. " + PLAIN


def write_human(tmp_path, n=6):
    docs = []
    for i in range(n):
        doc_id = f"en-web-src-{i}"
        docs.append(
            {
                "doc_id": doc_id,
                "language": "en",
                "register": "web",
                "title": f"Bridge {i}",
                "text": PLAIN,
                "words": 150,
                "sha256": sha256_text(PLAIN),
                "split": split_of(doc_id),
            }
        )
    d = tmp_path / "human"
    write_jsonl(d / "docs.jsonl", docs)
    write_json(
        d / "manifest.json",
        {"documents": [{k: v for k, v in x.items() if k not in ("text", "title")} for x in docs]},
    )
    return d, docs


def lock_file(tmp_path):
    entry = {
        "key": "generators/acme/cheap",
        "family": "acme",
        "tier": "cheap",
        "id": "acme/chat-1.1",
        "canonical_slug": "acme/chat-1.1-20250601",
        "pricing": {"prompt": 1e-7, "completion": 4e-7},
        "docs_per_language": 3,
    }
    judge = dict(entry, key="judges/acme/cheap")
    conf = dict(entry, key="conformance/acme/cheap")
    lock = {
        "resolved_at": iso(utc_now()),
        "roles": {"generators": [entry], "judges": [judge], "conformance": [conf]},
        "changes": [],
        "errors": [],
    }
    path = tmp_path / "lock.json"
    write_json(path, lock)
    return path


def chat_response(text):
    return {
        "model": "acme/chat-1.1",
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 200, "cost": 0.0001},
    }


def test_generate_ai_cli(tmp_path, fake_http, monkeypatch, capsys):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    human_dir, _ = write_human(tmp_path)
    fake_http.add("/chat/completions", chat_response(SLOP))
    out = tmp_path / "ai"
    code = cli.main(
        [
            "corpus",
            "generate-ai",
            "--human",
            str(human_dir),
            "--out",
            str(out),
            "--lock",
            str(lock_file(tmp_path)),
            "--ledger",
            str(tmp_path / "ledger.json"),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--workers",
            "1",
        ]
    )
    assert code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["generated"] == 3
    assert (out / "acme__chat-1.1-20250601" / "en.jsonl.gz").is_file()
    ledger = json.loads((tmp_path / "ledger.json").read_text())
    assert ledger["entries"][0]["calls"] == 3 and ledger["entries"][0]["usd"] == pytest.approx(0.0003)


def test_generate_ai_cli_budget_exit(tmp_path, fake_http, monkeypatch, capsys):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    human_dir, _ = write_human(tmp_path)
    fake_http.add("/chat/completions", chat_response(SLOP))
    code = cli.main(
        [
            "corpus",
            "generate-ai",
            "--human",
            str(human_dir),
            "--out",
            str(tmp_path / "ai"),
            "--lock",
            str(lock_file(tmp_path)),
            "--ledger",
            str(tmp_path / "ledger.json"),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--workers",
            "1",
            "--max-call-usd",
            "0.000001",
        ]
    )
    assert code == cli.EXIT_BUDGET
    assert fake_http.requests == []


def _measure_ready():
    pytest.importorskip("slopcheck.engine")
    pytest.importorskip("slopcheck_dev.build")
    pytest.importorskip("slopcheck_dev.status")


def test_measure_cli_end_to_end(tmp_path, capsys):
    _measure_ready()
    human_dir, docs = write_human(tmp_path, n=8)
    ai_recs = [
        {
            "doc_id": d["doc_id"],
            "model": "acme/chat-1.1",
            "canonical_slug": "acme/chat-1.1-20250601",
            "family": "acme",
            "language": "en",
            "register": "blog-post",
            "prompt_id": "en-blog-post",
            "text": SLOP,
        }
        for d in docs
    ]
    write_jsonl(tmp_path / "ai" / "acme__chat-1.1-20250601" / "en.jsonl.gz", ai_recs)
    out = tmp_path / "m.json"
    report = tmp_path / "r.md"
    code = cli.main(
        [
            "measure",
            "--human",
            str(human_dir),
            "--ai",
            str(tmp_path / "ai"),
            "--split",
            "all",
            "--patterns",
            "antithesis-template",
            "generic-opening",
            "--out",
            str(out),
            "--report",
            str(report),
        ]
    )
    assert code == 0
    m = json.loads(out.read_text())
    assert m["corpus"] == {"human_docs": {"en": 8}, "ai_docs": {"en": 8}, "split": "all"}
    for pid in ("antithesis-template", "generic-opening"):
        assert m["patterns"][pid]["fpr_human"] == 0.0 and m["patterns"][pid]["hit_ai"] == 1.0
    assert m["models"]["generators"] == ["acme/chat-1.1-20250601"]
    assert "antithesis-template" in report.read_text()


def test_measure_cli_llm_without_key(tmp_path, capsys):
    _measure_ready()
    human_dir, docs = write_human(tmp_path, n=4)
    write_jsonl(
        tmp_path / "ai" / "m" / "en.jsonl",
        [
            {
                "doc_id": docs[0]["doc_id"],
                "language": "en",
                "family": "acme",
                "canonical_slug": "a/b",
                "text": SLOP,
            }
        ],
    )
    out = tmp_path / "m.json"
    code = cli.main(
        [
            "measure",
            "--human",
            str(human_dir),
            "--ai",
            str(tmp_path / "ai"),
            "--split",
            "all",
            "--patterns",
            "antithesis-template",
            "hollow-sentences",
            "--llm",
            "--out",
            str(out),
            "--lock",
            str(lock_file(tmp_path)),
            "--ledger",
            str(tmp_path / "l.json"),
        ]
    )
    assert code == 0
    m = json.loads(out.read_text())
    assert "hollow-sentences" not in m["patterns"] and "antithesis-template" in m["patterns"]
    assert any("OPENROUTER_API_KEY" in n for n in m["notices"])


def test_measure_cli_bad_input(tmp_path):
    assert (
        cli.main(
            [
                "measure",
                "--human",
                str(tmp_path / "none"),
                "--ai",
                str(tmp_path),
                "--split",
                "dev",
                "--out",
                str(tmp_path / "x.json"),
            ]
        )
        == cli.EXIT_USAGE
    )


def test_conformance_cli(tmp_path, fake_http, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    skill = tmp_path / "slop-check"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: slop-check\ndescription: test\n---\nBody\n")
    cases = tmp_path / "cases"
    cases.mkdir()
    (cases / "c1.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "c1",
                "language": "en",
                "mode": "audit",
                "text": "Hello.",
                "must_find": ["p1"],
                "must_not_find": ["p2"],
            }
        )
    )
    block = json.dumps({"verdict": "RED", "findings": [{"pattern_id": "p1"}]})
    fake_http.add("/chat/completions", chat_response(f"Report\n```json\n{block}\n```"))
    out = tmp_path / "conf.json"
    code = cli.main(
        [
            "conformance",
            "--skill",
            str(skill),
            "--out",
            str(out),
            "--cases",
            str(cases),
            "--lock",
            str(lock_file(tmp_path)),
            "--ledger",
            str(tmp_path / "l.json"),
            "--cache-dir",
            str(tmp_path / "cache"),
        ]
    )
    assert code == 0
    res = json.loads(out.read_text())
    assert res["models"][0]["summary"]["recall"] == 1.0 and res["models"][0]["summary"]["passed"] == 1
    system = fake_http.bodies()[0]["messages"][0]["content"]
    assert '<skill name="slop-check">' in system


def test_conformance_cli_requires_key(tmp_path):
    assert (
        cli.main(
            [
                "conformance",
                "--skill",
                str(tmp_path),
                "--out",
                str(tmp_path / "o.json"),
                "--lock",
                str(lock_file(tmp_path)),
            ]
        )
        == cli.EXIT_USAGE
    )
