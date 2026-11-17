from __future__ import annotations

import pytest
from evals_helpers import http_error

from slopcheck_dev.evals import budget as B
from slopcheck_dev.evals import openrouter as O

KEY = "sk-or-test-secret-123"
MODEL = {
    "id": "acme/chat-1.1",
    "canonical_slug": "acme/chat-1.1-20250601",
    "pricing": {"prompt": 1e-6, "completion": 2e-6},
    "reasoning": {"mandatory": False, "supported_efforts": ["high", "low", "none"]},
}
MESSAGES = [{"role": "user", "content": "Say hello."}]


def completion(text="Hello.", cost=0.0012, usage=None):
    u = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    if cost is not None:
        u["cost"] = cost
    if usage:
        u.update(usage)
    return {"id": "gen-1", "model": "acme/chat-1.1", "choices": [{"message": {"content": text},
                                                                    "finish_reason": "stop"}], "usage": u}


def client(tmp_path, budget=None, **kw):
    return O.OpenRouterClient(KEY, budget=budget, cache_dir=tmp_path / "cache", sleep=lambda s: None, **kw)


def test_cache_key_is_deterministic_and_sensitive():
    a = O.cache_key("m", MESSAGES, {"max_tokens": 10, "temperature": 0})
    b = O.cache_key("m", [dict(MESSAGES[0])], {"temperature": 0, "max_tokens": 10})
    assert a == b and len(a) == 64
    assert a != O.cache_key("m2", MESSAGES, {"max_tokens": 10, "temperature": 0})
    assert a != O.cache_key("m", MESSAGES, {"max_tokens": 11, "temperature": 0})
    assert a != O.cache_key("m", [{"role": "user", "content": "Say hi."}], {"max_tokens": 10, "temperature": 0})


def test_chat_success_cost_and_cache(tmp_path, fake_http):
    fake_http.add("/chat/completions", completion())
    c = client(tmp_path)
    r = c.chat(MODEL, MESSAGES, max_tokens=50, role="judges")
    assert r.text == "Hello." and r.usd == pytest.approx(0.0012) and not r.estimated and not r.cached
    body = fake_http.bodies()[0]
    assert body["model"] == "acme/chat-1.1" and body["max_tokens"] == 50
    assert body["usage"] == {"include": True}
    assert body["reasoning"] == {"effort": "none", "exclude": True}
    assert fake_http.requests[0].headers["Authorization"] == f"Bearer {KEY}"
    again = c.chat(MODEL, MESSAGES, max_tokens=50, role="judges")
    assert again.cached and again.text == "Hello." and again.usd == 0.0
    assert len(fake_http.requests) == 1
    cached_files = list((tmp_path / "cache").rglob("*.json"))
    assert cached_files and KEY not in cached_files[0].read_text()


def test_cost_falls_back_to_lockfile_pricing(tmp_path, fake_http):
    fake_http.add("/chat/completions", completion(cost=None, usage={"prompt_tokens": 1000, "completion_tokens": 500}))
    r = client(tmp_path).chat(MODEL, MESSAGES)
    assert r.estimated and r.usd == pytest.approx(1000 * 1e-6 + 500 * 2e-6)


def test_budget_blocks_before_any_request(tmp_path, fake_http, thresholds):
    fake_http.add("/chat/completions", completion())
    caps = B.Caps(monthly_usd=26, run_usd=0.5, call_usd=0.001, run_kind="pull_request")
    b = B.Budget(B.Ledger(tmp_path / "l.json"), caps, "r")
    with pytest.raises(B.BudgetExceeded):
        client(tmp_path, b).chat(MODEL, MESSAGES, max_tokens=4000)
    assert fake_http.requests == []


def test_budget_records_actual_cost(tmp_path, fake_http, thresholds):
    fake_http.add("/chat/completions", completion(cost=0.004))
    b = B.Budget(B.Ledger(tmp_path / "l.json"), B.load_caps(thresholds, "scheduled"), "r")
    client(tmp_path, b).chat(MODEL, MESSAGES, max_tokens=100, role="generators")
    st = b.status()
    assert st["run_total_usd"] == pytest.approx(0.004)
    entry = b.ledger.entries[0]
    assert entry["role"] == "generators" and entry["model"] == "acme/chat-1.1"
    assert entry["canonical_slug"] == "acme/chat-1.1-20250601"


def test_budget_requires_pricing(tmp_path, fake_http, thresholds):
    b = B.Budget(B.Ledger(None), B.load_caps(thresholds, "scheduled"), "r")
    with pytest.raises(O.OpenRouterError, match="no pricing"):
        client(tmp_path, b).chat({"id": "x/y"}, MESSAGES)


