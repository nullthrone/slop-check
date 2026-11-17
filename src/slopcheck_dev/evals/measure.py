"""Per-pattern measurement on the human and AI corpora (docs/architecture.md 6.2 to 6.4).

For every measured pattern and language: ``fpr_human`` (triggered human documents / human
documents), ``hit_ai`` (triggered AI documents / AI documents, also per model family) and
``lift = (hit_ai + a) / (fpr_human + a)`` with ``a = 0.5 / n_human``. "Triggered" is the full
rule (detector, threshold, requires) as computed by ``slopcheck.engine.analyze`` with a
catalog compiled from the pattern files. ``kind: llm`` patterns count only when both judges
agree. ``meets_core`` and ``meets_fading`` apply ``governance/thresholds.yaml: admission``.

Output: the ``measurements.json`` structure of section 6.3, plus a Markdown report.
"""

from __future__ import annotations

import inspect
import math
import statistics
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from ._common import canonical_json, dates_to_str, iso, sha256_text, utc_now

RATE_DIGITS = 4
LIFT_DIGITS = 3


# ---------------------------------------------------------------------------
# basic math


def pattern_hash(pattern: dict) -> str:
    """sha256 of the canonical JSON of the pattern without ``history`` (section 6.3).

    Delegates to ``slopcheck_dev.status.pattern_hash`` so measurement and status derivation can
    never disagree. The local fallback uses the same canonicalization: keys sorted, separators
    (",", ":"), UTF-8 without ASCII escaping, dates as ISO strings, catalog-only fields dropped.
    """
    try:
        from slopcheck_dev.status import pattern_hash as status_hash
    except ImportError:
        status_hash = None
    if status_hash is not None:
        return status_hash(pattern)
    body = {k: v for k, v in dates_to_str(source_pattern(pattern)).items() if k != "history"}
    return sha256_text(canonical_json(body))


CATALOG_ONLY_FIELDS = ("effective_status", "weight", "weight_source")


def source_pattern(entry: dict) -> dict:
    return {k: v for k, v in entry.items() if k not in CATALOG_ONLY_FIELDS}


def smoothing(n_human: int) -> float:
    return 0.5 / n_human if n_human > 0 else 0.0


def lift_of(hit_ai: float, fpr_human: float, n_human: int) -> float | None:
    """(hit_ai + a) / (fpr_human + a), a = 0.5 / n_human. None without human documents."""
    if n_human <= 0:
        return None
    a = smoothing(n_human)
    return (hit_ai + a) / (fpr_human + a)


def rate(k: int, n: int) -> float | None:
    return k / n if n > 0 else None


def percentile(values: list[float], q: float) -> float:
    """Linear interpolation between closest ranks (numpy's default)."""
    if not values:
        raise ValueError("percentile of an empty list")
    xs = sorted(values)
    pos = (len(xs) - 1) * q / 100.0
    lo, hi = math.floor(pos), math.ceil(pos)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def measured_weight(lift: float | None, thresholds: dict) -> float | None:
    """clamp(ln(lift), weights.from_lift.min, weights.from_lift.max)."""
    if lift is None or lift <= 0:
        return None
    cfg = (thresholds.get("weights") or {}).get("from_lift") or {}
    lo, hi = float(cfg.get("min", 0.5)), float(cfg.get("max", 3.0))
    return max(lo, min(hi, math.log(lift)))


def _r(x: float | None, digits: int) -> float | None:
    return None if x is None else round(float(x), digits)


# ---------------------------------------------------------------------------
# applicability


def applies_to(pattern: dict, lang: str) -> bool:
    real = pattern.get("realizations") or {}
    return lang in real or "*" in real


def detector_kind(pattern: dict) -> str | None:
    return (pattern.get("detector") or {}).get("kind")


# ---------------------------------------------------------------------------
# evaluation


@dataclass
class DocResult:
    doc_id: str
    language: str
    kind: str  # human | ai
    family: str | None
    slug: str | None
    triggered: dict[str, bool] = field(default_factory=dict)
    evaluated: set[str] = field(default_factory=set)


def _default_analyze() -> Callable[..., dict]:
    from slopcheck.engine import analyze

    return analyze


