"""Skill conformance: does a host model follow the packaged skill? (docs/architecture.md 8)

The built skill folder (``SKILL.md`` plus ``references/*.md``; ``scripts/`` is ignored because
the skill must work without them) is turned into a system prompt that simulates skill
loading. Each case from ``evals/conformance/cases/*.yaml`` is sent to every resolved
``conformance`` model. Audit cases are scored from the JSON result block of the report
(``skill/references/report-format.md``; shape of section 4.5, ``findings[].pattern_id``):
recall over ``must_find``, precision against ``must_not_find`` and against scored findings in
clean texts. Rewrite cases check that flagged phrases disappear and that facts survive.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ._common import count_words, iso, load_yaml, repo_root, sha256_text, utc_now
from .budget import BudgetExceeded
from .openrouter import ModelUnavailableError, OpenRouterClient, OpenRouterError

VERDICTS = ("GREEN", "YELLOW", "RED")
CONFORMANCE_MAX_TOKENS = 6000

REQUESTS = {
    "audit": {
        "en": (
            "Please check the following text with the slop-check skill in audit mode. Give me the "
            "report as the skill describes it, including its JSON result block.\n\n"
            "<<<TEXT\n{text}\nTEXT>>>"
        ),
        "de": (
            "Bitte prüfe den folgenden Text mit dem Skill slop-check im Audit-Modus. Gib mir den "
            "Bericht so, wie der Skill ihn beschreibt, einschließlich des JSON-Ergebnisblocks.\n\n"
            "<<<TEXT\n{text}\nTEXT>>>"
        ),
    },
    "rewrite": {
        "en": (
            "Please use the slop-check skill in rewrite mode on the following text. After the "
            "skill's normal output, repeat the complete rewritten text once more inside a fenced "
            "code block whose info string is `rewrite`.\n\n<<<TEXT\n{text}\nTEXT>>>"
        ),
        "de": (
            "Bitte wende den Skill slop-check im Rewrite-Modus auf den folgenden Text an. Wiederhole "
            "nach der normalen Ausgabe des Skills den vollständigen überarbeiteten Text noch einmal in "
            "einem Codeblock mit der Kennung `rewrite`.\n\n<<<TEXT\n{text}\nTEXT>>>"
        ),
    },
}


# ---------------------------------------------------------------------------
# skill loading


def load_skill(skill_dir: str | Path) -> dict:
    """SKILL.md and references/*.md of a built skill package. Scripts are ignored."""
    base = Path(skill_dir)
    skill_md = base / "SKILL.md"
    if not skill_md.is_file():
        raise FileNotFoundError(f"{skill_md} not found; build the skill first (slopcheck-dev build)")
    files = [("SKILL.md", skill_md.read_text(encoding="utf-8"))]
    ref_dir = base / "references"
    if ref_dir.is_dir():
        for f in sorted(ref_dir.glob("*.md")):
            files.append((f"references/{f.name}", f.read_text(encoding="utf-8")))
    name = base.name
    m = re.search(r"^name:\s*([A-Za-z0-9-]+)\s*$", files[0][1], re.MULTILINE)
    if m:
        name = m.group(1)
    digest = sha256_text("\n".join(f"{p}\n{t}" for p, t in files))
    return {"name": name, "path": str(base), "files": files, "sha256": digest}


def skill_system_prompt(skill: dict) -> str:
    """System prompt that mimics a runtime that has loaded the skill without script access."""
    parts = [
        f'An agent skill named "{skill["name"]}" is installed. Its files are reproduced below. '
        "Apply the skill when the user's request matches its description in SKILL.md, and read the "
        "reference files as SKILL.md instructs. Scripts of this skill are not available in this "
        "environment, so apply the references yourself.",
        "",
        f'<skill name="{skill["name"]}">',
    ]
    for path, text in skill["files"]:
        parts.append(f'<file path="{path}">')
        parts.append(text.rstrip())
        parts.append("</file>")
    parts.append("</skill>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# cases


def default_cases_dir() -> Path:
    return repo_root() / "evals" / "conformance" / "cases"


def load_cases(cases_dir: str | Path | None = None) -> list[dict]:
    base = Path(cases_dir) if cases_dir else default_cases_dir()
    cases = []
    for f in sorted(base.glob("*.yaml")):
        case = load_yaml(f) or {}
        case.setdefault("id", f.stem)
        if case.get("mode") not in ("audit", "rewrite"):
            raise ValueError(f"{f.name}: mode must be audit or rewrite")
        if not case.get("text") or case.get("language") not in REQUESTS[case["mode"]]:
            raise ValueError(f"{f.name}: needs text and a language in {sorted(REQUESTS[case['mode']])}")
        for key in ("must_find", "must_not_find", "must_remove", "must_keep"):
            case[key] = list(case.get(key) or [])
        ev = case.get("expect_verdict")
        case["expect_verdict"] = [ev] if isinstance(ev, str) else list(ev or [])
        cases.append(case)
    return cases


def build_request(case: dict) -> str:
    return REQUESTS[case["mode"]][case["language"]].format(text=case["text"].strip())


# ---------------------------------------------------------------------------
# parsing replies

_FENCE_RE = re.compile(r"```([A-Za-z0-9_-]*)[^\n]*\n(.*?)```", re.DOTALL)


def extract_json_block(reply: str) -> dict | None:
    """Last JSON object in the reply that looks like a result block (has findings or verdict)."""
    candidates: list[dict] = []
    for info, body in _FENCE_RE.findall(reply):
        if info.lower() in ("json", "") or body.lstrip().startswith("{"):
            try:
                data = json.loads(body)
            except ValueError:
                continue
            if isinstance(data, dict):
                candidates.append(data)
    if not candidates:
        decoder = json.JSONDecoder()
        for m in re.finditer(r"\{", reply):
            try:
                data, _ = decoder.raw_decode(reply[m.start() :])
            except ValueError:
                continue
            if isinstance(data, dict):
                candidates.append(data)
    good = [c for c in candidates if "findings" in c or "verdict" in c]
    return good[-1] if good else None


def _ids(items: Any) -> list[str]:
    out = []
    for it in items or []:
        if isinstance(it, str):
            out.append(it)
        elif isinstance(it, dict):
            pid = it.get("pattern_id") or it.get("id") or it.get("pattern")
            if pid:
                out.append(str(pid))
    return out


def result_ids(block: dict) -> tuple[list[str], list[str]]:
    """(scored finding ids, observation ids) from a result block."""
    return _ids(block.get("findings")), _ids(block.get("observations"))


def extract_rewrite(reply: str) -> tuple[str | None, str]:
    """(rewritten text, method). Prefers a ```rewrite block, then JSON fields, then plain reply."""
    for info, body in _FENCE_RE.findall(reply):
        if info.lower() in ("rewrite", "rewritten", "text"):
            return body.strip(), "fence"
    block = extract_json_block(reply)
    if block:
        for key in ("rewritten_text", "rewrite", "rewritten", "text", "output"):
            if isinstance(block.get(key), str) and block[key].strip():
                return block[key].strip(), "json"
    stripped = _FENCE_RE.sub("", reply).strip()
    return (stripped or None), "fallback"


def _norm(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("„", '"')
    return re.sub(r"\s+", " ", s).strip().casefold()


# ---------------------------------------------------------------------------
# scoring


@dataclass
class CaseResult:
    id: str
    mode: str
    language: str
    passed: bool = False
    parse_ok: bool = False
    error: str | None = None
    verdict: str | None = None
    found: list = field(default_factory=list)
    missing: list = field(default_factory=list)
    unexpected: list = field(default_factory=list)
    extra_scored: list = field(default_factory=list)
    checks: dict = field(default_factory=dict)
    usd: float = 0.0

    def to_dict(self) -> dict:
        return {
            k: v for k, v in self.__dict__.items() if v not in (None, [], {}) or k in ("passed", "parse_ok")
        }


def score_audit(case: dict, reply: str) -> CaseResult:
    res = CaseResult(id=case["id"], mode="audit", language=case["language"])
    block = extract_json_block(reply)
    if block is None:
        res.error = "no JSON result block found"
        res.missing = list(case["must_find"])
        return res
    res.parse_ok = True
    findings, observations = result_ids(block)
    found = set(findings) | set(observations)
    res.found = sorted(found)
    res.missing = [p for p in case["must_find"] if p not in found]
    res.unexpected = [p for p in case["must_not_find"] if p in found]
    verdict = str(block.get("verdict") or "").upper() or None
    res.verdict = verdict
    ok = not res.missing and not res.unexpected
    if case["expect_verdict"]:
        res.checks["verdict"] = verdict in case["expect_verdict"]
        ok = ok and res.checks["verdict"]
    if case.get("max_findings") is not None:
        allowed = int(case["max_findings"])
        res.extra_scored = findings[allowed:] if len(findings) > allowed else []
        res.checks["max_findings"] = len(findings) <= allowed
        ok = ok and res.checks["max_findings"]
    res.passed = ok
    return res


def score_rewrite(case: dict, reply: str) -> CaseResult:
    res = CaseResult(id=case["id"], mode="rewrite", language=case["language"])
    text, method = extract_rewrite(reply)
    res.checks["extraction"] = method
    if not text:
        res.error = "no rewritten text found"
        return res
    res.parse_ok = method != "fallback"
    norm = _norm(text)
    still = [p for p in case["must_remove"] if _norm(p) in norm]
    lost = [p for p in case["must_keep"] if _norm(p) not in norm]
    res.unexpected = still
    res.missing = lost
    ratio = count_words(text) / max(1, count_words(case["text"]))
    lo = float(case.get("min_length_ratio", 0.5))
    hi = float(case.get("max_length_ratio", 1.3))
    res.checks["length_ratio"] = round(ratio, 3)
    res.checks["length_ok"] = lo <= ratio <= hi
    res.passed = not still and not lost and res.checks["length_ok"]
    return res


def score_case(case: dict, reply: str) -> CaseResult:
    return score_audit(case, reply) if case["mode"] == "audit" else score_rewrite(case, reply)


def summarize(cases: list[dict], results: list[CaseResult]) -> dict:
    """Recall, precision and pass rates for one model."""
    by_id = {c["id"]: c for c in cases}
    tp = fn = fp = 0
    clean_total = clean_pass = rewrite_total = rewrite_pass = parse_fail = errors = 0
    verdict_total = verdict_ok = 0
    for r in results:
        case = by_id[r.id]
        if r.error and not r.parse_ok:
            errors += 1
        if r.mode == "audit":
            if not r.parse_ok:
                parse_fail += 1
            tp += len(case["must_find"]) - len(r.missing)
            fn += len(r.missing)
            fp += len(r.unexpected) + len(r.extra_scored)
            if case.get("max_findings") is not None:
                clean_total += 1
                clean_pass += 1 if r.passed else 0
            if case["expect_verdict"]:
                verdict_total += 1
                verdict_ok += 1 if r.checks.get("verdict") else 0
        else:
            rewrite_total += 1
            rewrite_pass += 1 if r.passed else 0
    recall = tp / (tp + fn) if (tp + fn) else None
    precision = tp / (tp + fp) if (tp + fp) else None
    return {
        "cases": len(results),
        "passed": sum(1 for r in results if r.passed),
        "recall": None if recall is None else round(recall, 4),
        "precision": None if precision is None else round(precision, 4),
        "true_positives": tp,
        "false_negatives": fn,
        "false_positives": fp,
        "verdict_accuracy": round(verdict_ok / verdict_total, 4) if verdict_total else None,
        "clean_pass_rate": round(clean_pass / clean_total, 4) if clean_total else None,
        "rewrite_pass_rate": round(rewrite_pass / rewrite_total, 4) if rewrite_total else None,
        "parse_failures": parse_fail,
        "errors": errors,
        "usd": round(sum(r.usd for r in results), 6),
    }


# ---------------------------------------------------------------------------
# run


def run_conformance(
    skill_dir: str | Path,
    models: list[dict],
    client: OpenRouterClient,
    *,
    cases: list[dict] | None = None,
    workers: int = 4,
    max_tokens: int = CONFORMANCE_MAX_TOKENS,
    refresh: Callable[[dict, set[str]], dict | None] | None = None,
    log: Callable[[str], None] = lambda _m: None,
) -> dict:
    skill = load_skill(skill_dir)
    cases = cases if cases is not None else load_cases()
    system = skill_system_prompt(skill)
    stop = threading.Event()
    notices: list[str] = []
    model_results = []
    for entry in models:
        if stop.is_set():
            break
        current = entry
        failed: set[str] = set()
        while True:
            results, unavailable = _run_model(current, cases, system, client, workers, max_tokens, stop, log)
            if not unavailable:
                break
            failed.add(current["id"])
            replacement = refresh(current, failed) if refresh else None
            if not replacement or replacement["id"] in failed:
                notices.append(f"{current.get('key')}: {current['id']} unavailable; no replacement")
                break
            notices.append(f"{current.get('key')}: {current['id']} unavailable; now {replacement['id']}")
            current = replacement
        model_results.append(
            {
                "key": current.get("key"),
                "family": current.get("family"),
                "id": current["id"],
                "canonical_slug": current.get("canonical_slug"),
                "summary": summarize(cases, results),
                "cases": [r.to_dict() for r in results],
            }
        )
    if stop.is_set():
        notices.append("budget cap reached; conformance run aborted, results are partial")
    return {
        "run_at": iso(utc_now()),
        "skill": {
            "name": skill["name"],
            "path": skill["path"],
            "sha256": skill["sha256"],
            "files": [p for p, _ in skill["files"]],
        },
        "cases": [{"id": c["id"], "language": c["language"], "mode": c["mode"]} for c in cases],
        "models": model_results,
        "aborted": stop.is_set(),
        "notices": notices,
    }


def _run_model(
    entry: dict,
    cases: list[dict],
    system: str,
    client: OpenRouterClient,
    workers: int,
    max_tokens: int,
    stop: threading.Event,
    log: Callable[[str], None],
) -> tuple[list[CaseResult], bool]:
    unavailable = threading.Event()

    def one(case: dict) -> CaseResult | None:
        if stop.is_set() or unavailable.is_set():
            return None
        messages = [{"role": "system", "content": system}, {"role": "user", "content": build_request(case)}]
        try:
            res = client.chat(entry, messages, max_tokens=max_tokens, role="conformance")
        except BudgetExceeded:
            stop.set()
            return None
        except ModelUnavailableError as exc:
            unavailable.set()
            log(f"{entry['id']}: unavailable ({exc})")
            return None
        except OpenRouterError as exc:
            # nothing was found: the expected patterns count as missed, not as found
            return CaseResult(
                id=case["id"],
                mode=case["mode"],
                language=case["language"],
                error=str(exc)[:300],
                missing=list(case["must_find"]),
            )
        scored = score_case(case, res.text or "")
        scored.usd = res.usd
        return scored

    results: list[CaseResult] = []
    if workers <= 1:
        for c in cases:
            r = one(c)
            if r:
                results.append(r)
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(one, c) for c in cases]
            for f in as_completed(futures):
                r = f.result()
                if r:
                    results.append(r)
    order = {c["id"]: i for i, c in enumerate(cases)}
    results.sort(key=lambda r: order.get(r.id, 0))
    return results, unavailable.is_set()
