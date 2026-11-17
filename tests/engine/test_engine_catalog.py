"""Catalog loading (section 4.4)."""

import json

import pytest

from slopcheck import catalog as catalog_module
from slopcheck.catalog import CatalogError, load_catalog, make_catalog, select_patterns


def write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_explicit_path(tmp_path):
    path = write(tmp_path / "c.json", make_catalog([{"id": "a"}]))
    assert load_catalog(str(path))["patterns"] == [{"id": "a"}]


def test_environment_variable_wins(tmp_path, monkeypatch):
    path = write(tmp_path / "env.json", make_catalog([{"id": "env"}]))
    monkeypatch.setenv("SLOPCHECK_CATALOG", str(path))
    assert load_catalog()["patterns"][0]["id"] == "env"


def test_skill_layout_catalog_next_to_package(tmp_path, monkeypatch):
    monkeypatch.delenv("SLOPCHECK_CATALOG", raising=False)
    package = tmp_path / "scripts" / "slopcheck"
    package.mkdir(parents=True)
    write(tmp_path / "scripts" / "catalog.json", make_catalog([{"id": "skill"}]))
    monkeypatch.setattr(catalog_module, "__file__", str(package / "catalog.py"))
    assert load_catalog()["patterns"][0]["id"] == "skill"
    write(package / "catalog.json", make_catalog([{"id": "inside"}]))
    assert load_catalog()["patterns"][0]["id"] == "inside"


def test_missing_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOPCHECK_CATALOG", str(tmp_path / "missing.json"))
    with pytest.raises(CatalogError, match="not found"):
        load_catalog()


@pytest.mark.parametrize("content", ["{broken", "[]", '{"patterns": {}}', '{"patterns": [{"name": "x"}]}'])
def test_malformed_catalog(tmp_path, content):
    path = tmp_path / "bad.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(CatalogError):
        load_catalog(str(path))


def test_make_catalog_defaults():
    cat = make_catalog([])
    assert cat["short_text_max_words"] == 150
    assert cat["verdict_thresholds"]["yellow"] == 2.0
    assert cat["verdict_thresholds"]["red"] == 5.0


def test_select_patterns():
    cat = make_catalog(
        [
            {"id": "a", "modality": "text", "status": "core", "effective_status": "fading"},
            {"id": "b", "modality": "image", "status": "candidate"},
            {"id": "c", "modality": "text", "status": "candidate"},
        ]
    )
    assert [p["id"] for p in select_patterns(cat, status="fading")] == ["a"]
    assert [p["id"] for p in select_patterns(cat, modality="text", status="candidate")] == ["c"]
    assert [p["id"] for p in select_patterns(cat, modality="image")] == ["b"]
