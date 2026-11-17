"""``slopcheck-dev guard``: content changes must not take scored patterns out of the gate."""

from __future__ import annotations

import json
import subprocess

import pytest
from dev_helpers import make_pattern

from slopcheck_dev.cli import main
from slopcheck_dev.guard import guard
from slopcheck_dev.status import pattern_hash


def git(root, *args):
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=root, check=True, capture_output=True
    )


def commit(root, message="change"):
    git(root, "add", "-A")
    git(root, "commit", "-q", "--allow-empty", "-m", message)


@pytest.fixture
def grepo(repo):
    """The ``repo`` fixture (core-one is initial core, cand-one a candidate) committed on main,
    plus cand-two, a candidate that the measurement below promotes to core."""
    repo.write_pattern(make_pattern("cand-two"))
    git(repo.root, "init", "-q", "-b", "main")
    commit(repo.root, "base")
    git(repo.root, "checkout", "-q", "-b", "feature")
    return repo


def measured_core(repo, pid="cand-two", **entry):
    """measurements.json in which ``pid`` (as on the base commit) meets the core criteria."""
    pattern = make_pattern(pid)
    data = {
        "patterns": {
            pid: {
                "pattern_hash": pattern_hash(pattern),
                "fpr_human": 0.01,
                "hit_ai": 0.3,
                "lift": 9.0,
                "meets_core": True,
                "meets_fading": False,
                **entry,
            }
        }
    }
    return data


def changes(result):
    return {f.pattern_id: f.changes for f in result.findings}


def test_unchanged_repository_passes(grepo):
    result = guard(grepo.root, "main")
    assert result.ok and not result.findings
    assert "core-one" in result.guarded and "cand-one" not in result.guarded
    assert "initial core" in result.guarded["core-one"]


def test_deleted_core_pattern_fails(grepo):
    grepo.remove("patterns/text/core-one.yaml")
    result = guard(grepo.root, "main")
    assert not result.ok
    assert changes(result) == {"core-one": ["file deleted or renamed"]}


def test_renamed_core_pattern_fails(grepo):
    grepo.remove("patterns/text/core-one.yaml")
    grepo.write_pattern(make_pattern("core-renamed", status="candidate"))
    commit(grepo.root)  # committed or not makes no difference
    result = guard(grepo.root, "main")
    assert changes(result) == {"core-one": ["file deleted or renamed"]}


def test_id_changed_inside_the_file_fails(grepo):
    grepo.write_pattern(make_pattern("core-x", status="candidate"), rel="patterns/text/core-one.yaml")
    found = changes(guard(grepo.root, "main"))["core-one"]
    assert "id changed from core-one to core-x" in found


@pytest.mark.parametrize(
    ("over", "expected"),
    [
        ({"status": "candidate"}, "status changed from core to candidate"),
        ({"status": "observation"}, "status changed from core to observation"),
        ({"detector": {"kind": "vision", "rubric": "Look."}}, "detector.kind changed from regex to vision"),
        ({"detector": {"kind": "llm", "rubric": "Judge."}}, "detector.kind changed from regex to llm"),
        ({"detector": {"position": "any"}}, "detector.kind changed from regex to none"),
    ],
)
def test_status_and_detector_kind_changes_fail(grepo, over, expected):
    grepo.write_pattern(make_pattern("core-one", **{"status": "core", **over}))
    result = guard(grepo.root, "main")
    assert not result.ok
    assert expected in changes(result)["core-one"]


def test_modality_change_moves_the_file_and_fails(grepo):
    grepo.remove("patterns/text/core-one.yaml")
    grepo.write_pattern(make_pattern("core-one", status="core", modality="image"))
    found = changes(guard(grepo.root, "main"))["core-one"]
    assert found == ["file moved to `patterns/image/core-one.yaml`"]


def test_modality_change_in_place_fails(grepo):
    grepo.write_pattern(
        make_pattern("core-one", status="core", modality="image"), rel="patterns/text/core-one.yaml"
    )
    assert "modality changed from text to image" in changes(guard(grepo.root, "main"))["core-one"]


def test_measured_edits_stay_open(grepo):
    """Thresholds, examples, regexes, rubrics and word lists: the gates measure these."""
    pattern = make_pattern("core-one", status="core", threshold={"min_count": 3, "per_words": 100})
    pattern["realizations"]["en"]["patterns"] = [r"(?i)\bfoo+\b"]
    pattern["realizations"]["en"]["examples"]["positive"].append("Fooo indeed.")
    pattern["realizations"]["de"] = {"patterns": [r"(?i)\bfu\b"]}
    grepo.write_pattern(pattern)
    result = guard(grepo.root, "main")
    assert result.ok and not result.findings


