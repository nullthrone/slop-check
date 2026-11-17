"""slopcheck-dev gate: pull request admission rules on the dev split."""

from __future__ import annotations

import json

import pytest
from dev_helpers import make_pattern

from slopcheck_dev.cli import main
from slopcheck_dev.gate import gate
from slopcheck_dev.status import pattern_hash


def entry(
    pattern: dict,
    fpr: float | None = 0.02,
    lift: float | None = 6.0,
    meets_core: bool = False,
    per_language: dict | None = None,
    **extra,
) -> dict:
    out = {
        "pattern_hash": pattern_hash(pattern),
        "fpr_human": fpr,
        "hit_ai": 0.3,
        "lift": lift,
        "meets_core": meets_core,
        "meets_fading": False,
        "per_language": per_language
        if per_language is not None
        else {"en": {"fpr_human": fpr, "n_human": 120}},
        "per_family": {"anthropic": {"lift": 5.0}, "google": {"lift": 4.0}},
    }
    out.update(extra)
    return out


def measure(entries: dict, split: str = "dev") -> dict:
    return {
        "corpus": {"human_docs": {"en": 120}, "ai_docs": {"en": 600}, "split": split},
        "patterns": entries,
    }


def row(result, pid: str):
    return next(r for r in result.rows if r.pattern_id == pid)


# ---------------------------------------------------------------------------
# candidates


@pytest.mark.parametrize(("fpr", "outcome"), [(0.0, "pass"), (0.1, "pass"), (0.15, "pass"), (0.151, "fail")])
def test_candidate_fpr_limit(thresholds, fpr, outcome):
    cand = make_pattern("cand-one")
    result = gate(measure({"cand-one": entry(cand, fpr=fpr)}), [cand], thresholds)
    assert row(result, "cand-one").result == outcome
    assert row(result, "cand-one").rule == "fpr_human <= 0.15"
    assert result.ok is (outcome == "pass")


def test_candidate_fails_on_one_language(thresholds):
    cand = make_pattern("cand-one")
    per_language = {"de": {"fpr_human": 0.3, "n_human": 100}, "en": {"fpr_human": 0.0, "n_human": 100}}
    result = gate(measure({"cand-one": entry(cand, fpr=0.1, per_language=per_language)}), [cand], thresholds)
    r = row(result, "cand-one")
    assert r.result == "fail" and r.reasons == ["fpr_human (de) 0.3 above 0.15"]


def test_candidate_without_human_documents_fails(thresholds):
    cand = make_pattern("cand-one")
    result = gate(
        measure({"cand-one": entry(cand, fpr=None, lift=None, per_language={})}), [cand], thresholds
    )
    assert row(result, "cand-one").reasons == ["no human documents measured"]
    assert not result.ok


def test_candidate_limit_comes_from_thresholds(thresholds):
    thresholds["admission"]["candidate"]["pr_gate"]["max_fpr_human"] = 0.05
    cand = make_pattern("cand-one")
    result = gate(measure({"cand-one": entry(cand, fpr=0.1)}), [cand], thresholds)
    assert row(result, "cand-one").result == "fail"


def test_candidate_does_not_need_core_criteria(thresholds):
    cand = make_pattern("cand-one")
    result = gate(measure({"cand-one": entry(cand, fpr=0.1, lift=1.0, meets_core=False)}), [cand], thresholds)
    assert result.ok


# ---------------------------------------------------------------------------
# patterns that score: core criteria on the dev split


def test_initial_core_must_meet_core(thresholds):
    core = make_pattern("core-one", status="core")
    ok = gate(measure({"core-one": entry(core, meets_core=True)}), [core], thresholds)
    assert row(ok, "core-one").rule == "core criteria (dev split)"
    assert ok.ok
    bad = gate(measure({"core-one": entry(core, fpr=0.09, lift=1.2, meets_core=False)}), [core], thresholds)
    r = row(bad, "core-one")
    assert r.result == "fail"
    assert "fpr_human 0.09 above 0.05" in r.reasons
    assert "lift 1.2 below 2" in r.reasons
    assert not bad.ok


def test_core_reasons_name_family_and_document_gaps(thresholds):
    core = make_pattern("core-one", status="core")
    e = entry(
        core,
        fpr=0.01,
        lift=5.0,
        meets_core=False,
        per_language={"en": {"fpr_human": 0.01, "n_human": 40}},
        per_family={"anthropic": {"lift": 5.0}, "google": {"lift": 1.1}},
    )
    reasons = row(gate(measure({"core-one": e}), [core], thresholds), "core-one").reasons
    assert reasons == [
        "only 40 human documents (en), need 100",
        "1 model families with lift >= 1.5, need 2",
    ]
    e = entry(core, fpr=0.01, lift=5.0, meets_core=False)
    reasons = row(gate(measure({"core-one": e}), [core], thresholds), "core-one").reasons
    assert reasons == ["meets_core is false (for example too few triggered AI documents)"]


def test_candidate_that_is_measured_core_now_must_meet_core(thresholds):
    base = make_pattern("cand-one")
    current = {"patterns": {"cand-one": entry(base, meets_core=True)}}
    edited = make_pattern("cand-one", fix="A sharper fix for the pattern.")
    measured = measure({"cand-one": entry(edited, fpr=0.01, lift=1.3, meets_core=False)})
    result = gate(measured, [edited], thresholds, current)
    r = row(result, "cand-one")
    assert r.rule == "core criteria (dev split)"
    assert r.result == "fail"
    assert gate(
        measured, [edited], thresholds, None
    ).ok  # without current measurements it is a plain candidate


