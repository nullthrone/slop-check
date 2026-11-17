"""slopcheck-dev validate: schema, rules 1-8, independence clusters, regex safety."""

from __future__ import annotations

import subprocess

import pytest
from dev_helpers import make_pattern, make_source

from slopcheck_dev import regex_safety
from slopcheck_dev.cli import main
from slopcheck_dev.patterns import load_patterns, load_sources, load_thresholds, normalize_dates
from slopcheck_dev.validate import changed_files, independent_source_count, source_clusters, validate


def messages(report, needle: str = "") -> list[str]:
    return [str(i) for i in report.errors if needle in str(i)]


def run(repo, **kw):
    kw.setdefault("regex_timing", False)
    return validate(repo.root, **kw)


# ---------------------------------------------------------------------------
# loading


def test_loader_normalizes_unquoted_dates(mini_repo):
    path = mini_repo.root / "sources" / "dated.yaml"
    path.write_text(
        "id: dated\ntitle: Dated source\naccessed: 2026-11-17\npublished: 2025-01-02\ntype: blog\n",
        encoding="utf-8",
    )
    sources = load_sources(mini_repo.root)
    assert sources["dated"]["accessed"] == "2026-11-17"
    assert sources["dated"]["published"] == "2025-01-02"


def test_normalize_dates_recurses():
    import datetime as dt

    data = {"a": [dt.date(2026, 7, 30), {"b": dt.date(2026, 1, 2)}], "c": "x"}
    assert normalize_dates(data) == {"a": ["2026-07-30", {"b": "2026-01-02"}], "c": "x"}


def test_load_patterns_sorted_and_thresholds(repo):
    repo.write_pattern(make_pattern("img-one", modality="image"))
    pats = load_patterns(repo.root)
    assert [(p["modality"], p["id"]) for p in pats] == [
        ("image", "img-one"),
        ("text", "cand-one"),
        ("text", "core-one"),
    ]
    assert load_patterns(repo.root, "image")[0]["id"] == "img-one"
    assert load_thresholds(repo.root)["initial_core"]["core-one"] == 2.5


# ---------------------------------------------------------------------------
# valid repository and schema


def test_valid_repo_passes(repo):
    report = run(repo)
    assert report.ok, report.render()
    assert report.patterns == 2
    assert report.sources == 3


def test_schema_error_reported_with_path(repo):
    repo.write_pattern(make_pattern("cand-two", category="nonsense"))
    report = run(repo)
    errs = messages(report, "patterns/text/cand-two.yaml")
    assert any("schema: category" in e for e in errs)


def test_yaml_parse_error_reported(repo):
    (repo.root / "patterns" / "text" / "broken.yaml").write_text("id: [unclosed\n", encoding="utf-8")
    report = run(repo)
    assert any("broken.yaml" in e and "invalid YAML" in e for e in messages(report))


def test_source_schema_and_filename(repo):
    repo.write_source(make_source("src-c", type="tweet"), rel="sources/other-name.yaml")
    report = run(repo)
    errs = messages(report, "sources/other-name.yaml")
    assert any("schema: type" in e for e in errs)
    assert any("file name must be 'src-c.yaml'" in e for e in errs)


# ---------------------------------------------------------------------------
# rules 1-8


def test_rule1_core_requires_initial_core(repo):
    repo.write_pattern(make_pattern("new-core", status="core"))
    errs = messages(run(repo), "rule 1")
    assert len(errs) == 1 and "new-core.yaml" in errs[0] and "initial_core" in errs[0]


def test_rule1_initial_core_ids_may_declare_core(repo):
    repo.write_pattern(make_pattern("core-two", status="core"))
    assert run(repo).ok


def test_weight_fields_are_not_declared_in_pattern_files(repo):
    # weight and effective status are derived by the build, never declared (D5)
    for field, value in (("weight", 2.5), ("effective_status", "core"), ("weight_source", "measured")):
        repo.write_pattern(make_pattern("core-two", status="core", **{field: value}))
        errs = messages(run(repo), "patterns/text/core-two.yaml")
        assert any("schema" in e and field in e for e in errs), (field, errs)


