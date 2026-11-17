"""OpenRouter chat completion client (urllib only).

Features: retries with backoff, an on-disk response cache keyed by sha256 of
(model, messages, params), usage accounting (OpenRouter ``usage.cost``, else token counts
times lockfile pricing) and hard budget checks through :mod:`budget` before every paid call.

The API key is read from ``OPENROUTER_API_KEY``. It is kept in a private attribute, never
printed, never written to the cache and scrubbed from error messages.

Model references are lockfile entries (``models/lock.json``): dicts with at least ``id`` and,
for budget checks, ``pricing`` (USD per token). A bare model id string is accepted when no
budget is attached.
"""

from __future__ import annotations

import json
import math
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NoReturn

from ._common import HttpError, atomic_write_text, canonical_json, http_request, sha256_text
from .budget import Budget

API_BASE = "https://openrouter.ai/api/v1"
ENV_KEY = "OPENROUTER_API_KEY"
CHARS_PER_TOKEN_ESTIMATE = 3.0  # conservative (real ratio is ~4 for en, ~3.3 for de)
PER_MESSAGE_OVERHEAD_TOKENS = 8
# Reasoning effort used when a model reasons by default; the lowest level the model accepts wins.
EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max")


class OpenRouterError(Exception):
    """Request failed. The message never contains the API key."""

    def __init__(self, message: str, *, status: int | None = None, code: Any = None):
        super().__init__(message)
        self.status = status
        self.code = code


class ModelUnavailableError(OpenRouterError):
    """The model id is unknown, retired or has no endpoint. Re-resolve the lockfile and retry."""


class MissingApiKeyError(OpenRouterError):
    pass


@dataclass
class ChatResult:
    text: str
    model: str
    canonical_slug: str | None
    usage: dict = field(default_factory=dict)
    usd: float = 0.0
    estimated: bool = False
    cached: bool = False
    finish_reason: str | None = None
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def prompt_tokens(self) -> int:
        return int(self.usage.get("prompt_tokens") or 0)

    @property
    def completion_tokens(self) -> int:
        return int(self.usage.get("completion_tokens") or 0)


def model_ref(model: dict | str) -> tuple[str, str | None, dict]:
    """(id, canonical_slug, pricing) of a lock entry or bare id."""
    if isinstance(model, str):
        return model, None, {}
    mid = model.get("id")
    if not mid:
        raise ValueError("model entry has no id")
    return str(mid), model.get("canonical_slug"), dict(model.get("pricing") or {})


def cache_key(model: str, messages: list[dict], params: dict) -> str:
    """sha256 over canonical JSON of (model, messages, params)."""
    return sha256_text(canonical_json({"model": model, "messages": messages, "params": params}))


def estimate_prompt_tokens(messages: list[dict]) -> int:
    chars = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            chars += len(content)
        elif isinstance(content, list):
            chars += sum(len(str(part.get("text", ""))) for part in content if isinstance(part, dict))
    return math.ceil(chars / CHARS_PER_TOKEN_ESTIMATE) + PER_MESSAGE_OVERHEAD_TOKENS * len(messages)


def price(pricing: dict, kind: str) -> float | None:
    value = pricing.get(kind)
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v >= 0 else None


def estimate_max_cost(model: dict | str, messages: list[dict], max_tokens: int) -> float | None:
    """Upper bound for one call: estimated prompt tokens and the full completion budget."""
    _, _, pricing = model_ref(model)
    p_in, p_out = price(pricing, "prompt"), price(pricing, "completion")
    if p_in is None or p_out is None:
        return None
    request = price(pricing, "request") or 0.0
    return estimate_prompt_tokens(messages) * p_in + max_tokens * p_out + request


def cost_from_usage(usage: dict, pricing: dict) -> tuple[float, bool]:
    """(usd, estimated). Prefer OpenRouter's reported cost, else tokens times lockfile pricing."""
    cost = usage.get("cost")
    if isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost >= 0:
        return float(cost), False
    p_in, p_out = price(pricing, "prompt") or 0.0, price(pricing, "completion") or 0.0
    pt = int(usage.get("prompt_tokens") or 0)
    ct = int(usage.get("completion_tokens") or 0)
    return pt * p_in + ct * p_out + (price(pricing, "request") or 0.0), True


def reasoning_params(model: dict | str) -> dict:
    """Keep reasoning cheap: the lowest accepted effort, reasoning text excluded.

    Driven by the model's ``reasoning`` object from /api/v1/models (copied into the lockfile),
    so new models need no code change. Models without that object get no reasoning parameter.
    """
    if isinstance(model, str):
        return {}
    info = model.get("reasoning")
    if not isinstance(info, dict):
        return {}
    supported = info.get("supported_efforts")
    mandatory = bool(info.get("mandatory"))
    allowed = [e for e in EFFORT_ORDER if (supported is None or e in supported)]
    if mandatory:
        allowed = [e for e in allowed if e != "none"]
    if supported is not None and not supported:
        return {"reasoning": {"exclude": True}}
    if not allowed:
        return {"reasoning": {"exclude": True}}
    return {"reasoning": {"effort": allowed[0], "exclude": True}}


def _message_text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(p.get("text", "")) for p in content if isinstance(p, dict) and p.get("type") == "text"
        )
    return ""


_UNAVAILABLE_MARKERS = (
    "not a valid model",
    "no endpoints found",
    "model not found",
    "is not available",
    "has been deprecated",
    "no allowed providers",
)


