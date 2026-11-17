"""Analysis engine (architecture sections 4.1 and 4.5).

``analyze`` evaluates every pattern of the requested modality that has a detector,
regardless of status. Scoring uses only patterns whose ``effective_status`` is ``core``:
the score is the sum of their weights over triggered patterns, and the verdict follows
the catalog's ``verdict_thresholds`` (GREEN below yellow, YELLOW from yellow, RED from red).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from . import __version__
from .detectors import lexicon_hits, make_hit, regex_hits
from .metrics import METRICS, MetricInput, MetricResult
from .textmodel import PROSE_KINDS, TextModel, build_text_model
from .thresholds import count_met, describe_rule, effective_rule, units_ok, value_met, words_ok

DEFAULT_SHORT_TEXT_MAX_WORDS = 150
DEFAULT_VERDICT_THRESHOLDS = {"yellow": 2.0, "red": 5.0}
SCORED_STATUS = "core"
OBSERVED_STATUSES = ("candidate", "fading")

LlmJudge = Callable[[str, list, str], dict]


@dataclass
class Evaluation:
    """Outcome of one pattern on one text."""

    pattern: dict
    rule: dict
    unit: str = "sentences"
    hits: list[dict] = field(default_factory=list)
    value: float | None = None
    base: bool = False
    triggered: bool = False

    @property
    def id(self) -> str:
        return self.pattern["id"]

    @property
    def status(self) -> str:
        return effective_status(self.pattern)

    @property
    def weight(self) -> float:
        return float(self.pattern.get("weight") or 0.0)


def effective_status(pattern: dict) -> str:
    """``effective_status`` from the catalog, falling back to the declared status."""
    return pattern.get("effective_status") or pattern.get("status") or "observation"


def realization_for(pattern: dict, lang: str) -> dict | None:
    """Merge the realization for ``lang`` with the ``*`` realization.

    Payload lists (``patterns``, ``terms``) are concatenated; examples come from the
    language realization if present. Returns None if neither exists (the pattern does
    not apply to this language).
    """
    realizations = pattern.get("realizations") or {}
    own = realizations.get(lang) if lang != "*" else None
    star = realizations.get("*")
    if own is None and star is None:
        return None
    parts = [r for r in (own, star) if r is not None]
    return {
        "patterns": [p for r in parts for p in r.get("patterns", [])],
        "terms": [t for r in parts for t in r.get("terms", [])],
        "examples": (own if own is not None else star).get("examples") or {},
        "language": lang if own is not None else "*",
    }


# ---------------------------------------------------------------------------
# Per-kind evaluation


def _paragraph_words(model: TextModel) -> dict[int, int]:
    return {u.index: u.word_count for u in model.units}


def _apply_count_rule(ev: Evaluation, model: TextModel, units: int) -> None:
    ev.base = units_ok(ev.rule, units) and count_met(
        ev.rule, ev.hits, model.word_count, _paragraph_words(model)
    )


def _evaluate_lexical(ev: Evaluation, model: TextModel, real: dict) -> None:
    """regex and lexicon detectors."""
    detector = ev.pattern["detector"]
    position = detector.get("position")
    if detector["kind"] == "regex":
        ev.hits = regex_hits(model, ev.id, real["patterns"], position)
    else:
        ev.hits = lexicon_hits(model, ev.id, real["terms"], position)
    _apply_count_rule(ev, model, model.sentence_count())


def _run_metric(ev: Evaluation, model: TextModel, real: dict, units: list) -> MetricResult:
    detector = ev.pattern["detector"]
    spec = METRICS[detector["metric"]]
    value_rule = ev.rule.get("value") or {}
    direction = "low" if value_rule.get("op") in ("lt", "lte") else "high"
    inp = MetricInput(
        model=model,
        units=units,
        params=detector.get("params") or {},
        lang=model.language,
        terms=real["terms"],
        direction=direction,
        key=ev.id,
    )
    return spec.fn(inp)


def _evaluate_metric(ev: Evaluation, model: TextModel, real: dict) -> None:
    """metric detectors: value rule (or count rule on evidence when no value is set)."""
    name = ev.pattern["detector"].get("metric")
    if name not in METRICS:
        raise ValueError(f"pattern {ev.id}: unknown metric {name!r}")
    spec = METRICS[name]
    ev.unit = spec.unit
    if not ev.rule.get("value"):
        result = _run_metric(ev, model, real, model.units)
        ev.hits, ev.value = result.hits, result.value
        _apply_count_rule(ev, model, result.units)
        return
    if ev.rule.get("scope") == "paragraph":
        _evaluate_metric_per_paragraph(ev, model, real, spec.aggregate)
        return
    result = _run_metric(ev, model, real, model.units)
    ev.value = result.value
    ev.base = units_ok(ev.rule, result.units) and value_met(ev.rule, result.value)
    ev.hits = result.hits if (ev.base or not spec.aggregate) else []


def _evaluate_metric_per_paragraph(ev: Evaluation, model: TextModel, real: dict, aggregate: bool) -> None:
    """Value rule with scope ``paragraph``: triggers if any single unit meets it."""
    low = (ev.rule["value"]["op"]) in ("lt", "lte")
    hits: list[dict] = []
    values = []
    for unit in model.units:
        result = _run_metric(ev, model, real, [unit])
        if result.value is None or not units_ok(ev.rule, result.units):
            hits.extend([] if aggregate else result.hits)
            continue
        values.append(result.value)
        met = value_met(ev.rule, result.value)
        ev.base = ev.base or met
        if met or not aggregate:
            hits.extend(result.hits)
    ev.hits = sorted(hits, key=lambda h: h["start"])
    if values:
        ev.value = min(values) if low else max(values)


def locate_quotes(model: TextModel, quotes: list) -> list[dict]:
    """Turn judge quotes into hits. Quotes that are not verbatim substrings are dropped.

    A quote may be a string or a dict with ``quote``. Repeated quotes map to successive
    occurrences in the text. Occurrences outside the analyzed text (fenced code, front
    matter) are skipped, so the quote maps to its first occurrence in the prose.
    """
    hits = []
    used: set[tuple[int, int]] = set()
    for item in quotes or []:
        quote = item.get("quote") if isinstance(item, dict) else item
        if not isinstance(quote, str) or not quote.strip():
            continue
        found = None
        for candidate in dict.fromkeys((quote.strip(), quote.strip().strip("\"'“”„«»"))):
            if not candidate:
                continue
            pos = model.text.find(candidate)
            while pos != -1:
                span = (pos, pos + len(candidate))
                if span not in used:
                    hit = make_hit(model, *span)
                    if hit is not None:
                        found = (span, hit)
                        break
                pos = model.text.find(candidate, pos + 1)
            if found is not None:
                break
        if found is None:
            continue
        span, hit = found
        used.add(span)
        if all(h["start"] != hit["start"] or h["end"] != hit["end"] for h in hits):
            hits.append(hit)
    return sorted(hits, key=lambda h: h["start"])


def _llm_units(ev: Evaluation, model: TextModel) -> tuple[int, dict[int, int]]:
    """Units for llm value rules: sentences (default) or paragraphs, per params.unit."""
    unit = (ev.pattern["detector"].get("params") or {}).get("unit", "sentence")
    prose = model.units_of(PROSE_KINDS)
    if unit == "paragraph":
        ev.unit = "paragraphs"
        return len(prose), {u.index: 1 for u in prose}
    ev.unit = "sentences"
    return sum(len(u.sentences) for u in prose), {u.index: len(u.sentences) for u in prose}


def _apply_llm_rule(ev: Evaluation, model: TextModel) -> None:
    """Threshold for llm patterns: value rule as share of judged units, else count rule."""
    total, per_paragraph = _llm_units(ev, model)
    if not units_ok(ev.rule, total):
        ev.base = False
        return
    if not ev.rule.get("value"):
        _apply_count_rule(ev, model, total)
        return
    if ev.rule.get("scope") == "paragraph":
        counts: dict[int, int] = {}
        for hit in ev.hits:
            counts[hit["paragraph"]] = counts.get(hit["paragraph"], 0) + 1
        values = [c / per_paragraph[p] for p, c in counts.items() if per_paragraph.get(p)]
        ev.value = max(values) if values else 0.0
        ev.base = any(value_met(ev.rule, v) for v in values)
        return
    ev.value = len(ev.hits) / total if total else None
    ev.base = value_met(ev.rule, ev.value)


# ---------------------------------------------------------------------------
# Requires, scoring, verdict


def _resolve_requires(evaluations: list[Evaluation]) -> None:
    """Set ``triggered``: patterns with ``requires.min_other_findings`` count only if at
    least that many other effective-core patterns triggered (fixpoint over dependents)."""
    pending = []
    for ev in evaluations:
        needed = (ev.pattern.get("requires") or {}).get("min_other_findings")
        ev.triggered = ev.base and not needed
        if ev.base and needed:
            pending.append((ev, needed))
    changed = True
    while changed:
        changed = False
        core_triggered = [e for e in evaluations if e.triggered and e.status == SCORED_STATUS]
        for ev, needed in pending:
            if ev.triggered:
                continue
            others = sum(1 for e in core_triggered if e is not ev)
            if others >= needed:
                ev.triggered = True
                changed = True


def verdict_for(score: float, thresholds: dict) -> str:
    """GREEN below yellow, YELLOW from yellow, RED from red."""
    score = round(score, 6)
    if score >= thresholds["red"]:
        return "RED"
    if score >= thresholds["yellow"]:
        return "YELLOW"
    return "GREEN"


def _thresholds(catalog: dict) -> dict:
    vt = catalog.get("verdict_thresholds") or {}
    return {
        "yellow": float(vt.get("yellow", DEFAULT_VERDICT_THRESHOLDS["yellow"])),
        "red": float(vt.get("red", DEFAULT_VERDICT_THRESHOLDS["red"])),
    }


def _finding(ev: Evaluation) -> dict:
    pattern = ev.pattern
    scored = ev.status == SCORED_STATUS
    entry = {
        "pattern_id": ev.id,
        "name": pattern.get("name", ev.id),
        "effective_status": ev.status,
        "weight": ev.weight if scored else 0.0,
        "count": len(ev.hits),
        "triggered": ev.triggered,
        "threshold": describe_rule(ev.rule, pattern.get("requires"), ev.unit),
        "hits": ev.hits,
        "fix": " ".join(str(pattern.get("fix") or "").split()),
        "kind": pattern["detector"]["kind"],
        "rule": ev.rule,
        "unit": ev.unit,
    }
    if pattern.get("requires"):
        entry["requires"] = pattern["requires"]
    if ev.value is not None:
        entry["value"] = round(ev.value, 6)
    return entry


# ---------------------------------------------------------------------------
# analyze


def analyze(
    text: str,
    catalog: dict,
    lang: str | None = None,
    context: str = "default",
    modality: str = "text",
    llm_judge: LlmJudge | None = None,
) -> dict:
    """Analyze ``text`` against ``catalog`` and return the result structure (section 4.5).

    ``lang`` None or ``auto`` detects de/en (``und`` below confidence: only ``*``
    realizations run). ``llm_judge(text, patterns, lang) -> {pattern_id: [hits]}``
    evaluates ``kind: llm`` patterns; without it they are listed under ``not_evaluated``.
    """
    model = build_text_model(text, None if lang in (None, "", "auto") else lang)
    short_max = catalog.get("short_text_max_words") or DEFAULT_SHORT_TEXT_MAX_WORDS
    short = model.word_count <= short_max
    evaluations: list[Evaluation] = []
    not_evaluated: dict[str, str] = {}
    llm_queue: list[Evaluation] = []

    for pattern in catalog.get("patterns", []):
        detector = pattern.get("detector")
        if pattern.get("modality", "text") != modality or not detector or not detector.get("kind"):
            continue
        ev = Evaluation(pattern=pattern, rule=effective_rule(pattern.get("threshold"), short, context))
        kind = detector["kind"]
        real = realization_for(pattern, model.language)
        if kind == "vision":
            not_evaluated[ev.id] = "requires_vision"
            continue
        if real is None:
            evaluations.append(ev)
            continue
        if kind in ("regex", "lexicon"):
            _evaluate_lexical(ev, model, real)
        elif kind == "metric":
            _evaluate_metric(ev, model, real)
        elif kind == "llm":
            if llm_judge is None:
                not_evaluated[ev.id] = "requires_llm"
                continue
            llm_queue.append(ev)
        else:
            raise ValueError(f"pattern {ev.id}: unknown detector kind {kind!r}")
        evaluations.append(ev)

    llm_error = _run_llm(llm_queue, model, llm_judge, evaluations, not_evaluated)
    for ev in evaluations:
        _apply_min_words(ev, model)
    _resolve_requires(evaluations)
    return _assemble(catalog, model, short, context, modality, evaluations, not_evaluated, llm_error)


def _apply_min_words(ev: Evaluation, model: TextModel) -> None:
    """``min_words``: a text with fewer analyzed words never triggers the rule. Aggregate metrics
    (densities) then report no hits, as when their value rule is not met."""
    if words_ok(ev.rule, model.word_count):
        return
    ev.base = False
    detector = ev.pattern.get("detector") or {}
    spec = METRICS.get(detector.get("metric")) if detector.get("kind") == "metric" else None
    if spec is not None and spec.aggregate and ev.rule.get("value"):
        ev.hits = []


def _run_llm(
    queue: list[Evaluation],
    model: TextModel,
    judge: LlmJudge | None,
    evaluations: list[Evaluation],
    not_evaluated: dict[str, str],
) -> str | None:
    """Call the judge once for all llm patterns that meet ``min_units`` and ``min_words``."""
    if not queue or judge is None:
        return None
    ask = []
    for ev in queue:
        total, _ = _llm_units(ev, model)
        if units_ok(ev.rule, total) and words_ok(ev.rule, model.word_count):
            ask.append(ev)
    if not ask:
        return None
    try:
        raw = judge(model.text, [ev.pattern for ev in ask], model.language) or {}
    except Exception as exc:  # judge failures must not break the deterministic part
        for ev in ask:
            evaluations.remove(ev)
            not_evaluated[ev.id] = "llm_error"
        return f"{type(exc).__name__}: {exc}"
    for ev in ask:
        entry = raw.get(ev.id) or []
        if isinstance(entry, dict):
            entry = entry.get("hits") or []
        ev.hits = locate_quotes(model, entry)
        _apply_llm_rule(ev, model)
    return None


def _assemble(
    catalog: dict,
    model: TextModel,
    short: bool,
    context: str,
    modality: str,
    evaluations: list[Evaluation],
    not_evaluated: dict[str, str],
    llm_error: str | None,
) -> dict:
    thresholds = _thresholds(catalog)
    scored = [ev for ev in evaluations if ev.status == SCORED_STATUS]
    findings = [_finding(ev) for ev in scored if ev.triggered]
    findings.sort(key=lambda f: (-f["weight"], -f["count"], f["pattern_id"]))
    observations = [_finding(ev) for ev in evaluations if ev.triggered and ev.status in OBSERVED_STATUSES]
    observations.sort(key=lambda f: (-f["count"], f["pattern_id"]))
    score = round(sum(f["weight"] for f in findings), 4)
    # Observations are not part of the published catalog, so a skipped observation is not reported.
    status_by_id = {p.get("id"): effective_status(p) for p in catalog.get("patterns", [])}
    not_evaluated = {k: v for k, v in not_evaluated.items() if status_by_id.get(k) != "observation"}
    result = {
        "engine_version": __version__,
        "catalog_version": catalog.get("catalog_version"),
        "verdict": verdict_for(score, thresholds),
        "score": score,
        "verdict_thresholds": thresholds,
        "provisional": any(ev.pattern.get("weight_source") == "provisional" for ev in scored),
        "words": model.word_count,
        "language": model.language,
        "context": context,
        "modality": modality,
        "short_text": short,
        "findings": findings,
        "observations": observations,
        "not_evaluated": sorted(not_evaluated),
        "not_evaluated_reasons": dict(sorted(not_evaluated.items())),
        "all_patterns": {},
    }
    for ev in sorted(evaluations, key=lambda e: e.id):
        entry = {"triggered": ev.triggered, "count": len(ev.hits)}
        if ev.value is not None:
            entry["value"] = round(ev.value, 6)
        result["all_patterns"][ev.id] = entry
    if llm_error:
        result["llm_error"] = llm_error
    return result