def test_failed_call_releases_reservation(tmp_path, fake_http, thresholds):
    fake_http.add("/chat/completions", lambda req: http_error(req.full_url, 400, {"error": {"message": "bad"}}))
    b = B.Budget(B.Ledger(None), B.load_caps(thresholds, "pull_request"), "r")
    with pytest.raises(O.OpenRouterError):
        client(tmp_path, b).chat(MODEL, MESSAGES, max_tokens=100)
    assert b._reserved == 0.0 and b.ledger.entries == []


def test_retries_with_backoff(tmp_path, fake_http):
    calls = {"n": 0}

    def flaky(req):
        calls["n"] += 1
        if calls["n"] < 3:
            return http_error(req.full_url, 429 if calls["n"] == 1 else 503)
        return completion()

    fake_http.add("/chat/completions", flaky)
    sleeps = []
    c = O.OpenRouterClient(KEY, cache_dir=None, sleep=sleeps.append, backoff=1.0)
    assert c.chat(MODEL, MESSAGES).text == "Hello."
    assert calls["n"] == 3 and len(sleeps) == 2 and sleeps[1] >= sleeps[0]


def test_gives_up_after_max_retries(tmp_path, fake_http):
    fake_http.add("/chat/completions", lambda req: http_error(req.full_url, 502))
    c = O.OpenRouterClient(KEY, sleep=lambda s: None, max_retries=2)
    with pytest.raises(O.OpenRouterError):
        c.chat(MODEL, MESSAGES)
    assert len(fake_http.requests) == 3


@pytest.mark.parametrize(
    ("status", "message"),
    [(404, "Not found"), (400, "acme/x is not a valid model ID"), (404, "No endpoints found for acme/x")],
)
def test_model_unavailable(tmp_path, fake_http, status, message):
    fake_http.add("/chat/completions", lambda req: http_error(req.full_url, status, {"error": {"message": message}}))
    with pytest.raises(O.ModelUnavailableError):
        client(tmp_path).chat(MODEL, MESSAGES)


def test_error_in_200_body(tmp_path, fake_http):
    fake_http.add("/chat/completions", {"error": {"message": "upstream failed", "code": 502}})
    with pytest.raises(O.OpenRouterError, match="upstream failed"):
        client(tmp_path).chat(MODEL, MESSAGES)


def test_key_never_leaks(tmp_path, fake_http):
    fake_http.add("/chat/completions",
                  lambda req: http_error(req.full_url, 401, {"error": {"message": f"bad key {KEY}"}}))
    c = client(tmp_path)
    with pytest.raises(O.OpenRouterError) as exc:
        c.chat(MODEL, MESSAGES)
    assert KEY not in str(exc.value)
    assert "[redacted]" in str(exc.value)
    assert KEY not in repr(c)


def test_missing_key(tmp_path):
    c = O.OpenRouterClient(cache_dir=tmp_path)
    assert not c.has_key
    with pytest.raises(O.MissingApiKeyError):
        c.chat(MODEL, MESSAGES)


def test_key_from_environment(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-key")
    assert O.OpenRouterClient().has_key


def test_reasoning_params():
    assert O.reasoning_params("plain-id") == {}
    assert O.reasoning_params({"id": "a"}) == {}
    assert O.reasoning_params({"id": "a", "reasoning": {"mandatory": True, "supported_efforts": ["high", "low"]}}) == {
        "reasoning": {"effort": "low", "exclude": True}
    }
    assert O.reasoning_params({"id": "a", "reasoning": {"mandatory": False, "supported_efforts": None}}) == {
        "reasoning": {"effort": "none", "exclude": True}
    }
    assert O.reasoning_params({"id": "a", "reasoning": {"mandatory": True, "supported_efforts": None}}) == {
        "reasoning": {"effort": "minimal", "exclude": True}
    }


def test_estimates():
    est = O.estimate_max_cost(MODEL, MESSAGES, 100)
    assert est == pytest.approx(O.estimate_prompt_tokens(MESSAGES) * 1e-6 + 100 * 2e-6)
    assert O.estimate_max_cost({"id": "x"}, MESSAGES, 100) is None
    assert O.cost_from_usage({"cost": 0.5}, {}) == (0.5, False)
    assert O.cost_from_usage({"prompt_tokens": 2, "completion_tokens": 3}, {"prompt": 1.0, "completion": 2.0}) == (
        8.0,
        True,
    )


def test_content_parts_are_joined(tmp_path, fake_http):
    resp = completion()
    resp["choices"][0]["message"]["content"] = [{"type": "text", "text": "Hel"}, {"type": "text", "text": "lo"}]
    fake_http.add("/chat/completions", resp)
    assert client(tmp_path).chat(MODEL, MESSAGES).text == "Hello"


def test_refuses_plain_http():
    c = O.OpenRouterClient(KEY, base_url="http://example.invalid/api")
    with pytest.raises(ValueError):
        c.chat(MODEL, MESSAGES)
