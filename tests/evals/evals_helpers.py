"""Helpers shared by the evaluation tests (fake HTTP, test-only stand-ins)."""

from __future__ import annotations

import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class FakeResponse:
    def __init__(self, payload, status=200):
        self._data = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.status = status

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeUrlopen:
    """Routes requests by URL substring. A handler returns a payload, or raises."""

    def __init__(self):
        self.routes: list[tuple[str, object]] = []
        self.requests: list[urllib.request.Request] = []

    def add(self, fragment, handler):
        self.routes.append((fragment, handler))
        return self

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        url = req.full_url if isinstance(req, urllib.request.Request) else str(req)
        for fragment, handler in self.routes:
            if fragment in url:
                result = handler(req) if callable(handler) else handler
                if isinstance(result, BaseException):
                    raise result
                return FakeResponse(result)
        raise AssertionError(f"unexpected request to {url}")

    def bodies(self):
        return [json.loads(r.data.decode("utf-8")) for r in self.requests if r.data]


def http_error(url, code, body=None, headers=None):
    data = json.dumps(body or {"error": {"message": f"status {code}"}}).encode("utf-8")
    return urllib.error.HTTPError(url, code, "error", headers or {}, io.BytesIO(data))


# ---------------------------------------------------------------------------
# Test-only stand-ins for the tooling agent's slopcheck_dev.build.compile_catalog and
# slopcheck_dev.status.derive. Production code imports the real functions; these exist so the
# evaluation tests do not depend on them.


def _provisional_weight(pattern, thresholds):
    return float(((thresholds or {}).get("initial_core") or {}).get(pattern["id"], 0.0))


def standin_compile(patterns, thresholds=None, measurements=None):
    out = []
    for p in patterns:
        e = dict(p)
        if p.get("status") == "core":
            weight = _provisional_weight(p, thresholds)
            e["effective_status"] = "core"
            e["weight"] = weight
            e["weight_source"] = "provisional" if weight else "none"
        else:
            e["effective_status"] = p.get("status", "observation")
            e["weight"] = 0.0
            e["weight_source"] = "none"
        out.append(e)
    vt = (thresholds or {}).get("verdict_provisional") or {"yellow": 2.0, "red": 5.0}
    return {
        "catalog_version": "test",
        "short_text_max_words": 150,
        "verdict_thresholds": {"yellow": vt["yellow"], "red": vt["red"], "source": "provisional"},
        "patterns": out,
    }


def standin_derive(pattern, measurement, thresholds):
    declared = pattern.get("status")
    if declared == "observation":
        return "observation", 0.0, "none"
    if measurement is None:
        if declared == "core":
            return "core", _provisional_weight(pattern, thresholds), "provisional"
        return "candidate", 0.0, "none"
    if measurement.get("meets_fading") and declared == "core":
        return "fading", 0.0, "none"
    if measurement.get("meets_core") or declared == "core":
        return "core", measurement.get("weight") or 0.0, "measured"
    return "candidate", 0.0, "none"
