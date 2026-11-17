"""Report rendering (architecture section 4.6): Markdown in English or German, and JSON.

Findings describe style patterns. The wording never claims who or what wrote a text.
"""

from __future__ import annotations

import json

from .thresholds import describe_rule, format_number

MAX_QUOTES = 3
MAX_QUOTE_CHARS = 160

LABELS = {
    "en": {
        "default_title": "text",
        "verdict": "Verdict",
        "verdicts": {"GREEN": "GREEN", "YELLOW": "YELLOW", "RED": "RED"},
        "score": "score",
        "yellow_from": "yellow from",
        "red_from": "red from",
        "words": "words",
        "language": "language",
        "findings": "Findings",
        "observations": "Observations, not scored",
        "not_evaluated": "Not evaluated",
        "notes": "Notes",
        "suggestion": "Suggestion",
        "paragraph": "paragraph",
        "hit": "hit",
        "hits": "hits",
        "threshold": "threshold",
        "weight": "weight",
        "value": "value",
        "more": "(+{n} more)",
        "no_findings": "No scored pattern reached its threshold.",
        "heaviest": "Heaviest findings: {items}.",
        "statuses": {"candidate": "candidate", "fading": "fading", "core": "core"},
        "reasons": {
            "requires_llm": "requires a language model",
            "requires_vision": "requires an image judge",
            "llm_error": "language model call failed",
        },
        "note_provisional": "Some weights are provisional: they apply until the first measurement replaces "
        "them with measured values.",
        "note_short": "Short text ({words} words): short-text thresholds apply.",
        "note_und": "Language not detected: only language-independent patterns ran.",
        "note_llm_error": "Language model error: {error}",
        "note_style": "Findings describe style patterns. They do not show who or what wrote the text.",
        "none": "none",
    },
    "de": {
        "default_title": "Text",
        "verdict": "Gesamtbefund",
        "verdicts": {"GREEN": "GRÜN", "YELLOW": "GELB", "RED": "ROT"},
        "score": "Score",
        "yellow_from": "Gelb ab",
        "red_from": "Rot ab",
        "words": "Wörter",
        "language": "Sprache",
        "findings": "Befunde",
        "observations": "Beobachtungen (nicht gewertet)",
        "not_evaluated": "Nicht ausgewertet",
        "notes": "Hinweise",
        "suggestion": "Vorschlag",
        "paragraph": "Absatz",
        "hit": "Treffer",
        "hits": "Treffer",
        "threshold": "Schwelle",
        "weight": "Gewicht",
        "value": "Wert",
        "more": "(+{n} weitere)",
        "no_findings": "Kein gewertetes Muster hat seine Schwelle erreicht.",
        "heaviest": "Schwerste Befunde: {items}.",
        "statuses": {"candidate": "Kandidat", "fading": "auslaufend", "core": "Kern"},
        "reasons": {
            "requires_llm": "benötigt ein Sprachmodell",
            "requires_vision": "benötigt eine Bildbewertung",
            "llm_error": "Aufruf des Sprachmodells fehlgeschlagen",
        },
        "note_provisional": "Einige Gewichte sind vorläufig: Sie gelten, bis die erste Messung sie "
        "durch gemessene Werte ersetzt.",
        "note_short": "Kurzer Text ({words} Wörter): Es gelten die Schwellen für kurze Texte.",
        "note_und": "Sprache nicht erkannt: Nur sprachunabhängige Muster wurden geprüft.",
        "note_llm_error": "Fehler des Sprachmodells: {error}",
        "note_style": "Die Befunde beschreiben Stilmuster. Sie zeigen nicht, wer oder was den Text "
        "geschrieben hat.",
        "none": "keine",
    },
}


def _labels(lang: str) -> dict:
    return LABELS.get(lang, LABELS["en"])


def format_score(x: float, lang: str = "en") -> str:
    """Scores, weights and verdict thresholds: at least one decimal (``2.0``, ``2.48``)."""
    x = float(x or 0.0)
    text = f"{x:.1f}" if (x * 10).is_integer() else f"{x:.2f}".rstrip("0")
    return text.replace(".", ",") if lang == "de" else text


def _quote_text(quote: str) -> str:
    text = " ".join(quote.split())
    if len(text) > MAX_QUOTE_CHARS:
        text = text[: MAX_QUOTE_CHARS - 1].rstrip() + "…"
    return text


def _hits_text(n: int, lab: dict) -> str:
    return f"{n} {lab['hit'] if n == 1 else lab['hits']}"


def _threshold_text(item: dict, lang: str) -> str:
    if item.get("rule") is not None:
        return describe_rule(item["rule"], item.get("requires"), item.get("unit", "sentences"), lang)
    return str(item.get("threshold", ""))


def _quote_lines(item: dict, lab: dict, limit: int) -> list[str]:
    hits = item.get("hits") or []
    lines = [f'   > "{_quote_text(h["quote"])}" ({lab["paragraph"]} {h["paragraph"]})' for h in hits[:limit]]
    if len(hits) > limit:
        lines.append("   " + lab["more"].format(n=len(hits) - limit))
    return lines