def _default_derive() -> Callable[..., tuple]:
    from slopcheck_dev.status import derive

    return derive


def _default_compile() -> Callable[..., dict]:
    from slopcheck_dev.build import compile_catalog

    return compile_catalog


def call_compile(
    compile_fn: Callable[..., dict], patterns: list[dict], thresholds: dict, measurements: dict | None
) -> dict:
    """Call compile_catalog with whatever parameter names it declares."""
    try:
        params = inspect.signature(compile_fn).parameters
    except (TypeError, ValueError):
        return compile_fn(patterns, thresholds, measurements)
    kwargs: dict[str, Any] = {}
    names = list(params)
    if "thresholds" in params:
        kwargs["thresholds"] = thresholds
    if "measurements" in params:
        kwargs["measurements"] = measurements
    if names and names[0] not in kwargs:
        return compile_fn(patterns, **kwargs)
    return compile_fn(patterns=patterns, **kwargs)


def _run_analyze(
    analyze_fn: Callable[..., dict], text: str, catalog: dict, lang: str, judge: Callable | None
) -> dict:
    return analyze_fn(text, catalog, lang=lang, context="default", modality="text", llm_judge=judge)


def _doc_result(doc: dict) -> DocResult:
    return DocResult(
        doc_id=doc["doc_id"],
        language=doc["language"],
        kind=doc.get("source_kind") or ("ai" if doc.get("canonical_slug") else "human"),
        family=doc.get("family"),
        slug=doc.get("canonical_slug"),
    )


