"""Shared helpers for the evaluation package: paths, YAML/JSON I/O, hashing, HTTP."""

from __future__ import annotations

import datetime as _dt
import gzip
import hashlib
import json
import os
import random
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any

USER_AGENT = "slopcheck-evals/0.1 (+urllib)"
RETRY_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524})
WORD_RE = re.compile(r"\w+(?:['’]\w+)*")


# ---------------------------------------------------------------------------
# paths and loading


def repo_root() -> Path:
    """Repository root: env SLOPCHECK_ROOT, else the first parent holding governance/thresholds.yaml."""
    env = os.environ.get("SLOPCHECK_ROOT")
    if env:
        return Path(env).resolve()
    candidates = [Path(__file__).resolve(), Path.cwd().resolve()]
    for start in candidates:
        for parent in [start, *start.parents]:
            if (parent / "governance" / "thresholds.yaml").is_file():
                return parent
    return Path.cwd().resolve()


def dates_to_str(obj: Any) -> Any:
    """Convert date and datetime values (as produced by YAML loaders) to ISO strings, recursively."""
    if isinstance(obj, dict):
        return {k: dates_to_str(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [dates_to_str(v) for v in obj]
    if isinstance(obj, _dt.datetime):
        return obj.isoformat()
    if isinstance(obj, _dt.date):
        return obj.isoformat()
    return obj


def load_yaml(path: str | Path) -> Any:
    import yaml  # dev dependency, imported lazily

    with open(path, encoding="utf-8") as fh:
        return dates_to_str(yaml.safe_load(fh))


def load_thresholds(root: Path | None = None) -> dict:
    root = root or repo_root()
    return load_yaml(root / "governance" / "thresholds.yaml") or {}


def load_patterns(root: Path | None = None, modality: str | None = "text") -> list[dict]:
    """Load pattern YAML files (patterns/<modality>/*.yaml), sorted by id."""
    root = root or repo_root()
    base = root / "patterns"
    dirs = [base / modality] if modality else sorted(p for p in base.iterdir() if p.is_dir())
    out: list[dict] = []
    for d in dirs:
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.yaml")):
            data = load_yaml(f)
            if isinstance(data, dict) and data.get("id"):
                out.append(data)
    out.sort(key=lambda p: p["id"])
    return out


# ---------------------------------------------------------------------------
# hashing and split


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def split_of(doc_id: str) -> str:
    """Corpus split per docs/architecture.md 6.1: sha256(doc_id) % 10 < 5 is dev, else holdout."""
    return "dev" if int(sha256_text(doc_id), 16) % 10 < 5 else "holdout"


def seeded_rng(*parts: object) -> random.Random:
    """Deterministic PRNG for sampling (not for security)."""
    seed = int(sha256_text(":".join(str(p) for p in parts)), 16)
    return random.Random(seed)  # noqa: S311 - deterministic sampling, not cryptography


def count_words(text: str) -> int:
    return len(WORD_RE.findall(text))


# ---------------------------------------------------------------------------
# time


def utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)


def iso(dt: _dt.datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> _dt.datetime:
    text = value.strip().replace("Z", "+00:00")
    dt = _dt.datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# file I/O


def atomic_write_text(path: str | Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def write_json(path: str | Path, obj: Any) -> None:
    atomic_write_text(path, json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False) + "\n")


def read_json(path: str | Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def iter_jsonl(path: str | Path) -> Iterator[dict]:
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_jsonl(path: str | Path, records: Iterable[dict]) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    n = 0
    if path.suffix == ".gz":
        # mtime=0 keeps the gzip bytes reproducible for identical content
        with open(tmp, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
            for rec in records:
                gz.write((json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8"))
                n += 1
    else:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            for rec in records:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n += 1
    os.replace(tmp, path)
    return n


# ---------------------------------------------------------------------------
# HTTP (urllib only)


class HttpError(Exception):
    """HTTP failure with status code and a short body excerpt (never request headers)."""

    def __init__(
        self,
        status: int | None,
        message: str,
        body: str = "",
        url: str = "",
        *,
        retry_after: float | None = None,
        network: bool = False,
    ):
        super().__init__(f"HTTP {status}: {message}" if status else message)
        self.status = status
        self.body = body[:2000]
        self.url = url
        self.retry_after = retry_after
        self.network = network  # no HTTP response (timeout, refused or dropped connection)


def _retry_after(headers: Any) -> float | None:
    if headers is None:
        return None
    value = headers.get("Retry-After") if hasattr(headers, "get") else None
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def http_request(
    method: str,
    url: str,
    *,
    body: Any = None,
    headers: dict[str, str] | None = None,
    timeout: float = 60.0,
    retries: int = 4,
    backoff: float = 1.5,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """JSON request with retries and exponential backoff. Returns the decoded JSON body.

    Only https URLs are allowed. Error messages carry status and body excerpt, never headers,
    so an Authorization header cannot leak into logs.
    """
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ValueError(f"refusing non-https URL: {url}")
    data = None
    hdrs = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if headers:
        hdrs.update(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    attempt = 0
    while True:
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)  # noqa: S310 - https only
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                raw = resp.read()
            text = raw.decode("utf-8", errors="replace")
            return json.loads(text) if text.strip() else None
        except urllib.error.HTTPError as exc:
            try:
                err_body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                err_body = ""
            status = exc.code
            if status in RETRY_STATUS and attempt < retries:
                wait = _retry_after(exc.headers)
                if wait is None:
                    wait = backoff * (2**attempt)
                sleep(min(wait, 60.0) + random.random() * 0.25)  # noqa: S311 - jitter only
                attempt += 1
                continue
            raise HttpError(
                status,
                exc.reason if isinstance(exc.reason, str) else "error",
                err_body,
                url,
                retry_after=_retry_after(exc.headers),
            ) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            if attempt < retries:
                sleep(min(backoff * (2**attempt), 60.0))
                attempt += 1
                continue
            reason = getattr(exc, "reason", exc)
            raise HttpError(None, f"network error: {reason}", "", url, network=True) from None
        except json.JSONDecodeError as exc:
            raise HttpError(None, f"invalid JSON from {url}: {exc}", "", url) from None


def http_get_json(url: str, **kwargs: Any) -> Any:
    return http_request("GET", url, **kwargs)
