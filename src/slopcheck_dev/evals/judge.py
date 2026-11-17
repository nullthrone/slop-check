"""LLM judges for ``kind: llm`` patterns during measurement.

A judge has the engine's interface (``slopcheck.engine.analyze(llm_judge=...)``)::

    judge(text, patterns, lang) -> {pattern_id: [{"quote": ...}, ...]}

The prompt and the reply parsing come from ``slopcheck.llm`` so the measured judge sees the
same instructions as ``slopcheck audit --llm``. Calls go through :class:`OpenRouterClient`,
which adds the response cache and the budget checks. Agreement of two judges is applied by
:mod:`measure` (a pattern counts only if it triggers under both). :mod:`measure` also splits
each request so that effective-core patterns and all other patterns go to the judge in separate
calls (``measure.core_separated``); every one of those calls is budgeted and counted here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .budget import BudgetExceeded
from .openrouter import ModelUnavailableError, OpenRouterClient

JUDGE_MAX_TOKENS = 2048


@dataclass
class JudgeStats:
    calls: int = 0
    errors: int = 0
    usd: float = 0.0
    budget_exceeded: bool = False
    messages: list = field(default_factory=list)


def judge_params(entry: dict) -> dict:
    """Deterministic sampling where the model accepts it."""
    supported = entry.get("supported_parameters")
    if supported is None or "temperature" in supported:
        return {"temperature": 0}
    return {}


def make_judge(
    client: OpenRouterClient,
    entry: dict,
    *,
    max_tokens: int = JUDGE_MAX_TOKENS,
    stats: JudgeStats | None = None,
    refresh: Callable[[dict, set[str]], dict | None] | None = None,
) -> Callable[[str, list, str], dict]:
    """Engine-compatible judge backed by one lockfile entry (role ``judges``).

    When the locked model has been renamed or retired (``ModelUnavailableError``), ``refresh``
    re-resolves the selector live and the judge continues with the replacement. The entry in
    use is exposed as ``judge.entry`` so the measurement records the model that really judged.
    """
    from slopcheck.llm import build_messages, parse_json_object, verbatim_hits

    stats = stats if stats is not None else JudgeStats()
    state = {"entry": entry, "failed": set()}

    def call(messages: list[dict]):
        while True:
            current = state["entry"]
            try:
                return client.chat(
                    current, messages, max_tokens=max_tokens, role="judges", params=judge_params(current)
                )
            except ModelUnavailableError:
                state["failed"].add(current["id"])
                replacement = refresh(current, set(state["failed"])) if refresh else None
                if not replacement or replacement["id"] in state["failed"]:
                    raise
                stats.messages.append(f"{current['id']} unavailable; switched to {replacement['id']}")
                state["entry"] = replacement
                judge.entry = replacement  # type: ignore[attr-defined]

    def judge(text: str, patterns: list, lang: str) -> dict:
        ids = [p["id"] for p in patterns]
        messages = build_messages(text, patterns, lang)
        stats.calls += 1
        try:
            res = call(messages)
            data = parse_json_object(res.text)
        except BudgetExceeded:
            stats.budget_exceeded = True
            raise
        except Exception as exc:
            stats.errors += 1
            if len(stats.messages) < 20:
                stats.messages.append(f"{state['entry'].get('id')}: {type(exc).__name__}: {exc}")
            raise
        stats.usd += res.usd
        return verbatim_hits(data, text, ids)

    judge.stats = stats  # type: ignore[attr-defined]
    judge.entry = entry  # type: ignore[attr-defined]
    return judge
