"""slopcheck-dev build: catalog compilation, generated references, packaging, section 7."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from dev_helpers import REPO, make_pattern

from slopcheck_dev import build as build_mod
from slopcheck_dev.build import (
    CORE_CATALOG_END,
    CORE_CATALOG_START,
    MAX_DESCRIPTION_CHARS,
    MAX_FILES,
    MAX_INSTRUCTIONS_CHARS,
    MAX_LITE_COMPANION_FILES,
    MAX_SKILL_LINES,
    MAX_SKILL_TOKENS,
    BuildError,
    build,
    check_package,
    compile_catalog,
    formatting_problems,
    package_skill_md,
    parse_frontmatter,
    render_core_catalog,
    render_instructions,
    render_patterns_markdown,
    render_prevention_markdown,
    replace_marked_region,
    skill_size,
)
from slopcheck_dev.cli import main
from slopcheck_dev.status import pattern_hash

STAMP = "2026-11-17T12:00:00Z"
EPOCH = "1794916800"  # 2026-11-17T12:00:00Z


def lexicon_core() -> dict:
    return make_pattern(
        "core-two",
        status="core",
        name="Showy words",
        category="lexical",
        detector={"kind": "lexicon", "position": "any"},
        threshold={
            "min_count": 2,
            "short_text": {"min_count": 1},
            "context_overrides": {"informal": {"min_count": 3}},
        },
        realizations={
            "en": {
                "terms": ["delve", "tapestr*"],
                "examples": {
                    "positive": ["We delve in.", "A tapestry."],
                    "negative": ["Delving.", "A tape."],
                },
            }
        },
        prevention="Prefer plain verbs to showy ones.",
    )


def text_patterns() -> list[dict]:
    """Initial core weights 2.5 / 1.0 / 0.5, one candidate, one observation."""
    return [
        make_pattern("cand-one", category="rhetoric", prevention="Candidate rule."),
        make_pattern("core-one", status="core", name="Foo opener", prevention="Core rule one."),
        lexicon_core(),
        make_pattern(
            "core-three",
            status="core",
            category="attribution",
            requires={"min_other_findings": 3},
            prevention="Name the source.",
        ),
        make_pattern("obs-one", status="observation", detector=None, prevention="Observation rule."),
    ]


def image_pattern() -> dict:
    return make_pattern(
        "img-one",
        modality="image",
        name="Glow default",
        detector={"kind": "vision", "rubric": "Look for an orange glow on every edge."},
        realizations={"*": {}},
        prevention="Name the light source.",
    )


def web_patterns() -> list[dict]:
    """One visual and one source-judged web pattern."""
    return [
        make_pattern(
            "web-one",
            modality="web",
            name="Gradient default",
            category="web-visual-style",
            detector={"kind": "vision", "rubric": "Look for a purple gradient behind the hero."},
            realizations={"*": {}},
            prevention="Take the accent color from the brand.",
        ),
        make_pattern(
            "web-two",
            modality="web",
            name="Div soup",
            category="web-markup",
            detector={"kind": "llm", "rubric": "Look for pages without landmarks."},
            realizations={"*": {}},
            prevention="Use landmarks and a heading outline.",
        ),
    ]


def strip_none(pattern: dict) -> dict:
    return {k: v for k, v in pattern.items() if v is not None}


def by_id(catalog: dict) -> dict[str, dict]:
    return {p["id"]: p for p in catalog["patterns"]}


# ---------------------------------------------------------------------------
# compile_catalog


def test_compile_catalog_provisional_weights(thresholds):
    patterns = [strip_none(p) for p in text_patterns()]
    before = json.dumps(patterns, sort_keys=True)
    catalog = compile_catalog(patterns, None, thresholds, generated_at=STAMP)
    assert json.dumps(patterns, sort_keys=True) == before  # input untouched
    got = {pid: (p["effective_status"], p["weight"], p["weight_source"]) for pid, p in by_id(catalog).items()}
    assert got == {
        "cand-one": ("candidate", 0.0, "none"),
        "core-one": ("core", 2.5, "provisional"),
        "core-two": ("core", 1.0, "provisional"),
        "core-three": ("core", 0.5, "provisional"),
        "obs-one": ("observation", 0.0, "none"),
    }
    assert catalog["verdict_thresholds"] == {"yellow": 2.0, "red": 5.0, "source": "provisional"}
    assert catalog["catalog_version"] == "2026.11.17"
    assert catalog["generated_at"] == STAMP
    assert catalog["short_text_max_words"] == 150
    assert [p["id"] for p in catalog["patterns"]] == [
        "cand-one",
        "core-one",
        "core-three",
        "core-two",
        "obs-one",
    ]
    entry = by_id(catalog)["core-two"]
    source = strip_none(lexicon_core())
    assert {
        k: v for k, v in entry.items() if k not in ("effective_status", "weight", "weight_source")
    } == source


def test_compile_catalog_measured_weights_and_thresholds(thresholds):
    patterns = [strip_none(p) for p in text_patterns()]
    pats = {p["id"]: p for p in patterns}

    def m(pid, lift, meets_core=False, meets_fading=False):
        return {
            "pattern_hash": pattern_hash(pats[pid]),
            "lift": lift,
            "meets_core": meets_core,
            "meets_fading": meets_fading,
        }

    measurements = {
        "verdict_thresholds": {"yellow": 2.1, "red": 5.4},
        "patterns": {
            "core-one": m("core-one", math.e**1.5, meets_core=True),
            "core-two": m("core-two", 1000.0, meets_core=True),
            "core-three": m("core-three", 1.1, meets_fading=True),
            "cand-one": m("cand-one", 4.0, meets_core=True),
            "obs-one": m("obs-one", 50.0, meets_core=True),
        },
    }
    catalog = compile_catalog(patterns, measurements, thresholds, version="2026.12.01", generated_at=STAMP)
    got = {
        pid: (p["effective_status"], round(p["weight"], 3), p["weight_source"])
        for pid, p in by_id(catalog).items()
    }
    assert got == {
        "cand-one": ("core", round(math.log(4.0), 3), "measured"),
        "core-one": ("core", 1.5, "measured"),
        "core-two": ("core", 3.0, "measured"),  # ln 1000 clamped to weights.from_lift.max
        "core-three": ("fading", 0.0, "none"),
        "obs-one": ("observation", 0.0, "none"),
    }
    assert catalog["verdict_thresholds"] == {"yellow": 2.1, "red": 5.4, "source": "measured"}
    assert catalog["catalog_version"] == "2026.12.01"


def test_compile_catalog_ignores_stale_measurement(thresholds):
    pattern = make_pattern("core-one", status="core")
    stale = {"patterns": {"core-one": {"pattern_hash": "0" * 64, "lift": 1.0, "meets_fading": True}}}
    entry = by_id(compile_catalog([pattern], stale, thresholds, generated_at=STAMP))["core-one"]
    assert (entry["effective_status"], entry["weight"], entry["weight_source"]) == (
        "core",
        2.5,
        "provisional",
    )


def test_compile_catalog_generated_at_from_source_date_epoch(thresholds, monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", EPOCH)
    catalog = compile_catalog([make_pattern("cand-one")], None, thresholds)
    assert catalog["generated_at"] == STAMP
    assert catalog["catalog_version"] == "2026.11.17"


def test_catalog_runs_in_engine(thresholds):
    from slopcheck.engine import analyze

    catalog = compile_catalog(text_patterns(), None, thresholds, generated_at=STAMP)
    result = analyze("A foo walks in. We delve into a tapestry of things.", catalog, lang="en")
    assert [f["pattern_id"] for f in result["findings"]] == ["core-one", "core-two"]
    assert result["score"] == 3.5
    assert result["verdict"] == "YELLOW"
    assert [o["pattern_id"] for o in result["observations"]] == ["cand-one"]


# ---------------------------------------------------------------------------
# generated references


def catalog_with_fading(thresholds) -> dict:
    patterns = [*text_patterns(), make_pattern("core-fade", status="core"), image_pattern()]
    thresholds["initial_core"]["core-fade"] = 1.0
    fade = next(p for p in patterns if p["id"] == "core-fade")
    measurements = {
        "patterns": {"core-fade": {"pattern_hash": pattern_hash(fade), "lift": 1.0, "meets_fading": True}}
    }
    return compile_catalog(patterns, measurements, thresholds, generated_at=STAMP)


def headings(markdown: str) -> list[str]:
    return re.findall(r"^### .*\(`([^`]+)`\)$", markdown, flags=re.MULTILINE)


def test_text_patterns_order_and_groups(thresholds):
    md = render_patterns_markdown(catalog_with_fading(thresholds), "text")
    assert headings(md) == ["core-one", "core-two", "core-three", "cand-one", "core-fade"]
    assert "obs-one" not in md and "img-one" not in md
    groups = re.findall(r"^## (.*)$", md, flags=re.MULTILINE)
    assert groups == [
        "Index",
        "Scored patterns",
        "Candidates (observed, weight 0)",
        "Fading patterns (observed, weight 0)",
    ]
    index = [line for line in md.splitlines() if line.startswith("| ") and "`" in line]
    assert index[0] == "| Foo opener | `core-one` | core | 2.5 |"
    assert index[-1] == "| Pattern core-fade | `core-fade` | fading | 0 |"
    assert "YELLOW starts at 2, RED at 5 (provisional thresholds)" in md
    assert "A text with at most 150 words counts as short." in md


def test_text_pattern_section_contents(thresholds):
    md = render_patterns_markdown(catalog_with_fading(thresholds), "text")
    section = md.split("### Showy words (`core-two`)")[1].split("\n### ")[0]
    assert "Status: core, weight 1 (provisional weight, not yet measured). Category: Word choice." in section
    assert "A summary that is long enough for the schema." in section
    assert "Detection: Word list, anywhere in the text." in section
    assert "Threshold: min 2 per text." in section
    assert "Short texts: min 1 per text." in section
    assert "Context informal: min 3 per text." in section
    assert "Terms (en): `delve`, `tapestr*`." in section
    assert "Example hits (en):\n\n- `We delve in.`\n- `A tapestry.`" in section
    assert "Not a hit (en):\n\n- `Delving.`\n- `A tape.`" in section
    assert "Legitimate use: Quoting the word itself." in section
    assert "Fix: Remove the foo." in section
    core_three = md.split("(`core-three`)")[1].split("\n### ")[0]
    assert "Counts only when at least 3 other scored patterns are triggered as well." in core_three
    candidate = md.split("(`cand-one`)")[1].split("\n### ")[0]
    assert "Status: candidate, weight 0; report it under observations only." in candidate
    assert "Detection: Phrase match, anywhere in the text." in candidate


def test_image_patterns_reference(thresholds):
    md = render_patterns_markdown(catalog_with_fading(thresholds), "image")
    assert md.startswith("# Image pattern catalog\n")
    assert headings(md) == ["img-one"]
    assert "Detection: Visual judgment: Look for an orange glow on every edge." in md
    assert "Threshold: min 1 per image." in md
    empty = render_patterns_markdown(compile_catalog([], None, thresholds, generated_at=STAMP), "image")
    assert "No patterns of this modality are in the catalog yet." in empty


def test_prevention_rules_grouped_by_category(thresholds):
    catalog = catalog_with_fading(thresholds)
    md = render_prevention_markdown(catalog, "text")
    groups = re.findall(r"^## (.*)$", md, flags=re.MULTILINE)
    assert groups == ["Rhetoric", "Word choice", "Attribution"]
    rhetoric = md.split("## Rhetoric")[1].split("## Word choice")[0]
    rules = [line for line in rhetoric.splitlines() if line.startswith("- ")]
    assert rules == [
        "- Core rule one. (`core-one`)",
        "- Candidate rule. (`cand-one`)",
    ]  # core before candidate
    assert "Observation rule." not in md  # observations omitted
    assert "core-fade" not in md  # fading omitted
    image = render_prevention_markdown(catalog, "image")
    assert "## Visual style\n\n- Name the light source. (`img-one`)" in image
    none = render_prevention_markdown(compile_catalog([], None, thresholds, generated_at=STAMP), "image")
    assert "No prevention rules for this modality yet." in none


def test_core_catalog_names_web_pattern_ids(thresholds):
    patterns = [*text_patterns(), image_pattern(), *web_patterns()]
    region = render_core_catalog(compile_catalog(patterns, None, thresholds, generated_at=STAMP))
    expected = "Web page patterns (weight 0, observations only): `web-one`, `web-two`."
    assert region.rstrip("\n").endswith(expected)
    assert "img-one" not in region
    without = render_core_catalog(compile_catalog(text_patterns(), None, thresholds, generated_at=STAMP))
    assert "Web page patterns" not in without


def test_web_patterns_reference_and_prevention(thresholds):
    catalog = compile_catalog([*text_patterns(), *web_patterns()], None, thresholds, generated_at=STAMP)
    md = render_patterns_markdown(catalog, "web")
    assert md.startswith("# Web page pattern catalog\n")
    assert headings(md) == ["web-one", "web-two"]
    assert "Use this file to audit web pages" in md
    assert "Detection: Visual judgment: Look for a purple gradient behind the hero." in md
    assert "Detection: Source judgment (HTML, CSS or component code): Look for pages without landmarks." in md
    assert "Threshold: min 1 per page." in md
    assert "Category: Page styling." in md
    assert "cand-one" not in md  # text patterns stay in text-patterns.md
    rules = render_prevention_markdown(catalog, "web")
    assert "Apply these rules while building or styling web pages" in rules
    assert "`references/web-patterns.md`" in rules
    groups = re.findall(r"^## (.*)$", rules, flags=re.MULTILINE)
    assert groups == ["Page styling", "Markup and behaviour"]
    assert "- Take the accent color from the brand. (`web-one`)" in rules


def test_generated_markdown_is_deterministic_and_clean(thresholds):
    first = catalog_with_fading(thresholds)
    catalog_fields = ("effective_status", "weight", "weight_source")
    patterns = [{k: v for k, v in p.items() if k not in catalog_fields} for p in reversed(first["patterns"])]
    fade = next(p for p in patterns if p["id"] == "core-fade")
    measurements = {
        "patterns": {"core-fade": {"pattern_hash": pattern_hash(fade), "lift": 1.0, "meets_fading": True}}
    }
    second = compile_catalog(patterns, measurements, thresholds, generated_at=STAMP)
    assert by_id(second)["core-fade"]["effective_status"] == "fading"
    for render in (render_patterns_markdown, render_prevention_markdown):
        for modality in ("text", "image", "web"):
            a, b = render(first, modality), render(second, modality)
            assert a == b
            assert formatting_problems(a) == []
            assert a.endswith("\n") and not a.endswith("\n\n")


def test_formatting_problems_detects_slop_formatting():
    md = "- **Lead**: text\n1. __Lead__ text\n- plain item\nDone ✅\nKeep `✅` in code.\n"
    problems = formatting_problems(md)
    assert problems == [
        "line 1: list item with a bold lead",
        "line 2: list item with a bold lead",
        "line 4: emoji outside a code span",
    ]


# ---------------------------------------------------------------------------
# build()


@pytest.fixture
def skill_repo(repo):
    """Mini repository with skill files, the engine and text plus image patterns."""
    repo.add_skill()
    repo.add_engine()
    for pattern in (*text_patterns(), image_pattern(), *web_patterns()):
        repo.write_pattern(strip_none(pattern))
    return repo


def package_files(pkg: Path) -> set[str]:
    return {p.relative_to(pkg).as_posix() for p in pkg.rglob("*") if p.is_file()}


def test_build_writes_package_zip_and_export(skill_repo, tmp_path):
    result = build(tmp_path / "out", root=skill_repo.root)
    pkg = tmp_path / "out" / "slop-check"
    assert result.package_dir == pkg
    engine = {f"scripts/slopcheck/{p.name}" for p in (skill_repo.root / "src" / "slopcheck").glob("*.py")}
    references = {
        f"references/{n}"
        for n in (
            "audit-procedure.md",
            "report-format.md",
            "rewrite-procedure.md",
            "prevention-procedure.md",
            "text-patterns.md",
            "image-patterns.md",
            "web-patterns.md",
            "prevention-rules-text.md",
            "prevention-rules-image.md",
            "prevention-rules-web.md",
        )
    }
    assert (
        package_files(pkg)
        == {"SKILL.md", "scripts/catalog.json", "scripts/slopcheck.py"} | references | engine
    )
    source = (skill_repo.root / "skill" / "SKILL.md").read_text(encoding="utf-8")
    packaged = (pkg / "SKILL.md").read_text(encoding="utf-8")
    assert packaged == replace_marked_region(source, render_core_catalog(result.catalog))
    assert result.skill_size == skill_size(packaged)
    assert result.warnings == []

    from slopcheck.catalog import load_catalog

    catalog = load_catalog(str(pkg / "scripts" / "catalog.json"))
    assert catalog == result.catalog
    assert {p["id"] for p in catalog["patterns"]} == {
        "cand-one",
        "core-one",
        "core-two",
        "core-three",
        "obs-one",
        "img-one",
        "web-one",
        "web-two",
    }

    with zipfile.ZipFile(result.zip_path) as zf:
        names = zf.namelist()
    assert result.zip_path == tmp_path / "out" / "slop-check.zip"
    assert all(n.startswith("slop-check/") for n in names)
    assert {n[len("slop-check/") :] for n in names if not n.endswith("/")} == package_files(pkg)
    assert not any("__pycache__" in n or n.endswith(".pyc") for n in names)

    export = result.export_path.read_text(encoding="utf-8")
    assert result.export_path == tmp_path / "out" / "exports" / "system-prompt.md"
    assert export.startswith("# slop-check (compact system prompt)\n")
    knowledge = (tmp_path / "out" / "exports" / "knowledge.md").read_text(encoding="utf-8")
    assert knowledge.startswith("# slop-check (single-file export)\n")
    assert "Follow the audit procedure." in export
    assert "name: slop-check" not in export  # frontmatter stripped
    order = [m.group(1) for m in re.finditer(r"^# File: references/(\S+)$", knowledge, flags=re.MULTILINE)]
    assert order == [
        "audit-procedure.md",
        "report-format.md",
        "rewrite-procedure.md",
        "prevention-procedure.md",
        "text-patterns.md",
        "image-patterns.md",
        "web-patterns.md",
        "prevention-rules-text.md",
        "prevention-rules-image.md",
        "prevention-rules-web.md",
    ]


def test_build_writes_flat_zip_with_skill_md_at_the_root(skill_repo, tmp_path):
    result = build(tmp_path / "out", root=skill_repo.root)
    pkg = result.package_dir
    assert result.flat_zip_path == tmp_path / "out" / "slop-check-flat.zip"
    with zipfile.ZipFile(result.flat_zip_path) as zf:
        names = zf.namelist()
        assert zf.read("SKILL.md") == (pkg / "SKILL.md").read_bytes()
        assert zf.read("scripts/catalog.json") == (pkg / "scripts" / "catalog.json").read_bytes()
    assert "SKILL.md" in names
    assert not any(n.startswith("slop-check/") for n in names)
    assert {n for n in names if not n.endswith("/")} == package_files(pkg)
    assert not any("__pycache__" in n or n.endswith(".pyc") for n in names)


def test_flat_zip_is_deterministic(skill_repo, tmp_path, monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", EPOCH)
    a = build(tmp_path / "a", root=skill_repo.root)
    b = build(tmp_path / "b", root=skill_repo.root)
    assert a.flat_zip_path.read_bytes() == b.flat_zip_path.read_bytes()


def test_bundled_shim_runs_offline_without_the_repository(skill_repo, tmp_path):
    result = build(tmp_path / "out", root=skill_repo.root)
    sample = tmp_path / "sample.txt"
    sample.write_text("A foo walks in. We delve into a tapestry of things.\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k not in ("SLOPCHECK_CATALOG", "PYTHONPATH")}
    proc = subprocess.run(
        [
            sys.executable,
            "-I",
            str(result.package_dir / "scripts" / "slopcheck.py"),
            "audit",
            str(sample),
            "--format",
            "json",
            "--lang",
            "en",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["catalog_version"] == result.catalog["catalog_version"]
    assert [f["pattern_id"] for f in data["findings"]] == ["core-one", "core-two"]


def test_build_is_deterministic(skill_repo, tmp_path, monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", EPOCH)
    a = build(tmp_path / "a", root=skill_repo.root)
    b = build(tmp_path / "b", root=skill_repo.root)
    assert a.zip_path.read_bytes() == b.zip_path.read_bytes()
    assert a.export_path.read_bytes() == b.export_path.read_bytes()
    assert a.catalog["generated_at"] == STAMP


def test_build_replaces_previous_package(skill_repo, tmp_path):
    stale = tmp_path / "out" / "slop-check" / "references" / "old-name.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("old\n", encoding="utf-8")
    build(tmp_path / "out", root=skill_repo.root)
    assert not stale.exists()


def test_build_fails_without_skill_md(repo, tmp_path, capsys):
    repo.add_engine()
    with pytest.raises(BuildError, match=r"skill/SKILL\.md not found"):
        build(tmp_path / "out", root=repo.root)
    assert main(["build", "--root", str(repo.root), "--out", str(tmp_path / "out")]) == 1
    assert "skill/SKILL.md not found" in capsys.readouterr().err
    assert not (tmp_path / "out" / "slop-check.zip").exists()


@pytest.mark.parametrize(
    ("frontmatter", "message"),
    [
        ("---\nname: Slop Check\ndescription: Checks style.\n---\n", "frontmatter name must be 'slop-check'"),
        ("---\nname: slop-check\n---\n", "description missing or empty"),
        ("---\nname: slop-check\ndescription: '  '\n---\n", "description missing or empty"),
        ("", "frontmatter (--- name / description ---) missing or invalid"),
        ("---\nname: [unclosed\n---\n", "missing or invalid"),
    ],
)
def test_build_checks_skill_frontmatter(repo, tmp_path, frontmatter, message):
    repo.add_engine()
    repo.add_skill(frontmatter=frontmatter)
    with pytest.raises(BuildError, match=re.escape(message)):
        build(tmp_path / "out", root=repo.root)


def test_build_rejects_skill_description_over_200_characters(repo, tmp_path, capsys):
    repo.add_engine()
    repo.add_skill(frontmatter=f"---\nname: slop-check\ndescription: {'x' * 201}\n---\n")
    with pytest.raises(BuildError, match="description has 201 characters, at most 200 are allowed"):
        build(tmp_path / "out", root=repo.root)
    assert main(["build", "--root", str(repo.root), "--out", str(tmp_path / "out")]) == 1
    assert "at most 200" in capsys.readouterr().err
    assert not (tmp_path / "out" / "slop-check.zip").exists()
    assert not (tmp_path / "out" / "slop-check-flat.zip").exists()


def test_build_accepts_skill_description_of_exactly_200_characters(repo, tmp_path):
    repo.add_engine()
    # a folded block scalar ends with a newline that is not part of the description's length
    repo.add_skill(frontmatter=f"---\nname: slop-check\ndescription: >\n  {'y' * 200}\n---\n")
    result = build(tmp_path / "out", root=repo.root)
    assert result.flat_zip_path.is_file()


def test_build_rejects_handwritten_file_with_generated_name(skill_repo, tmp_path):
    (skill_repo.root / "skill" / "references" / "text-patterns.md").write_text("# hand\n", encoding="utf-8")
    with pytest.raises(BuildError, match="clashes with a generated reference"):
        build(tmp_path / "out", root=skill_repo.root)


def test_build_warns_on_missing_reference_and_keeps_extras(repo, tmp_path):
    repo.add_engine()
    repo.add_skill(
        references={
            "audit-procedure.md": "# Audit\n",
            "report-format.md": "# Report\n",
            "rewrite-procedure.md": "# Rewrite\n",
            "scripts-usage.md": "# Scripts\n",
        }
    )
    result = build(tmp_path / "out", root=repo.root)
    assert result.warnings == ["hand-written references missing: prevention-procedure.md"]
    assert (result.package_dir / "references" / "scripts-usage.md").is_file()
    knowledge = (result.export_path.parent / "knowledge.md").read_text(encoding="utf-8")
    order = re.findall(r"^# File: references/(\S+)$", knowledge, flags=re.MULTILINE)
    assert (
        order.index("rewrite-procedure.md")
        < order.index("scripts-usage.md")
        < order.index("text-patterns.md")
    )
    compact = result.export_path.read_text(encoding="utf-8")
    assert "# File: references/report-format.md" in compact
    assert "(condensed)" in compact
    assert len(compact) < len(knowledge)


def test_build_enforces_section_7_on_engine_files(skill_repo, tmp_path):
    (skill_repo.root / "src" / "slopcheck" / "data.bin").write_bytes(b"\x00\x01")
    with pytest.raises(BuildError, match=r"package violates section 7:\n  scripts/slopcheck/data\.bin"):
        build(tmp_path / "out", root=skill_repo.root)
    assert not (tmp_path / "out" / "slop-check.zip").exists()


def test_build_skips_caches_and_stray_catalog(skill_repo, tmp_path):
    engine = skill_repo.root / "src" / "slopcheck"
    (engine / "__pycache__").mkdir()
    (engine / "__pycache__" / "engine.cpython-313.pyc").write_bytes(b"x")
    (engine / ".hidden.py").write_text("x = 1\n", encoding="utf-8")
    (engine / "catalog.json").write_text("{}", encoding="utf-8")
    result = build(tmp_path / "out", root=skill_repo.root)
    files = package_files(result.package_dir)
    assert not any(
        "__pycache__" in f or ".hidden" in f or f == "scripts/slopcheck/catalog.json" for f in files
    )
    assert any("catalog.json not copied" in w for w in result.warnings)


def test_build_with_measurements(skill_repo, tmp_path):
    pattern = make_pattern("core-one", status="core", name="Foo opener", prevention="Core rule one.")
    measurements = tmp_path / "measurements.json"
    measurements.write_text(
        json.dumps(
            {
                "verdict_thresholds": {"yellow": 2.2, "red": 5.1},
                "patterns": {
                    "core-one": {"pattern_hash": pattern_hash(pattern), "lift": math.e**2, "meets_core": True}
                },
            }
        ),
        encoding="utf-8",
    )
    result = build(
        tmp_path / "out", measurements_path=measurements, version="2026.12.01", root=skill_repo.root
    )
    entry = by_id(result.catalog)["core-one"]
    assert (entry["weight"], entry["weight_source"]) == (2.0, "measured")
    assert result.catalog["verdict_thresholds"]["source"] == "measured"
    assert result.catalog["catalog_version"] == "2026.12.01"
    text = (result.package_dir / "references" / "text-patterns.md").read_text(encoding="utf-8")
    assert "Status: core, weight 2 (measured on the reference corpora)." in text
    assert "YELLOW starts at 2.2, RED at 5.1 (measured thresholds)" in text
    measurements.write_text("{not json", encoding="utf-8")
    with pytest.raises(BuildError, match="cannot read measurements"):
        build(tmp_path / "out2", measurements_path=measurements, root=skill_repo.root)


def test_cli_build(skill_repo, tmp_path, capsys):
    out = tmp_path / "dist"
    code = main(["build", "--root", str(skill_repo.root), "--out", str(out), "--version", "2026.12.01"])
    assert code == 0
    stdout = capsys.readouterr().out
    assert "build: catalog 2026.12.01 (candidate 4, core 3, observation 1)" in stdout
    assert (out / "slop-check.zip").is_file() and (out / "exports" / "system-prompt.md").is_file()
    assert (out / "slop-check-flat.zip").is_file() and (out / "slop-check-lite.zip").is_file()
    assert (out / "exports" / "instructions.md").is_file()
    assert re.search(
        r"build: SKILL\.md \d+ lines, \d+ characters, about \d+ tokens \(limits 500 lines", stdout
    )
    assert re.search(r"build: instructions\.md \d+ characters \(limit 7500\)", stdout)


# ---------------------------------------------------------------------------
# core catalog in SKILL.md (section 7: the packaged SKILL.md suffices on its own)


def core_region(text: str) -> str:
    return text.split(CORE_CATALOG_START + "\n", 1)[1].split("\n" + CORE_CATALOG_END, 1)[0]


def test_render_core_catalog_lists_core_patterns_thresholds_and_candidate_ids(thresholds):
    catalog = catalog_with_fading(thresholds)
    region = render_core_catalog(catalog)
    assert region.startswith(
        "Catalog 2026.11.17. Verdict: a score below 2.0 is GREEN, from 2.0 YELLOW, from 5.0 RED "
        "(provisional thresholds). A short text has at most 150 words.\n"
    )
    assert "The weights are provisional, so every report carries the provisional-weights note." in region
    lines = {
        re.match(r"- `([^`]+)`", line).group(1): line
        for line in region.splitlines()
        if line.startswith("- `")
    }
    assert list(lines) == ["core-one", "core-two", "core-three"]  # weight order, core only
    assert lines["core-one"] == (
        "- `core-one` Foo opener, weight 2.5. Phrase; threshold min 1 per text. en: `foo`, `Foo`."
    )
    assert lines["core-two"] == (
        "- `core-two` Showy words, weight 1.0. Listed words; threshold min 2 per text "
        "(short texts: min 1 per text; informal: min 3 per text). en: `delve`, `tapestr*`."
    )
    assert "threshold min 1 per text; only with 3 other findings." in lines["core-three"]
    assert "Candidates (weight 0, observations only): `cand-one`." in region
    assert "Fading (weight 0, observations only): `core-fade`." in region
    assert "obs-one" not in region and "img-one" not in region
    assert "Example" not in region.split("Candidates")[1]  # candidates are IDs only
    assert formatting_problems(region) == []
    assert "`foo`" not in render_core_catalog(catalog, examples=0)


def test_render_core_catalog_with_measured_weights(thresholds):
    pattern = make_pattern("core-one", status="core", name="Foo opener")
    measurements = {
        "verdict_thresholds": {"yellow": 2.1, "red": 5.4},
        "patterns": {
            "core-one": {"pattern_hash": pattern_hash(pattern), "lift": math.e**2, "meets_core": True}
        },
    }
    region = render_core_catalog(compile_catalog([pattern], measurements, thresholds, generated_at=STAMP))
    assert "from 2.1 YELLOW, from 5.4 RED (measured thresholds)" in region
    assert "All weights are measured, so reports carry no provisional-weights note." in region
    assert "- `core-one` Foo opener, weight 2.0." in region
    empty = render_core_catalog(compile_catalog([], None, thresholds, generated_at=STAMP))
    assert "No scored patterns yet: every text audit is GREEN." in empty


def test_build_injects_core_catalog_into_packaged_skill_md(skill_repo, tmp_path):
    source = (skill_repo.root / "skill" / "SKILL.md").read_text(encoding="utf-8")
    result = build(tmp_path / "out", root=skill_repo.root)
    packaged = (result.package_dir / "SKILL.md").read_text(encoding="utf-8")
    assert "(Filled in by the build.)" not in packaged
    assert packaged.count(CORE_CATALOG_START) == 1 and packaged.count(CORE_CATALOG_END) == 1
    region = core_region(packaged)
    core_ids = [p["id"] for p in result.catalog["patterns"] if p["effective_status"] == "core"]
    assert core_ids and all(f"`{pid}`" in region for pid in core_ids)
    assert "a score below 2.0 is GREEN, from 2.0 YELLOW, from 5.0 RED" in region
    before, after = source.split("(Filled in by the build.)")
    assert packaged.startswith(before) and packaged.endswith(after)  # only the region changes
    assert (skill_repo.root / "skill" / "SKILL.md").read_text(encoding="utf-8") == source


@pytest.mark.parametrize(
    "body",
    [
        "# Skill\n\nNo markers.\n",
        f"# Skill\n\n{CORE_CATALOG_START}\nno end marker\n",
        f"# Skill\n\n{CORE_CATALOG_END}\nreversed\n{CORE_CATALOG_START}\n",
        f"# Skill\n\n{CORE_CATALOG_START}\n{CORE_CATALOG_END}\n{CORE_CATALOG_START}\n{CORE_CATALOG_END}\n",
    ],
)
def test_build_requires_one_pair_of_core_catalog_markers(skill_repo, tmp_path, body):
    skill_md = skill_repo.root / "skill" / "SKILL.md"
    frontmatter = skill_md.read_text(encoding="utf-8").split("---\n", 2)
    skill_md.write_text(f"---\n{frontmatter[1]}---\n{body}", encoding="utf-8")
    with pytest.raises(BuildError, match="needs exactly one line '<!-- slopcheck:core-catalog -->'"):
        build(tmp_path / "out", root=skill_repo.root)


def test_skill_md_size_budget_drops_typical_hits_then_fails(skill_repo, tmp_path, monkeypatch, thresholds):
    patterns = [*text_patterns(), image_pattern(), *web_patterns()]  # the patterns of skill_repo
    catalog = compile_catalog(patterns, None, thresholds, generated_at=STAMP)
    source = (skill_repo.root / "skill" / "SKILL.md").read_text(encoding="utf-8")
    full = replace_marked_region(source, render_core_catalog(catalog, 2))
    bare = replace_marked_region(source, render_core_catalog(catalog, 0))
    assert skill_size(bare)["tokens"] < skill_size(full)["tokens"]
    text, size, warnings = package_skill_md(source, catalog)
    assert (text, warnings) == (full, []) and size == skill_size(full)
    # a budget between the smallest and the full catalog: fewer typical hits and a warning
    monkeypatch.setattr(build_mod, "MAX_SKILL_TOKENS", skill_size(full)["tokens"] - 1)
    text, _size, warnings = package_skill_md(source, catalog)
    assert text != full and len(warnings) == 1 and "typical hits per language instead of 2" in warnings[0]
    result = build(tmp_path / "out", root=skill_repo.root)
    assert any("typical hits per language" in w for w in result.warnings)
    # below the smallest catalog the build fails before anything is zipped
    monkeypatch.setattr(build_mod, "MAX_SKILL_TOKENS", skill_size(bare)["tokens"] - 1)
    with pytest.raises(BuildError, match=r"Shorten the hand-written text of skill/SKILL\.md"):
        build(tmp_path / "out2", root=skill_repo.root)
    assert not (tmp_path / "out2" / "slop-check.zip").exists()
    monkeypatch.setattr(build_mod, "MAX_SKILL_TOKENS", 10**6)
    monkeypatch.setattr(build_mod, "MAX_SKILL_LINES", skill_size(bare)["lines"] - 1)
    with pytest.raises(BuildError, match="lines"):
        package_skill_md(source, catalog)


def test_skill_size_estimates_tokens():
    assert skill_size("abcd\nefgh\n") == {"lines": 2, "chars": 10, "tokens": 3}
    assert skill_size("") == {"lines": 0, "chars": 0, "tokens": 0}


def copy_real_skill(repo) -> str:
    """Replace the mini repository's skill/ with the repository's real SKILL.md and references."""
    import shutil

    target = repo.root / "skill"
    shutil.rmtree(target)
    shutil.copytree(REPO / "skill", target)
    return (target / "SKILL.md").read_text(encoding="utf-8")


def test_real_skill_md_packages_self_sufficient_and_within_limits(skill_repo, tmp_path):
    source = copy_real_skill(skill_repo)
    assert source.count(CORE_CATALOG_START) == 1 and source.count(CORE_CATALOG_END) == 1
    assert core_region(source) == "(Filled in by `slopcheck-dev build` from the pattern catalog.)"
    result = build(tmp_path / "out", root=skill_repo.root)
    pkg = result.package_dir
    assert check_package(pkg) == ([], [])
    packaged = (pkg / "SKILL.md").read_text(encoding="utf-8")
    meta, _ = parse_frontmatter(packaged)
    source_meta, _ = parse_frontmatter(source)
    assert meta["description"] == source_meta["description"]
    assert len(meta["description"].strip()) <= MAX_DESCRIPTION_CHARS
    size = skill_size(packaged)
    assert size["lines"] <= MAX_SKILL_LINES and size["tokens"] <= MAX_SKILL_TOKENS
    region = core_region(packaged)
    for p in result.catalog["patterns"]:
        if p["effective_status"] == "core" and p.get("modality", "text") == "text":
            assert f"- `{p['id']}`" in region
    # the report skeleton in SKILL.md matches the layouts of report-format.md
    report_format = (REPO / "skill" / "references" / "report-format.md").read_text(encoding="utf-8")
    layouts = report_format.split("## Audit report in Markdown")[1].split("### Line by line")[0]
    headings = re.findall(r"^## .+$", layouts, flags=re.MULTILINE)
    assert len(headings) == 8
    for heading in headings:
        assert heading in packaged.replace("<candidate|fading>", "<status>"), heading
    for label in ("Verdict: <", "Gesamtbefund: <", "Suggestion: <", "Vorschlag: <"):
        assert label in packaged
    for note in re.findall(
        r"`((?:Some weights|Einige Gewichte|Findings describe|Die Befunde)[^`]+)`", report_format
    ):
        assert " ".join(note.split()) in packaged
    # the script is optional and the manual audit comes first
    assert packaged.index("works fully without code") < packaged.index("scripts/slopcheck.py")
    assert "Optional: if `scripts/slopcheck.py` exists" in packaged


def test_compact_export_lists_the_core_patterns_once(skill_repo, tmp_path):
    result = build(tmp_path / "out", root=skill_repo.root)
    export = result.export_path.read_text(encoding="utf-8")
    assert "In this single-file export, the scored patterns" in export
    assert "Each line: ID, name, weight" not in export  # the inline list is not repeated
    for pid in ("core-one", "core-two", "core-three"):
        assert len(re.findall(rf"^- `{pid}`", export, flags=re.MULTILINE)) == 1
    knowledge = (result.export_path.parent / "knowledge.md").read_text(encoding="utf-8")
    assert "Each line: ID, name, weight" in knowledge  # the package body keeps its inline list
    assert "## Web page patterns" in export
    assert re.search(r"^- `web-one` Gradient default \(candidate, weight 0\)\.", export, flags=re.MULTILINE)


# ---------------------------------------------------------------------------
# lite archive and instruction export


def test_build_writes_lite_zip_without_scripts(skill_repo, tmp_path):
    copy_real_skill(skill_repo)
    result = build(tmp_path / "out", root=skill_repo.root)
    assert result.lite_zip_path == tmp_path / "out" / "slop-check-lite.zip"
    with zipfile.ZipFile(result.lite_zip_path) as zf:
        files = sorted(n for n in zf.namelist() if not n.endswith("/"))
        skill = zf.read("SKILL.md")
    assert skill == (result.package_dir / "SKILL.md").read_bytes()
    assert CORE_CATALOG_START.encode() in skill and b"Gesamtbefund: <" in skill
    expected = {
        f"references/{p.name}"
        for p in (result.package_dir / "references").glob("*.md")
        if p.name != "scripts-usage.md"
    }
    assert set(files) == {"SKILL.md"} | expected
    assert not any(n.startswith(("scripts/", "slop-check/")) for n in files)
    assert len(files) - 1 <= MAX_LITE_COMPANION_FILES


def test_check_package_lite_rules(tmp_path):
    pkg = make_pkg(tmp_path)
    assert check_package(pkg, lite=True) == ([], [])
    for i in range(MAX_LITE_COMPANION_FILES):  # with references/a.md: one more than allowed
        (pkg / "references" / f"extra-{i}.md").write_text("# X\n", encoding="utf-8")
    errors, _ = check_package(pkg, lite=True)
    assert errors == [
        f"lite package holds 21 files besides SKILL.md; at most {MAX_LITE_COMPANION_FILES} are allowed"
    ]
    assert check_package(pkg) == ([], [])  # the full package has no such limit
    (pkg / "references" / "extra-0.md").unlink()
    (pkg / "scripts").mkdir()
    errors, _ = check_package(pkg, lite=True)
    assert errors == ["lite package must not contain scripts/"]


def test_build_fails_when_lite_package_breaks_its_limit(skill_repo, tmp_path):
    refs = skill_repo.root / "skill" / "references"
    for i in range(MAX_LITE_COMPANION_FILES):
        (refs / f"extra-{i}.md").write_text("# Extra\n", encoding="utf-8")
    with pytest.raises(BuildError, match="lite package violates section 7"):
        build(tmp_path / "out", root=skill_repo.root)


def test_instructions_export_fits_an_instruction_field(skill_repo, tmp_path):
    copy_real_skill(skill_repo)
    result = build(tmp_path / "out", root=skill_repo.root)
    text = result.instructions_path.read_text(encoding="utf-8")
    assert result.instructions_path == tmp_path / "out" / "exports" / "instructions.md"
    assert len(text) <= MAX_INSTRUCTIONS_CHARS
    assert "never authorship" in text and "never with a free-form review" in text
    assert "Below 2.0 is GREEN, from 2.0 YELLOW, from 5.0 RED" in text
    assert "Verdict: <GREEN|YELLOW|RED> (score <score>; yellow from 2.0, red from 5.0)" in text
    for pid in ("core-one", "core-two", "core-three"):
        assert len(re.findall(rf"^- `{pid}` ", text, flags=re.MULTILINE)) == 1
    assert "cand-one" not in text and "core-fade" not in text and "obs-one" not in text
    assert text.rstrip().endswith("and the detailed procedures.") and "knowledge.md" in text
    assert "- `core-two` Showy words, 1.0, min 2 per text" in text


def test_instructions_export_limit_is_enforced(skill_repo, tmp_path, monkeypatch, thresholds):
    catalog = compile_catalog(text_patterns(), None, thresholds, generated_at=STAMP)
    full, bare = render_instructions(catalog, 3), render_instructions(catalog, 0)
    assert len(bare) < len(full)
    monkeypatch.setattr(build_mod, "MAX_INSTRUCTIONS_CHARS", len(full) - 1)
    result = build(tmp_path / "out", root=skill_repo.root)
    assert any("key phrases per pattern instead of 3" in w for w in result.warnings)
    assert len(result.instructions_path.read_text(encoding="utf-8")) < len(full)
    monkeypatch.setattr(build_mod, "MAX_INSTRUCTIONS_CHARS", len(bare) - 1)
    with pytest.raises(BuildError, match=r"instructions\.md has \d+ characters without key phrases"):
        build(tmp_path / "out2", root=skill_repo.root)


# ---------------------------------------------------------------------------
# check_package (section 7)


def make_pkg(base: Path, name: str = "slop-check") -> Path:
    pkg = base / name
    (pkg / "references").mkdir(parents=True)
    (pkg / "SKILL.md").write_text(
        "---\nname: slop-check\ndescription: Style check.\n---\n# Body\n", encoding="utf-8"
    )
    (pkg / "references" / "a.md").write_text("# A\n", encoding="utf-8")
    return pkg


def test_check_package_accepts_minimal_package(tmp_path):
    pkg = make_pkg(tmp_path)
    for name in ("x.py", "x.json", "x.yaml", "x.txt"):
        (pkg / name).write_text("{}\n", encoding="utf-8")
    assert check_package(pkg) == ([], [])


def test_check_package_description_length(tmp_path):
    pkg = make_pkg(tmp_path)
    (pkg / "SKILL.md").write_text(
        f"---\nname: slop-check\ndescription: {'d' * 250}\n---\n# Body\n", encoding="utf-8"
    )
    errors, _ = check_package(pkg)
    assert errors == ["SKILL.md: frontmatter description has 250 characters, at most 200 are allowed"]


def test_check_package_folder_name(tmp_path):
    errors, _ = check_package(make_pkg(tmp_path, "slopcheck"))
    assert errors == ["package folder must be named 'slop-check', is 'slopcheck'"]


@pytest.mark.parametrize(
    ("rel", "content", "message"),
    [
        ("image.png", b"\x89PNG", "file type '.png' not allowed"),
        ("run.sh", b"echo", "file type '.sh' not allowed"),
        ("Makefile", b"all:", "file type '(none)' not allowed"),
        (".env", b"KEY=1", "hidden files and folders are not allowed"),
        (".git/config", b"[core]", "hidden files and folders are not allowed"),
        (
            "scripts/__pycache__/x.cpython-313.pyc",
            b"x",
            "__pycache__ and compiled Python files are not allowed",
        ),
        ("scripts/x.pyc", b"x", "__pycache__ and compiled Python files are not allowed"),
        ("inner.zip", b"PK\x03\x04", "archives are not allowed inside the package"),
        ("data.tar.gz", b"\x1f\x8b", "archives are not allowed inside the package"),
        ("data.json", b"PK\x03\x04rest", "contains zip archive data"),
        ("notes.txt", b"\x1f\x8b\x08rest", "contains gzip archive data"),
    ],
)
def test_check_package_rejects_files(tmp_path, rel, content, message):
    pkg = make_pkg(tmp_path)
    path = pkg / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    errors, _ = check_package(pkg)
    assert any(message in e for e in errors), errors


def test_check_package_rejects_symlink(tmp_path):
    pkg = make_pkg(tmp_path)
    try:
        (pkg / "link.md").symlink_to(pkg / "references" / "a.md")
    except OSError:
        pytest.skip("symlinks not supported here")
    errors, _ = check_package(pkg)
    assert errors == ["link.md: symbolic links are not allowed"]


def test_check_package_size_limits(tmp_path, monkeypatch):
    pkg = make_pkg(tmp_path)
    (pkg / "big.txt").write_text("x" * 2000, encoding="utf-8")
    monkeypatch.setattr(build_mod, "WARN_BYTES", 1000)
    errors, warnings = check_package(pkg)
    assert errors == [] and len(warnings) == 1 and "above 5 MB" in warnings[0]
    monkeypatch.setattr(build_mod, "MAX_BYTES", 1500)
    errors, warnings = check_package(pkg)
    assert len(errors) == 1 and "exceeds the 100 MB limit" in errors[0] and warnings == []


def test_check_package_file_limit(tmp_path):
    pkg = make_pkg(tmp_path)  # root folder, SKILL.md, references/, references/a.md: 4 zip entries
    for i in range(MAX_FILES - 4):
        (pkg / "references" / f"f{i}.md").write_text("x\n", encoding="utf-8")
    assert check_package(pkg) == ([], [])
    (pkg / "references" / "one-more.md").write_text("x\n", encoding="utf-8")
    errors, _ = check_package(pkg)
    assert errors == [
        f"package holds {MAX_FILES + 1} files and folders (zip entries); claude.ai rejects archives with "
        f"more than {MAX_FILES}"
    ]


def test_check_package_requires_skill_md(tmp_path):
    pkg = make_pkg(tmp_path)
    (pkg / "SKILL.md").unlink()
    errors, _ = check_package(pkg)
    assert errors == ["SKILL.md missing in the package root"]


def test_detection_words_describe_min_sentences_per_paragraph():
    detector = {"kind": "metric", "metric": "sentence_length_cv", "params": {"run": 4}}
    plain = build_mod.detection_words({"detector": detector})
    assert "any run of 4 consecutive paragraphs" in plain and "break a run" not in plain
    detector["params"]["min_sentences_per_paragraph"] = 2
    text = build_mod.detection_words({"detector": detector})
    assert "Paragraphs with fewer than 2 sentences break a run." in text
    assert "Parameters" not in text
