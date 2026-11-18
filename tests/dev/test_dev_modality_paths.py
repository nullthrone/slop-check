"""The workflows' content-path checks know every modality of ``slopcheck_dev.patterns.MODALITIES``."""

from __future__ import annotations

import re

from dev_helpers import REPO

from slopcheck_dev.patterns import MODALITIES


def _alternatives(text: str, prefix: str) -> set[str]:
    match = re.search(re.escape(prefix) + r"([a-z|]+)\)/", text)
    assert match, f"no modality list after {prefix!r}"
    return set(match.group(1).split("|"))


def test_ci_content_path_check_lists_every_modality():
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert _alternatives(ci, "patterns/(") == set(MODALITIES)


def test_llm_gate_data_path_lists_every_modality():
    gate = (REPO / ".github" / "scripts" / "llm_gate.py").read_text(encoding="utf-8")
    assert _alternatives(gate, "patterns/(?:") == set(MODALITIES)