def test_unscored_candidates_may_change_freely(grepo):
    grepo.write_pattern(make_pattern("cand-one", status="observation"))
    grepo.remove("patterns/text/cand-two.yaml")
    assert guard(grepo.root, "main").ok


def test_measured_core_candidate_is_guarded_with_measurements(grepo):
    grepo.write_pattern(make_pattern("cand-two", status="observation"))
    measurements = measured_core(grepo)
    assert guard(grepo.root, "main").ok  # without the file only the initial core is known
    result = guard(grepo.root, "main", measurements)
    assert not result.ok
    assert result.guarded["cand-two"] == "effective core (measured weight)"
    assert changes(result) == {"cand-two": ["status changed from candidate to observation"]}


def test_deleting_a_measured_core_candidate_fails(grepo):
    grepo.remove("patterns/text/cand-two.yaml")
    result = guard(grepo.root, "main", measured_core(grepo))
    assert changes(result) == {"cand-two": ["file deleted or renamed"]}


def test_stale_or_fading_measurement_does_not_guard(grepo):
    grepo.write_pattern(make_pattern("cand-two", status="observation"))
    stale = measured_core(grepo, pattern_hash="0" * 64)
    assert guard(grepo.root, "main", stale).ok
    fading = measured_core(grepo, meets_core=False, meets_fading=True)
    assert guard(grepo.root, "main", fading).ok


def test_governance_change_turns_findings_into_notices(grepo):
    grepo.remove("patterns/text/core-one.yaml")
    del grepo.thresholds["initial_core"]["core-one"]
    grepo.write_thresholds()
    result = guard(grepo.root, "main")
    assert result.ok and result.governance_changed
    assert changes(result) == {"core-one": ["file deleted or renamed"]}  # still reported


def test_base_is_the_merge_base(grepo):
    """Changes that landed on the base branch after the branch point are not this change's."""
    grepo.write_pattern(make_pattern("cand-one", name="Edited on the branch"))
    commit(grepo.root, "branch work")
    git(grepo.root, "checkout", "-q", "main")
    grepo.write_pattern(make_pattern("core-one", status="core", detector={"kind": "lexicon"}))
    commit(grepo.root, "maintainer change on main")
    git(grepo.root, "checkout", "-q", "feature")
    assert guard(grepo.root, "main").ok


def test_without_merge_base_the_ref_itself_is_the_base(grepo):
    """In a shallow clone git may find no merge base; then BASE_REF itself is compared."""
    git(grepo.root, "checkout", "-q", "--orphan", "unrelated")
    commit(grepo.root, "same tree, no common history")
    git(grepo.root, "checkout", "-q", "feature")
    grepo.remove("patterns/text/core-one.yaml")
    assert changes(guard(grepo.root, "unrelated")) == {"core-one": ["file deleted or renamed"]}


def test_cli_exit_codes_and_message(grepo, capsys, tmp_path):
    args = ["guard", "--base", "main", "--root", str(grepo.root)]
    assert main(args) == 0
    assert "Result: passed." in capsys.readouterr().out

    grepo.write_pattern(make_pattern("core-one", status="candidate"))
    summary = tmp_path / "summary.md"
    assert main([*args, "--summary", str(summary)]) == 1
    err = capsys.readouterr().err
    assert "`patterns/text/core-one.yaml` (`core-one`, initial core" in err
    assert "needs a maintainer" in err and "governance/" in err
    assert "Result: failed (1 pattern(s))." in summary.read_text(encoding="utf-8")

    measurements = tmp_path / "measurements.json"
    measurements.write_text(json.dumps(measured_core(grepo)), encoding="utf-8")
    assert main([*args, "--measurements", str(measurements)]) == 1
    capsys.readouterr()

    assert main(["guard", "--base", "no-such-ref", "--root", str(grepo.root)]) == 2
    assert "unknown base ref" in capsys.readouterr().err
    measurements.write_text("[1, 2]", encoding="utf-8")
    assert main([*args, "--measurements", str(measurements)]) == 2
    assert main([*args, "--measurements", str(tmp_path / "missing.json")]) == 2
