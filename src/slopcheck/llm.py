"""Minimal OpenRouter chat client and LLM judge for ``kind: llm`` patterns (urllib only).

No model ID is hard-coded (decision D15): OpenRouter renames, adds and retires models,
so the model always comes from configuration, resolved at call time in this order:

1. an explicit model (``--llm-model``);
2. environment variable ``SLOPCHECK_LLM_MODEL``;
3. the first judge in the resolver lockfile named by ``SLOPCHECK_MODELS_LOCK``
   (``models/lock.json`` written weekly by ``slopcheck-dev models resolve``), so the CLI
   follows renamed or new models without a code change.

The engine itself never calls the network; only the CLI flag ``--llm`` uses this module.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
KEY_ENV = "OPENROUTER_API_KEY"
MODEL_ENV = "SLOPCHECK_LLM_MODEL"
LOCK_ENV = "SLOPCHECK_MODELS_LOCK"
MAX_EXAMPLES = 3

SYSTEM_PROMPT = (
    "You audit texts for specific style patterns. You never judge who or what wrote a text. "
    "Apply each pattern's rubric to the text and report the passages that match it. "
    "Answer with one JSON object and nothing else. Its keys are the pattern ids; each value is a list "
    'of objects {"quote": "..."}. Every quote must be copied character for character from the text: '
    "one contiguous passage, no ellipsis, no corrections, no added quotation marks. "
    "Use an empty list when a pattern does not occur."
)


class LLMError(RuntimeError):
    """Raised when the model call fails or returns unusable output."""


def resolve_model(explicit: str | None = None) -> str | None:
    """Return the model ID from the flag, the environment or the resolver lockfile."""
    if explicit:
        return explicit
    if os.environ.get(MODEL_ENV):
        return os.environ[MODEL_ENV]
    lock = os.environ.get(LOCK_ENV)
    if lock:
        return model_from_lock(lock)
    return None


def model_from_lock(path: str, role: str = "judges") -> str | None:
    """First model ``id`` of ``role`` in a resolver lockfile (section 6.6), or None."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    entries = (data.get("roles") or {}).get(role) or []
    for entry in entries:
        if isinstance(entry, dict) and entry.get("id"):
            return str(entry["id"])
    return None


def chat(
    messages: list[dict],
    model: str,
    api_key: str | None = None,
    timeout: float = 120.0,
    temperature: float = 0.0,
    max_tokens: int = 4000,
    url: str = OPENROUTER_URL,
) -> dict:
    """Send one chat completion request. Returns ``{"content", "model", "usage"}``."""
    key = api_key or os.environ.get(KEY_ENV)
    if not key:
        raise LLMError(f"{KEY_ENV} is not set")
    if not url.startswith("https://"):
        raise LLMError(f"refusing non-https endpoint: {url}")
    body = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    request = urllib.request.Request(  # noqa: S310 (https enforced above)
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "X-Title": "slop-check",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        hint = ""
        if exc.code in (400, 404) and "model" in detail.lower():
            hint = (
                f" (model {model!r} may have been renamed or retired; set {MODEL_ENV} or refresh the "
                "lockfile with `slopcheck-dev models resolve`)"
            )
        raise LLMError(f"OpenRouter HTTP {exc.code}: {detail}{hint}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise LLMError(f"OpenRouter request failed: {exc}") from exc
    if payload.get("error"):
        raise LLMError(f"OpenRouter error: {payload['error']}")
    try:
        content = payload["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError("OpenRouter response has no message content") from exc
    return {"content": content, "model": payload.get("model", model), "usage": payload.get("usage") or {}}


# ---------------------------------------------------------------------------
# Judge


def _examples(pattern: dict, lang: str) -> dict:
    realizations = pattern.get("realizations") or {}
    real = realizations.get(lang) or realizations.get("*") or {}
    return real.get("examples") or {}


def build_messages(
    text: str, patterns: list[dict], lang: str, max_examples: int = MAX_EXAMPLES
) -> list[dict]:
    """Chat messages asking for strict JSON hits per pattern."""
    blocks = []
    for p in patterns:
        detector = p.get("detector") or {}
        lines = [
            f"### {p['id']}: {p.get('name', p['id'])}",
            f"Rubric: {' '.join(str(detector.get('rubric', '')).split())}",
        ]
        position = detector.get("position")
        if position and position != "any":
            lines.append(f"Position: only passages at {position.replace('_', ' ')}.")
        examples = _examples(p, lang)
        for label, key in (("Matches", "positive"), ("Does not match", "negative")):
            items = (examples.get(key) or [])[:max_examples]
            if items:
                lines.append(f"{label}:")
                lines += [f"- {json.dumps(item, ensure_ascii=False)}" for item in items]
        blocks.append("\n".join(lines))
    ids = ", ".join(json.dumps(p["id"]) for p in patterns)
    user = (
        f"Language of the text: {lang}\n\nPatterns:\n\n"
        + "\n\n".join(blocks)
        + f"\n\nText between the markers:\n<<<TEXT\n{text}\nTEXT>>>\n\n"
        + f"Return one JSON object with exactly these keys: {ids}."
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def parse_json_object(content: str) -> dict:
    """Parse the first JSON object in a reply (code fences and surrounding prose tolerated)."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
    try:
        data = json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise LLMError("model reply contains no JSON object") from None
        try:
            data = json.loads(text[start : end + 1])
        except ValueError as exc:
            raise LLMError(f"model reply is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise LLMError("model reply is not a JSON object")
    return data


def verbatim_hits(data: dict, text: str, pattern_ids: list[str]) -> dict[str, list[dict]]:
    """Keep only quotes that occur verbatim in ``text``; unknown keys are ignored."""
    result: dict[str, list[dict]] = {}
    for pattern_id in pattern_ids:
        entry = data.get(pattern_id) or []
        if isinstance(entry, dict):
            entry = entry.get("hits") or []
        hits = []
        for item in entry if isinstance(entry, list) else []:
            quote = item.get("quote") if isinstance(item, dict) else item
            if isinstance(quote, str) and quote.strip() and quote in text:
                hits.append({"quote": quote})
        result[pattern_id] = hits
    return result


def make_llm_judge(
    model: str,
    api_key: str | None = None,
    chat_fn: Callable[..., dict | str] | None = None,
    max_examples: int = MAX_EXAMPLES,
) -> Callable[[str, list, str], dict]:
    """Return ``judge(text, patterns, lang) -> {pattern_id: [{"quote": ...}]}``.

    ``chat_fn(messages, model, api_key=...)`` defaults to :func:`chat`; tests inject a stub.
    Quotes that are not verbatim substrings of the text are dropped.
    """
    send = chat_fn or chat

    def judge(text: str, patterns: list, lang: str) -> dict:
        if not patterns:
            return {}
        reply = send(build_messages(text, patterns, lang, max_examples), model, api_key=api_key)
        content = reply.get("content", "") if isinstance(reply, dict) else str(reply)
        return verbatim_hits(parse_json_object(content), text, [p["id"] for p in patterns])

    judge.model = model  # type: ignore[attr-defined]
    return judge