def test_initial_core_must_map_ids_to_weights(repo):
    repo.thresholds["initial_core"] = {"core-one": "heavy", "core-two": -1, "core-three": 0.5}
    repo.write_thresholds()
    report = run(repo)
    errs = messages(report, "governance/thresholds.yaml")
    assert len(errs) == 2
    assert any("'core-one'" in e for e in errs) and any("'core-two'" in e for e in errs)
    assert any("'core-three' has no pattern file" in str(w) for w in report.warnings)
    repo.thresholds["initial_core"] = ["core-one"]
    repo.write_thresholds()
    report = run(repo)
    assert messages(report, "initial_core must be a mapping")
    assert messages(report, "rule 1")  # a list grants no core status


def test_rule2_candidate_needs_two_independent_sources(repo):
    repo.write_pattern(make_pattern("cand-two", sources=[{"source": "src-a"}]))
    errs = messages(run(repo), "rule 2")
    assert len(errs) == 1 and "has 1" in errs[0]


def test_rule2_own_observation_never_counts(repo):
    repo.write_pattern(make_pattern("cand-two", sources=[{"source": "src-a"}, {"source": "src-own"}]))
    assert messages(run(repo), "independent sources, has 1")


def test_rule2_same_publisher_is_one_cluster(repo):
    repo.write_source(make_source("src-c", publisher="Publisher SRC-A"))  # case-insensitive match
    repo.write_pattern(make_pattern("cand-two", sources=[{"source": "src-a"}, {"source": "src-c"}]))
    assert messages(run(repo), "independent sources, has 1")


def test_rule2_derived_from_transitive_is_one_cluster(repo):
    repo.write_source(make_source("src-c", derived_from=["src-d"]))
    repo.write_source(make_source("src-d", derived_from=["src-e"]))
    repo.write_source(make_source("src-e"))
    repo.write_pattern(make_pattern("cand-two", sources=[{"source": "src-c"}, {"source": "src-e"}]))
    assert messages(run(repo), "independent sources, has 1")


def test_rule2_examples_per_language(repo):
    pattern = make_pattern("cand-two")
    pattern["realizations"]["de"] = {
        "patterns": [r"\bfoo\b"],
        "examples": {"positive": ["foo"], "negative": ["bar", "baz"]},
    }
    repo.write_pattern(pattern)
    errs = messages(run(repo), "rule 2")
    assert len(errs) == 1 and "realizations.de has 1 positive, 2 negative" in errs[0]


def test_rule2_not_applied_to_observation_or_core(repo):
    repo.write_pattern(make_pattern("obs-one", status="observation", realizations={"en": {}}))
    core = make_pattern("core-two", status="core", sources=[{"source": "src-own"}])
    core["realizations"]["en"]["examples"] = {"positive": ["foo"]}
    repo.write_pattern(core)
    assert run(repo).ok


def test_rule3_and_rule4_unresolved_source(repo):
    repo.write_pattern(make_pattern("obs-one", status="observation", sources=[{"source": "missing-src"}]))
    report = run(repo)
    assert messages(report, "rule 4: source 'missing-src'")
    assert messages(report, "rule 3")


def test_rule5_regex_does_not_compile(repo):
    pattern = make_pattern("cand-two")
    pattern["realizations"]["en"]["patterns"] = ["(unclosed"]
    repo.write_pattern(pattern)
    errs = messages(run(repo), "rule 5")
    assert errs and "realizations.en.patterns[0]: does not compile" in errs[0]


def test_rule5_nested_quantifier_rejected(repo):
    pattern = make_pattern("cand-two")
    pattern["realizations"]["en"]["patterns"] = [r"(?i)(?:\w+\s?)+foo"]
    repo.write_pattern(pattern)
    errs = messages(run(repo), "rule 5")
    assert errs and "nested unbounded quantifier" in errs[0]