def test_fading_core_edited_must_meet_core_again(thresholds):
    core = make_pattern("core-one", status="core")
    current = {"patterns": {"core-one": entry(core, meets_fading=True)}}
    result = gate(measure({"core-one": entry(core, fpr=0.01, meets_core=False)}), [core], thresholds, current)
    assert row(result, "core-one").rule == "core criteria (dev split)"
    assert not result.ok


# ---------------------------------------------------------------------------
# measurement problems and skipped patterns


def test_stale_measurement_fails(thresholds):
    cand = make_pattern("cand-one")
    edited = make_pattern("cand-one", summary="Edited after the measurement ran.")
    r = row(gate(measure({"cand-one": entry(cand)}), [edited], thresholds), "cand-one")
    assert r.result == "fail" and "stale measurement" in r.reasons[0]


def test_missing_measurement_fails(thresholds):
    result = gate(measure({}), [make_pattern("cand-one")], thresholds)
    assert row(result, "cand-one").reasons == ["no measurement for this pattern in the file"]
    assert not result.ok


def test_holdout_measurement_is_rejected(thresholds):
    cand = make_pattern("cand-one")
    result = gate(measure({"cand-one": entry(cand)}, split="holdout"), [cand], thresholds)
    assert row(result, "cand-one").result == "pass"
    assert result.errors and "split 'holdout'" in result.errors[0]
    assert not result.ok


def test_skipped_patterns(thresholds):
    patterns = [
        make_pattern("obs-one", status="observation"),
        make_pattern("llm-one", detector={"kind": "llm", "rubric": "Judge it."}),
        make_pattern("img-one", modality="image", detector={"kind": "vision", "rubric": "Look."}),
        make_pattern("obs-two", status="observation", detector=None),
    ]
    result = gate(measure({}), patterns, thresholds)
    assert {r.pattern_id: r.result for r in result.rows} == dict.fromkeys(
        ("img-one", "llm-one", "obs-one", "obs-two"), "skipped"
    )
    assert "llm-gate" in row(result, "llm-one").reasons[0]
    assert result.ok
    assert "Result: passed." in result.markdown


def test_markdown_summary(thresholds):
    good = make_pattern("cand-one")
    bad = make_pattern("cand-two")
    m = measure({"cand-one": entry(good, fpr=0.05, lift=7.25), "cand-two": entry(bad, fpr=0.4, lift=1.0)})
    md = gate(m, [bad, good], thresholds).markdown
    lines = md.splitlines()
    assert lines[0] == "## Empirical gate (dev split)"
    assert "Human documents: en 120. AI documents: en 600." in lines
    assert "| `cand-one` | fpr_human <= 0.15 | 0.05 | 7.25 | pass |" in lines
    assert "| `cand-two` | fpr_human <= 0.15 | 0.4 | 1 | fail |" in lines
    assert lines.index("| `cand-one` | fpr_human <= 0.15 | 0.05 | 7.25 | pass |") < lines.index(
        "| `cand-two` | fpr_human <= 0.15 | 0.4 | 1 | fail |"
    )
    assert "- `cand-two` (fail): fpr_human 0.4 above 0.15; fpr_human (en) 0.4 above 0.15" in lines
    assert lines[-1] == "Result: failed (1 pattern(s), 0 error(s))."
    assert "No patterns to gate." in gate(measure({}), [], thresholds).markdown


# ---------------------------------------------------------------------------
# CLI


def write_json(path, data) -> str:
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_cli_gate(repo, tmp_path, capsys):
    cand = make_pattern("cand-one")
    core = make_pattern("core-one", status="core")
    good = write_json(
        tmp_path / "m.json", measure({"cand-one": entry(cand), "core-one": entry(core, meets_core=True)})
    )
    summary = tmp_path / "summary.md"
    summary.write_text("# CI\n", encoding="utf-8")
    args = ["gate", "--root", str(repo.root), "--measure", good, "--summary", str(summary)]
    assert main([*args, "--patterns", "cand-one", "core-one", "deleted-one", "cand-one"]) == 0
    out = capsys.readouterr().out
    assert out.count("`cand-one`") == 1
    assert "| `deleted-one` | - | - | - | skipped |" in out
    assert summary.read_text(encoding="utf-8") == "# CI\n" + out

    bad = write_json(tmp_path / "bad.json", measure({"cand-one": entry(cand), "core-one": entry(core)}))
    assert main(["gate", "--root", str(repo.root), "--measure", bad, "--patterns", "core-one"]) == 1
    assert "Result: failed" in capsys.readouterr().out

    current = write_json(tmp_path / "current.json", {"patterns": {"cand-one": entry(cand, meets_core=True)}})
    weak = write_json(tmp_path / "weak.json", measure({"cand-one": entry(cand, lift=1.1)}))
    assert main(["gate", "--root", str(repo.root), "--measure", weak, "--patterns", "cand-one"]) == 0
    assert (
        main(
            [
                "gate",
                "--root",
                str(repo.root),
                "--measure",
                weak,
                "--current",
                current,
                "--patterns",
                "cand-one",
            ]
        )
        == 1
    )


def test_cli_gate_input_errors(repo, tmp_path, capsys):
    broken = tmp_path / "broken.json"
    broken.write_text("{nope", encoding="utf-8")
    assert main(["gate", "--root", str(repo.root), "--measure", str(broken), "--patterns", "cand-one"]) == 2
    assert main(["gate", "--root", str(repo.root), "--measure", str(tmp_path / "missing.json")]) == 2
    listing = write_json(tmp_path / "list.json", [1, 2])
    assert main(["gate", "--root", str(repo.root), "--measure", listing]) == 2
    assert main(["gate", "--root", str(repo.root)]) == 2  # --measure is required
    assert "gate:" in capsys.readouterr().err