def evaluate_docs(
    docs: list[dict],
    catalog: dict,
    *,
    analyze_fn: Callable[..., dict],
    judges: list[Callable] | None = None,
    llm_ids: set[str] | None = None,
    llm_doc_ids: set[tuple[str, str | None]] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[list[DocResult], list[str]]:
    """Run the engine on each document. LLM patterns need agreement of every judge."""
    notices: list[str] = []
    llm_ids = set(llm_ids or ())
    llm_catalog = None
    if judges and llm_ids:
        # drop llm patterns that are not measured, so judges are not asked about them
        llm_catalog = dict(catalog)
        llm_catalog["patterns"] = [
            p for p in catalog.get("patterns", []) if detector_kind(p) != "llm" or p["id"] in llm_ids
        ]
    results: list[DocResult] = []
    budget_stop = False
    for i, doc in enumerate(docs):
        res = _doc_result(doc)
        base = _run_analyze(analyze_fn, doc["text"], catalog, doc["language"], None)
        for pid, info in (base.get("all_patterns") or {}).items():
            res.triggered[pid] = bool(info.get("triggered"))
            res.evaluated.add(pid)
        wants_llm = (
            llm_catalog is not None
            and not budget_stop
            and (llm_doc_ids is None or (doc["doc_id"], doc.get("canonical_slug")) in llm_doc_ids)
        )
        if wants_llm:
            per_judge = []
            for judge in judges or []:
                out = _run_analyze(analyze_fn, doc["text"], llm_catalog, doc["language"], judge)
                per_judge.append(out.get("all_patterns") or {})
                stats = getattr(judge, "stats", None)
                if stats is not None and getattr(stats, "budget_exceeded", False):
                    budget_stop = True
            if not budget_stop:
                for pid in llm_ids:
                    if all(pid in pj for pj in per_judge):
                        res.evaluated.add(pid)
                        res.triggered[pid] = all(bool(pj[pid].get("triggered")) for pj in per_judge)
        for pid in llm_ids:
            if pid not in res.evaluated or not wants_llm or budget_stop:
                res.evaluated.discard(pid)
                res.triggered.pop(pid, None)
        results.append(res)
        if progress:
            progress(i + 1, len(docs))
    if budget_stop:
        notices.append("budget cap reached during LLM judging; llm patterns are incomplete and were dropped")
    return results, notices


# ---------------------------------------------------------------------------
# aggregation


def _count(results: Iterable[DocResult], pid: str) -> tuple[int, int]:
    n = k = 0
    for r in results:
        if pid in r.evaluated:
            n += 1
            k += 1 if r.triggered.get(pid) else 0
    return k, n


def aggregate_pattern(pattern: dict, results: list[DocResult], thresholds: dict) -> dict | None:
    """Measurement entry for one pattern (section 6.3), or None if nothing was evaluated."""
    pid = pattern["id"]
    langs = sorted({r.language for r in results if applies_to(pattern, r.language)})
    rel = [r for r in results if r.language in langs]
    human = [r for r in rel if r.kind == "human"]
    ai = [r for r in rel if r.kind == "ai"]
    kh, nh = _count(human, pid)
    ka, na = _count(ai, pid)
    if nh == 0 and na == 0:
        return None
    per_language: dict[str, dict] = {}
    for lang in langs:
        lkh, lnh = _count([r for r in human if r.language == lang], pid)
        lka, lna = _count([r for r in ai if r.language == lang], pid)
        if lnh == 0 and lna == 0:
            continue
        fpr, hit = rate(lkh, lnh), rate(lka, lna)
        per_language[lang] = {
            "fpr_human": _r(fpr, RATE_DIGITS),
            "hit_ai": _r(hit, RATE_DIGITS),
            "lift": _r(lift_of(hit or 0.0, fpr or 0.0, lnh) if lna else None, LIFT_DIGITS),
            "n_human": lnh,
            "n_ai": lna,
        }
    fpr, hit = rate(kh, nh), rate(ka, na)
    lift = lift_of(hit or 0.0, fpr or 0.0, nh) if na else None
    per_family: dict[str, dict] = {}
    for fam in sorted({r.family for r in ai if r.family}):
        fk, fn = _count([r for r in ai if r.family == fam], pid)
        if fn == 0:
            continue
        fh = rate(fk, fn)
        per_family[fam] = {
            "hit_ai": _r(fh, RATE_DIGITS),
            "lift": _r(lift_of(fh or 0.0, fpr or 0.0, nh), LIFT_DIGITS),
        }
    entry = {
        "pattern_hash": pattern_hash(source_pattern(pattern)),
        "per_language": per_language,
        "per_family": per_family,
        "fpr_human": _r(fpr, RATE_DIGITS),
        "hit_ai": _r(hit, RATE_DIGITS),
        "lift": _r(lift, LIFT_DIGITS),
    }
    entry["meets_core"], entry["meets_fading"] = admission_flags(entry, ka, thresholds)
    weight = measured_weight(lift, thresholds)
    entry["weight"] = _r(weight, 3)
    return entry


def admission_flags(entry: dict, ai_hits: int, thresholds: dict) -> tuple[bool, bool]:
    """(meets_core, meets_fading) per governance/thresholds.yaml.

    Both need at least ``min_human_docs_per_language`` human documents in every measured
    language. Core: pooled and per-language fpr within max_fpr_human, pooled lift >= min_lift,
    >= min_ai_hits triggered AI documents, >= min_model_families families with lift >=
    min_family_lift. Fading: pooled lift <= fading.max_lift or pooled fpr >= fading.min_fpr_human.
    """
    adm = thresholds.get("admission") or {}
    core = adm.get("core") or {}
    fading = adm.get("fading") or {}
    per_language = entry.get("per_language") or {}
    min_docs = int(core.get("min_human_docs_per_language", 100))
    enough = bool(per_language) and all((pl.get("n_human") or 0) >= min_docs for pl in per_language.values())
    fpr, lift = entry.get("fpr_human"), entry.get("lift")
    if not enough or fpr is None or lift is None:
        return False, False
    max_fpr = float(core.get("max_fpr_human", 0.05))
    fpr_ok = fpr <= max_fpr and all(
        pl.get("fpr_human") is None or pl["fpr_human"] <= max_fpr for pl in per_language.values()
    )
    fam_ok = sum(
        1
        for f in (entry.get("per_family") or {}).values()
        if f.get("lift") is not None and f["lift"] >= float(core.get("min_family_lift", 1.5))
    ) >= int(core.get("min_model_families", 2))
    meets_core = (
        fpr_ok
        and lift >= float(core.get("min_lift", 2.0))
        and ai_hits >= int(core.get("min_ai_hits", 10))
        and fam_ok
    )
    meets_fading = lift <= float(fading.get("max_lift", 1.5)) or fpr >= float(
        fading.get("min_fpr_human", 0.08)
    )
    return bool(meets_core), bool(meets_fading and not meets_core)


# ---------------------------------------------------------------------------
# verdict thresholds


def doc_score(result: DocResult, weights: dict[str, float]) -> float:
    return round(sum(w for pid, w in weights.items() if w and result.triggered.get(pid)), 6)


def verdict_thresholds(human_scores: list[float], ai_scores: list[float], min_weight: float) -> dict | None:
    """yellow = P90 of human scores, red = median AI score (section 6.4).

    The engine compares with >=, so yellow is raised to the next observed human score when
    ties at the percentile would put more than 10 % of human texts at YELLOW, and it is never
    0 (then the smallest scored weight is used). red is kept above yellow.
    """
    if not human_scores or not ai_scores:
        return None
    yellow = percentile(human_scores, 90)
    n = len(human_scores)
    if sum(1 for s in human_scores if s >= yellow) / n > 0.10:
        higher = sorted({s for s in human_scores if s > yellow})
        yellow = higher[0] if higher else yellow + min_weight
    if yellow <= 0:
        yellow = min_weight
    red = statistics.median(ai_scores)
    adjusted = False
    if red <= yellow:
        red = yellow + min_weight
        adjusted = True
    out = {"yellow": round(yellow, 2), "red": round(red, 2)}
    if adjusted:
        out["red_adjusted"] = True
    return out


# ---------------------------------------------------------------------------
# main entry


def select_split(docs: list[dict], split: str) -> list[dict]:
    from ._common import split_of

    if split not in ("dev", "holdout", "all"):
        raise ValueError("split must be dev, holdout or all")
    if split == "all":
        return list(docs)
    return [d for d in docs if (d.get("split") or split_of(d["doc_id"])) == split]


def llm_sample(ai_docs: list[dict], per_language: int | None) -> set[tuple[str, str | None]] | None:
    """Deterministic subset of AI documents judged by LLMs (cost control)."""
    if per_language is None:
        return None
    out: set[tuple[str, str | None]] = set()
    by_lang: dict[str, list[dict]] = {}
    for d in ai_docs:
        by_lang.setdefault(d["language"], []).append(d)
    for docs in by_lang.values():
        docs.sort(key=lambda d: sha256_text(f"llm:{d['doc_id']}:{d.get('canonical_slug')}"))
        out.update((d["doc_id"], d.get("canonical_slug")) for d in docs[:per_language])
    return out


def measure(
    human_docs: list[dict],
    ai_docs: list[dict],
    patterns: list[dict],
    thresholds: dict,
    *,
    split: str,
    pattern_ids: Iterable[str] | None = None,
    catalog: dict | None = None,
    previous_measurements: dict | None = None,
    analyze_fn: Callable[..., dict] | None = None,
    derive_fn: Callable[..., tuple] | None = None,
    compile_fn: Callable[..., dict] | None = None,
    judges: list[Callable] | None = None,
    llm_ai_sample: int | None = None,
    models_used: dict | None = None,
    llm_unavailable_reason: str | None = None,
    progress: Callable[[int, int], None] | None = None,
    now: Any = None,
) -> dict:
    """Measure patterns and return the measurements.json structure."""
    analyze_fn = analyze_fn or _default_analyze()
    derive_fn = derive_fn or _default_derive()
    if catalog is None:
        catalog = call_compile(compile_fn or _default_compile(), patterns, thresholds, previous_measurements)
    by_id = {p["id"]: p for p in patterns}
    wanted = list(pattern_ids) if pattern_ids else [p["id"] for p in patterns]
    unknown = [pid for pid in wanted if pid not in by_id]
    if unknown:
        raise ValueError(f"unknown pattern ids: {', '.join(unknown)}")
    text_ids = [
        pid for pid in wanted if by_id[pid].get("modality", "text") == "text" and detector_kind(by_id[pid])
    ]
    notices: list[str] = []
    llm_ids = {pid for pid in text_ids if detector_kind(by_id[pid]) == "llm"}
    if llm_ids and not judges:
        reason = llm_unavailable_reason or "no judges (run with --llm)"
        notices.append(f"llm patterns not measured: {reason}: {', '.join(sorted(llm_ids))}")
        text_ids = [pid for pid in text_ids if pid not in llm_ids]
        llm_ids = set()
    skipped_vision = [pid for pid in wanted if detector_kind(by_id[pid]) in ("vision", None)]
    if skipped_vision:
        notices.append(f"not measurable on the text corpora: {', '.join(skipped_vision)}")

    human = select_split(human_docs, split)
    ai = select_split(ai_docs, split)
    for d in human:
        d.setdefault("source_kind", "human")
    for d in ai:
        d["source_kind"] = "ai"
    llm_docs = None
    if llm_ids and llm_ai_sample is not None:
        sample = llm_sample(ai, llm_ai_sample)
        llm_docs = {(d["doc_id"], None) for d in human} | (sample or set())
    results, eval_notices = evaluate_docs(
        human + ai,
        catalog,
        analyze_fn=analyze_fn,
        judges=judges,
        llm_ids=llm_ids,
        llm_doc_ids=llm_docs,
        progress=progress,
    )
    notices.extend(eval_notices)
    for judge in judges or []:
        stats = getattr(judge, "stats", None)
        if stats is not None and (getattr(stats, "errors", 0) or getattr(stats, "messages", None)):
            jid = (getattr(judge, "entry", None) or {}).get("id", "judge")
            first = "; ".join(stats.messages[:3])
            notices.append(f"judge {jid}: {stats.errors} failed calls of {stats.calls}. {first}".strip())
    if judges and llm_ids:
        measurements_models = {
            "judges": [(getattr(j, "entry", None) or {}).get("canonical_slug") for j in judges]
        }
    else:
        measurements_models = {}
    if eval_notices:
        text_ids = [pid for pid in text_ids if pid not in llm_ids]

    patterns_out: dict[str, dict] = {}
    for pid in text_ids:
        entry = aggregate_pattern(by_id[pid], results, thresholds)
        if entry is not None:
            patterns_out[pid] = entry

    # scores with the weights this measurement implies
    weights: dict[str, float] = {}
    for cat_entry in catalog.get("patterns", []):
        pid = cat_entry["id"]
        if pid in patterns_out:
            status, weight, _src = derive_fn(
                by_id.get(pid, source_pattern(cat_entry)), patterns_out[pid], thresholds
            )
            weights[pid] = float(weight or 0.0) if status == "core" else 0.0
        elif cat_entry.get("effective_status") == "core":
            weights[pid] = float(cat_entry.get("weight") or 0.0)
    positive = [w for w in weights.values() if w > 0]
    min_weight = (
        min(positive)
        if positive
        else float(((thresholds.get("weights") or {}).get("from_lift") or {}).get("min", 0.5))
    )
    human_scores = [doc_score(r, weights) for r in results if r.kind == "human"]
    ai_scores = [doc_score(r, weights) for r in results if r.kind == "ai"]
    vt = verdict_thresholds(human_scores, ai_scores, min_weight)

    def lang_counts(docs: list[dict]) -> dict[str, int]:
        out: dict[str, int] = {}
        for d in docs:
            out[d["language"]] = out.get(d["language"], 0) + 1
        return dict(sorted(out.items()))

    measurements: dict[str, Any] = {
        "measured_at": iso(now or utc_now()),
        "corpus": {"human_docs": lang_counts(human), "ai_docs": lang_counts(ai), "split": split},
        "verdict_thresholds": vt,
        "patterns": dict(sorted(patterns_out.items())),
    }
    models_out = dict(models_used or {})
    if measurements_models.get("judges") and any(measurements_models["judges"]):
        models_out["judges"] = measurements_models["judges"]
    if models_out:
        measurements["models"] = models_out
    if notices:
        measurements["notices"] = notices
    return measurements


# ---------------------------------------------------------------------------
# report


def _fmt(x: Any, pct: bool = False) -> str:
    if x is None:
        return "n/a"
    if pct:
        return f"{100 * float(x):.1f} %"
    return f"{float(x):.2f}"


def render_report(
    measurements: dict,
    patterns: list[dict] | None = None,
    *,
    thresholds: dict | None = None,
    derive_fn: Callable[..., tuple] | None = None,
    title: str | None = None,
) -> str:
    """Markdown report for one measurement run."""
    by_id = {p["id"]: p for p in patterns or []}
    corpus = measurements.get("corpus") or {}
    lines = [f"# {title or 'Measurement report'} ({measurements.get('measured_at', '')[:10]})", ""]
    hd = ", ".join(f"{k} {v}" for k, v in (corpus.get("human_docs") or {}).items()) or "none"
    ad = ", ".join(f"{k} {v}" for k, v in (corpus.get("ai_docs") or {}).items()) or "none"
    lines.append(f"Split: {corpus.get('split')} | human documents: {hd} | AI documents: {ad}")
    vt = measurements.get("verdict_thresholds")
    if vt:
        note = " (red raised above yellow)" if vt.get("red_adjusted") else ""
        lines.append(
            f"Verdict thresholds: yellow from {vt['yellow']:.2f} (90th percentile of human scores), "
            f"red from {vt['red']:.2f} (median AI score){note}"
        )
    models = measurements.get("models") or {}
    for role, entries in models.items():
        lines.append(f"{role}: " + ", ".join(str(e) for e in entries))
    lines.append("")
    pats = measurements.get("patterns") or {}

    def status_after(pid: str) -> str:
        if not (derive_fn and thresholds and pid in by_id):
            return ""
        status, weight, src = derive_fn(by_id[pid], pats[pid], thresholds)
        return f"{status} ({src}, {float(weight or 0):.2f})"

    groups = [
        ("Meets core", [p for p, m in pats.items() if m.get("meets_core")]),
        ("Meets fading", [p for p, m in pats.items() if m.get("meets_fading")]),
        ("Neither", [p for p, m in pats.items() if not m.get("meets_core") and not m.get("meets_fading")]),
    ]
    for heading, ids in groups:
        lines.append(f"## {heading} ({len(ids)})")
        lines.append("")
        if not ids:
            lines.append("None.")
            lines.append("")
            continue
        lines.append(
            "| Pattern | Declared | FPR human | Hit AI | Lift | Weight | Families >= min lift "
            "| After derivation |"
        )
        lines.append("|---|---|---|---|---|---|---|---|")
        fam_min = float(
            (((thresholds or {}).get("admission") or {}).get("core") or {}).get("min_family_lift", 1.5)
        )
        for pid in sorted(ids, key=lambda p: -(pats[p].get("lift") or 0)):
            m = pats[pid]
            fams = [f for f, v in (m.get("per_family") or {}).items() if (v.get("lift") or 0) >= fam_min]
            declared = by_id.get(pid, {}).get("status", "")
            fpr, hit = _fmt(m.get("fpr_human"), True), _fmt(m.get("hit_ai"), True)
            lines.append(
                f"| `{pid}` | {declared} | {fpr} | {hit} | {_fmt(m.get('lift'))} | {_fmt(m.get('weight'))} "
                f"| {len(fams)} ({', '.join(fams) or '-'}) | {status_after(pid)} |"
            )
        lines.append("")
    lines.append("## Per language")
    lines.append("")
    lines.append("| Pattern | Language | FPR human | Hit AI | Lift | n human | n AI |")
    lines.append("|---|---|---|---|---|---|---|")
    for pid in sorted(pats):
        for lang, pl in (pats[pid].get("per_language") or {}).items():
            lines.append(
                f"| `{pid}` | {lang} | {_fmt(pl.get('fpr_human'), True)} | {_fmt(pl.get('hit_ai'), True)} | "
                f"{_fmt(pl.get('lift'))} | {pl.get('n_human')} | {pl.get('n_ai')} |"
            )
    lines.append("")
    notices = measurements.get("notices") or []
    if notices:
        lines.append("## Notices")
        lines.append("")
        lines.extend(f"- {n}" for n in notices)
        lines.append("")
    lines.append(
        "Findings describe style patterns that are over-represented in model output relative to the "
        "human baseline. They are not evidence about who wrote any individual text."
    )
    return "\n".join(lines) + "\n"