class OpenRouterClient:
    """Chat completions with cache, retries and budget enforcement."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        budget: Budget | None = None,
        cache_dir: str | Path | None = None,
        base_url: str = API_BASE,
        timeout: float = 180.0,
        max_retries: int = 4,
        backoff: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
        read_cache: bool = True,
    ):
        self.__key = api_key if api_key is not None else os.environ.get(ENV_KEY, "")
        self.budget = budget
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.sleep = sleep
        self.read_cache = read_cache
        self.calls = 0
        self.cache_hits = 0

    def __repr__(self) -> str:
        return f"OpenRouterClient(base_url={self.base_url!r}, has_key={self.has_key}, cache={self.cache_dir})"

    @property
    def has_key(self) -> bool:
        return bool(self.__key)

    # -- cache ---------------------------------------------------------------
    def _cache_path(self, key: str) -> Path | None:
        if not self.cache_dir:
            return None
        return self.cache_dir / key[:2] / f"{key}.json"

    def _cache_get(self, key: str) -> dict | None:
        path = self._cache_path(key)
        if not path or not self.read_cache or not path.is_file():
            return None
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            return None

    def _cache_put(self, key: str, model: str, response: dict) -> None:
        path = self._cache_path(key)
        if not path:
            return
        atomic_write_text(
            path, json.dumps({"key": key, "model": model, "response": response}, ensure_ascii=False)
        )

    # -- errors --------------------------------------------------------------
    def _scrub(self, text: str) -> str:
        key = self.__key
        if key and key in text:
            text = text.replace(key, "[redacted]")
        return text

    def _raise_for(self, status: int | None, message: str, code: Any = None) -> NoReturn:
        message = self._scrub(message)
        low = message.lower()
        if status == 404 or any(m in low for m in _UNAVAILABLE_MARKERS):
            raise ModelUnavailableError(message, status=status, code=code)
        raise OpenRouterError(message, status=status, code=code)

    # -- main call -----------------------------------------------------------
    def build_body(
        self, model: dict | str, messages: list[dict], params: dict | None, max_tokens: int
    ) -> dict:
        mid, _, _ = model_ref(model)
        body: dict[str, Any] = {"model": mid, "messages": messages, "max_tokens": int(max_tokens)}
        body.update(reasoning_params(model))
        if params:
            body.update(params)
        # Deprecated on chat completions (usage is always returned) but harmless; kept so older
        # gateway versions still report cost.
        body["usage"] = {"include": True}
        return body

    def chat(
        self,
        model: dict | str,
        messages: list[dict],
        *,
        params: dict | None = None,
        max_tokens: int = 1024,
        role: str = "unspecified",
    ) -> ChatResult:
        mid, slug, pricing = model_ref(model)
        body = self.build_body(model, messages, params, max_tokens)
        key_params = {k: v for k, v in body.items() if k not in ("model", "messages", "usage")}
        key = cache_key(slug or mid, messages, key_params)

        hit = self._cache_get(key)
        if hit is not None and isinstance(hit.get("response"), dict):
            self.cache_hits += 1
            return self._result(hit["response"], mid, slug, pricing, cached=True)

        if not self.has_key:
            raise MissingApiKeyError(f"{ENV_KEY} is not set")

        reserved = 0.0
        if self.budget is not None:
            estimate = estimate_max_cost(model, messages, max_tokens)
            if estimate is None:
                raise OpenRouterError(f"no pricing for {mid}; cannot enforce the budget")
            reserved = self.budget.reserve(estimate)
        try:
            response = self._post("/chat/completions", body)
            result = self._result(response, mid, slug, pricing, cached=False)
        except BaseException:
            if self.budget is not None:
                self.budget.release(reserved)
            raise
        if self.budget is not None:
            self.budget.settle(
                reserved,
                result.usd,
                role=role,
                model=mid,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                canonical_slug=slug,
                estimated=result.estimated,
            )
        self.calls += 1
        self._cache_put(key, slug or mid, response)
        return result

    def _post(self, path: str, body: dict) -> dict:
        headers = {"Authorization": f"Bearer {self.__key}"}
        try:
            response = http_request(
                "POST",
                self.base_url + path,
                body=body,
                headers=headers,
                timeout=self.timeout,
                retries=self.max_retries,
                backoff=self.backoff,
                sleep=self.sleep,
            )
        except HttpError as exc:
            message = exc.body or str(exc)
            code = None
            try:
                err = json.loads(exc.body).get("error") or {}
                message = str(err.get("message") or message)
                code = err.get("code")
            except (ValueError, AttributeError):
                pass
            self._raise_for(exc.status, f"OpenRouter {exc.status}: {message}"[:600], code)
        if not isinstance(response, dict):
            raise OpenRouterError("unexpected response shape from OpenRouter")
        if response.get("error"):
            err = (
                response["error"]
                if isinstance(response["error"], dict)
                else {"message": str(response["error"])}
            )
            code = err.get("code")
            status = code if isinstance(code, int) else None
            self._raise_for(status, f"OpenRouter error: {err.get('message', 'unknown')}"[:600], code)
        return response

    def _result(
        self, response: dict, mid: str, slug: str | None, pricing: dict, *, cached: bool
    ) -> ChatResult:
        choices = response.get("choices") or []
        if not choices:
            raise OpenRouterError("OpenRouter response has no choices")
        choice = choices[0]
        if choice.get("error"):
            err = choice["error"] if isinstance(choice["error"], dict) else {"message": str(choice["error"])}
            self._raise_for(
                None, f"OpenRouter choice error: {err.get('message', 'unknown')}"[:600], err.get("code")
            )
        usage = dict(response.get("usage") or {})
        usd, estimated = (0.0, False) if cached else cost_from_usage(usage, pricing)
        return ChatResult(
            text=_message_text(choice.get("message") or {}),
            model=str(response.get("model") or mid),
            canonical_slug=slug,
            usage=usage,
            usd=usd,
            estimated=estimated,
            cached=cached,
            finish_reason=choice.get("finish_reason"),
            raw=response,
        )