def test_rule5_catastrophic_regex_times_out(repo):
    pattern = make_pattern("cand-two")
    pattern["realizations"]["en"]["patterns"] = [r"(a|a)*b"]  # no nested quantifier, exponential
    repo.write_pattern(pattern)
    report = validate(repo.root, regex_timing=True)
    errs = messages(report, "rule 5")
    assert errs and ("did not finish" in errs[0] or "took" in errs[0])
    assert report.regexes_timed == 3


def test_rule5_safe_regexes_pass_timing(repo):
    report = validate(repo.root, regex_timing=True)
    assert report.ok, report.render()
    assert report.regexes_timed == 2


def test_rule6_duplicate_terms_case_insensitive(repo):
    pattern = make_pattern(
        "cand-two",
        detector={"kind": "lexicon", "position": "any"},
        realizations={
            "en": {
                "terms": ["Delve", "tapestry", "delve"],
                "examples": {"positive": ["delve", "tapestry"], "negative": ["dig", "rug"]},
            },
            "de": {
                "terms": ["maßgeschneidert", "massgeschneidert"],
                "examples": {"positive": ["maßgeschneidert", "x maßgeschneidert"], "negative": ["a", "b"]},
            },
        },
    )
    repo.write_pattern(pattern)
    errs = messages(run(repo), "rule 6")
    assert len(errs) == 1 and "realizations.en.terms" in errs[0]


def test_rule7_realization_keys(repo):
    pattern = make_pattern("cand-two")
    pattern["realizations"]["EN"] = pattern["realizations"]["en"]
    repo.write_pattern(pattern)
    assert messages(run(repo), "rule 7: realization key 'EN'")


def test_rule8_file_name_and_directory(repo):
    repo.write_pattern(make_pattern("cand-two"), rel="patterns/text/wrong-name.yaml")
    repo.write_pattern(make_pattern("cand-three", modality="image"), rel="patterns/text/cand-three.yaml")
    report = run(repo)
    assert messages(report, "rule 8: file name must be 'cand-two.yaml'")
    assert messages(report, "rule 8: modality 'image'")


def test_payload_required_for_regex(repo):
    pattern = make_pattern("cand-two")
    pattern["realizations"]["en"].pop("patterns")
    repo.write_pattern(pattern)
    assert messages(run(repo), "lacks 'patterns'")


# ---------------------------------------------------------------------------
# cross-file rules


def test_duplicate_ids(repo):
    repo.write_pattern(make_pattern("cand-one"), rel="patterns/text/sub/cand-one.yaml")
    report = run(repo)
    assert messages(report, "duplicate pattern id 'cand-one'")


def test_related_must_resolve(repo):
    repo.write_pattern(make_pattern("cand-two", related=[{"id": "nowhere", "relation": "overlaps"}]))
    repo.write_pattern(make_pattern("cand-three", related=[{"id": "cand-one", "relation": "overlaps"}]))
    errs = messages(run(repo), "related")
    assert len(errs) == 1 and "'nowhere'" in errs[0]


def test_derived_from_must_resolve(repo):
    repo.write_source(make_source("src-c", derived_from=["ghost"]))
    assert messages(run(repo), "derived_from 'ghost'")


def test_source_clusters_and_count():
    sources = {
        "a": {"publisher": "X", "type": "blog"},
        "b": {"publisher": " x ", "type": "blog"},
        "c": {"derived_from": ["d"], "type": "blog"},
        "d": {"type": "press"},
        "e": {"type": "academic-preprint", "derived_from": ["d"]},
        "own": {"type": "own-observation"},
        "f": {"type": "blog"},
    }
    clusters = source_clusters(sources)
    assert clusters["a"] == clusters["b"]
    assert clusters["c"] == clusters["d"] == clusters["e"]
    assert clusters["f"] == "f"
    refs = [{"source": s} for s in ("a", "b", "c", "e", "own", "missing")]
    assert independent_source_count({"sources": refs}, sources) == 2
    refs.append({"source": "f"})
    assert independent_source_count({"sources": refs}, sources) == 3


# ---------------------------------------------------------------------------
# --changed-only