def _measure_text(item: dict, lab: dict, lang: str) -> str:
    parts = [_hits_text(item.get("count", 0), lab)]
    if item.get("value") is not None and item.get("kind") in ("metric", "llm"):
        parts.append(f"{lab['value']} {format_number(item['value'], lang)}")
    parts.append(f"{lab['threshold']} {_threshold_text(item, lang)}")
    return ", ".join(parts)


def _verdict_line(result: dict, lab: dict, lang: str) -> str:
    vt = result.get("verdict_thresholds") or {}
    verdict = lab["verdicts"].get(result.get("verdict"), result.get("verdict"))
    return (
        f"{lab['verdict']}: {verdict} ({lab['score']} {format_score(result.get('score', 0), lang)}; "
        f"{lab['yellow_from']} {format_score(vt.get('yellow', 0), lang)}, "
        f"{lab['red_from']} {format_score(vt.get('red', 0), lang)}) | "
        f"{result.get('words', 0)} {lab['words']} | {lab['language']}: {result.get('language', 'und')}"
    )


def _rationale(result: dict, lab: dict, lang: str) -> str:
    findings = result.get("findings") or []
    if not findings:
        return lab["no_findings"]
    items = ", ".join(f"{f['name']} ({format_score(f['weight'], lang)})" for f in findings[:3])
    return lab["heaviest"].format(items=items)


def _notes(result: dict, lab: dict) -> list[str]:
    notes = []
    if result.get("provisional"):
        notes.append(lab["note_provisional"])
    if result.get("short_text"):
        notes.append(lab["note_short"].format(words=result.get("words", 0)))
    if result.get("language") == "und":
        notes.append(lab["note_und"])
    if result.get("llm_error"):
        notes.append(lab["note_llm_error"].format(error=result["llm_error"]))
    notes.append(lab["note_style"])
    return notes


def render_markdown(result: dict, title: str | None = None, lang: str = "en") -> str:
    """Render an analysis result as a Markdown report (labels in ``en`` or ``de``)."""
    lab = _labels(lang)
    out = [f"# Slop-Check: {title or lab['default_title']}", "", _verdict_line(result, lab, lang)]
    out += [_rationale(result, lab, lang), ""]

    findings = result.get("findings") or []
    out.append(f"## {lab['findings']} ({len(findings)})")
    if not findings:
        out.append(lab["no_findings"])
    for i, f in enumerate(findings, start=1):
        head = f"{i}. {f['name']} (`{f['pattern_id']}`, {lab['weight']} {format_score(f['weight'], lang)})"
        out.append(f"{head}: {_measure_text(f, lab, lang)}")
        out += _quote_lines(f, lab, MAX_QUOTES)
        if f.get("fix"):
            out.append(f"   {lab['suggestion']}: {f['fix']}")
    out.append("")

    observations = result.get("observations") or []
    if observations:
        out.append(f"## {lab['observations']} ({len(observations)})")
        for i, o in enumerate(observations, start=1):
            status = lab["statuses"].get(o["effective_status"], o["effective_status"])
            out.append(f"{i}. {o['name']} (`{o['pattern_id']}`, {status}): {_measure_text(o, lab, lang)}")
            out += _quote_lines(o, lab, 1)
        out.append("")

    not_evaluated = result.get("not_evaluated") or []
    if not_evaluated:
        reasons = result.get("not_evaluated_reasons") or {}
        out.append(f"## {lab['not_evaluated']} ({len(not_evaluated)})")
        for pattern_id in not_evaluated:
            reason = lab["reasons"].get(reasons.get(pattern_id, "requires_llm"), "")
            out.append(f"- `{pattern_id}` ({reason})")
        out.append("")

    out.append(f"## {lab['notes']}")
    out += [f"- {note}" for note in _notes(result, lab)]
    return "\n".join(out) + "\n"


def render_json(result: dict) -> str:
    """Render a result (or a list of results) as indented JSON."""
    return json.dumps(result, ensure_ascii=False, indent=2) + "\n"


def render_pattern_list(patterns: list[dict], lang: str = "en") -> str:
    """Markdown table of catalog patterns for ``slopcheck patterns``."""
    head = {
        "en": ("Pattern", "Name", "Modality", "Status", "Detector", "Weight"),
        "de": ("Muster", "Name", "Modalität", "Status", "Detektor", "Gewicht"),
    }.get(lang, ())
    head = head or ("Pattern", "Name", "Modality", "Status", "Detector", "Weight")
    rows = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for p in patterns:
        detector = (p.get("detector") or {}).get("kind", "-")
        status = p.get("effective_status") or p.get("status", "-")
        weight = format_score(p.get("weight") or 0.0, lang)
        name = str(p.get("name", "")).replace("|", "\\|")
        rows.append(
            f"| `{p['id']}` | {name} | {p.get('modality', 'text')} | {status} | {detector} | {weight} |"
        )
    return "\n".join(rows) + "\n"
