"""LLM judges for ``kind: llm`` patterns during measurement.

A judge has the engine's interface (``slopcheck.engine.analyze(llm_judge=...)``)::

    judge(text, patterns, lang) -> {pattern_id: [{"quote": ...}, ...]}

The prompt and the reply parsing come from ``slopcheck.llm`` so the measured judge sees the
same instructions as ``slopcheck audit --llm``. Calls go through :class:`OpenRouterClient`,
which adds the response cache and the budget checks. Agreement of two judges is applied by
:mod:`measure` (a pattern counts only if it triggers under both).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .budget import BudgetExceeded
from .openrouter import OpenRouterClient

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
) -> Callable[[str, list, str], dict]:
    """Engine-compatible judge backed by one lockfile entry (role ``judges``)."""
    from slopcheck.llm import build_messages, parse_json_object, verbatim_hits

    stats = stats if stats is not None else JudgeStats()

    def judge(text: str, patterns: list, lang: str) -> dict:
        ids = [p["id"] for p in patterns]
        messages = build_messages(text, patterns, lang)
        stats.calls += 1
        try:
            res = client.chat(
                entry, messages, max_tokens=max_tokens, role="judges", params=judge_params(entry)
            )
            data = parse_json_object(res.text)
        except BudgetExceeded:
            stats.budget_exceeded = True
            raise
        except Exception as exc:
            stats.errors += 1
            if len(stats.messages) < 20:
                stats.messages.append(f"{entry.get('id')}: {type(exc).__name__}: {exc}")
            raise
        stats.usd += res.usd
        return verbatim_hits(data, text, ids)

    judge.stats = stats  # type: ignore[attr-defined]
    judge.entry = entry  # type: ignore[attr-defined]
    return judge