def test_changed_only_limits_per_file_but_keeps_cross_file(repo):
    bad = make_pattern("cand-two", category="nonsense", sources=[{"source": "src-a"}])
    repo.write_pattern(bad)
    full = run(repo)
    assert messages(full, "schema: category") and messages(full, "rule 2")
    limited = run(repo, changed=["patterns/text/cand-one.yaml"])
    assert not messages(limited, "schema: category")
    assert messages(limited, "rule 2")  # independence is a cross-file rule
    assert limited.checked_files == 1


def test_changed_only_governance_change_validates_everything(repo):
    repo.write_pattern(make_pattern("cand-two", category="nonsense"))
    report = run(repo, changed=["governance/thresholds.yaml"])
    assert messages(report, "schema: category")


def git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_changed_files_against_git_ref(repo):
    root = repo.root
    git(root, "init", "-q", "-b", "main")
    git(root, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init")
    repo.write_pattern(make_pattern("cand-one", name="Pattern changed"))
    repo.write_pattern(make_pattern("cand-new"))
    changed = changed_files("main", root)
    assert changed == {"patterns/text/cand-one.yaml", "patterns/text/cand-new.yaml"}


# ---------------------------------------------------------------------------
# static regex scan


@pytest.mark.parametrize(
    "rx",
    [
        r"(a+)+",
        r"(?:\w+\s?)*",
        r"(a{2,})*",
        r"((a)+b)*",
        r"(?:x|y+)+",
        r"(?P<n>\s*,\s*\w+)+$",
        r"(?i)(?:[^.]+\.)+",
    ],
)
def test_nested_quantifiers_found(rx):
    assert regex_safety.nested_quantifiers(rx)


@pytest.mark.parametrize(
    "rx",
    [
        r"(?:\w+\s){1,5}",
        r"[(+)]+",
        r"\(a+\)+",
        r"(?i)\bfoo+\b",
        r"(a{2,3})*",
        r"(?P<n>a+)?",
        r"a{,5}b{3}",
        r"(?i)\b(?:it[’']?s|it is)\s+not\s+(?:just|only)\b[^.!?\n]{1,80}?[,;:—–-]\s*(?:it[’']?s|but)\b",
        r"x{}+",
        r"(?#comment (a+)+)foo",
        r"[\]a+]+",
    ],
)
def test_nested_quantifiers_not_found(rx):
    assert regex_safety.nested_quantifiers(rx) == []


def test_time_patterns_reports_slow_and_restarts():
    inputs = {"letters": "a" * 5000 + "!"}
    items = [
        regex_safety.TimingItem(r"(a|aa)*b", ["letters"]),
        regex_safety.TimingItem(r"\ba\b", ["letters"]),
    ]
    results = regex_safety.time_patterns(items, inputs, limit_ms=50)
    assert results[0].problems(50)
    assert results[1].problems(50) == []
    assert "letters" in results[1].ms


# ---------------------------------------------------------------------------
# CLI


def test_cli_validate_exit_codes(repo, capsys):
    assert main(["validate", "--root", str(repo.root), "--no-regex-timing"]) == 0
    assert "0 error(s)" in capsys.readouterr().out
    repo.write_pattern(make_pattern("new-core", status="core"))
    assert main(["validate", "--root", str(repo.root), "--no-regex-timing"]) == 1
    err = capsys.readouterr().err
    assert "patterns/text/new-core.yaml: rule 1" in err


def test_academic_sources_cluster_by_authors_not_publisher():
    from slopcheck_dev.validate import source_clusters

    sources = {
        "paper-a": {"type": "academic-preprint", "publisher": "arXiv", "authors": ["A. One", "B. Two"]},
        "paper-b": {"type": "academic-preprint", "publisher": "arXiv", "authors": ["C. Three"]},
        "paper-c": {"type": "peer-reviewed", "publisher": "ACL", "authors": ["b. two"]},
        "blog-a": {"type": "blog", "publisher": "Same Blog"},
        "blog-b": {"type": "blog", "publisher": "same blog"},
    }
    clusters = source_clusters(sources)
    assert clusters["paper-a"] != clusters["paper-b"]
    assert clusters["paper-a"] == clusters["paper-c"]
    assert clusters["blog-a"] == clusters["blog-b"]
