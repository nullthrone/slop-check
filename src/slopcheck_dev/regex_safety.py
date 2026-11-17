"""Regex safety checks for detector payloads (docs/architecture.md section 3, rule 5).

Three checks per expression:

1. it compiles with ``re.MULTILINE`` (the engine's flags);
2. a static scan finds no unbounded quantifier (``*``, ``+``, ``{n,}``) applied to a group
   that itself contains an unbounded quantifier, such as ``(a+)+`` or ``(?:\\w+\\s?)*``;
3. it runs on 50 kB adversarial inputs in a separate Python process, each input within
   200 ms. A worker that does not answer in time is killed and the expression fails.

The static scan is deliberately simple: it tokenizes escapes, character classes, groups
and quantifiers without building a full parse tree. Bounded repetition such as
``(?:\\w+\\s){1,5}`` is allowed.
"""

from __future__ import annotations

import json
import queue
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field

INPUT_SIZE = 50_000
TIME_LIMIT_MS = 200


# ---------------------------------------------------------------------------
# compile and static scan


def compile_error(pattern: str) -> str | None:
    """None if ``pattern`` compiles with ``re.MULTILINE``, else the error text."""
    try:
        re.compile(pattern, re.MULTILINE)
    except re.error as exc:
        return str(exc)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


_QUANT_BRACE = re.compile(r"\{(\d*)(,?)(\d*)\}")


@dataclass
class _Frame:
    start: int
    unbounded: bool = False


@dataclass
class _Atom:
    start: int
    unbounded_inside: bool = False


def _skip_class(p: str, i: int) -> int:
    """Index after the character class starting at ``p[i] == '['``."""
    j = i + 1
    if j < len(p) and p[j] == "^":
        j += 1
    if j < len(p) and p[j] == "]":
        j += 1
    while j < len(p) and p[j] != "]":
        if p[j] == "\\":
            j += 2
        elif p[j] == "[" and p.startswith("[:", j):
            end = p.find(":]", j + 2)
            j = end + 2 if end != -1 else j + 1
        else:
            j += 1
    return j + 1


def _quantifier(p: str, i: int) -> tuple[int, bool] | None:
    """Parse a quantifier at ``p[i]``: (index after it, unbounded) or None if not one."""
    c = p[i]
    if c in "*+":
        end, unbounded = i + 1, True
    elif c == "?":
        end, unbounded = i + 1, False
    elif c == "{":
        m = _QUANT_BRACE.match(p, i)
        if not m or (not m.group(1) and not m.group(3)) or (not m.group(1) and not m.group(2)):
            return None
        end = m.end()
        unbounded = bool(m.group(2)) and not m.group(3)
    else:
        return None
    if end < len(p) and p[end] in "?+":  # lazy or possessive modifier
        end += 1
    return end, unbounded


def _skip_group_prefix(p: str, i: int) -> int:
    """Index after ``(`` and its extension prefix (``?:``, ``?P<name>``, ``?<=``, ``?i:``...)."""
    j = i + 1
    if j >= len(p) or p[j] != "?":
        return j
    j += 1
    if j < len(p) and p[j] == "P":
        j += 1
        if j < len(p) and p[j] == "<":
            end = p.find(">", j)
            return end + 1 if end != -1 else len(p)
        if j < len(p) and p[j] == "=":  # (?P=name) backreference
            end = p.find(")", j)
            return end if end != -1 else len(p)
        return j
    if p.startswith("<=", j) or p.startswith("<!", j):
        return j + 2
    if j < len(p) and p[j] == "<":
        end = p.find(">", j)
        return end + 1 if end != -1 else len(p)
    if j < len(p) and p[j] in ":=!>":
        return j + 1
    if j < len(p) and p[j] == "(":  # conditional (?(1)...)
        end = p.find(")", j)
        return end + 1 if end != -1 else len(p)
    m = re.match(r"[aiLmsux-]+[:)]?", p[j:])
    if m:
        return j + m.end() - (1 if m.group(0).endswith(")") else 0)
    return j


def nested_quantifiers(pattern: str) -> list[str]:
    """Fragments where an unbounded quantifier applies to a group containing one.

    Returns an empty list for safe expressions.
    """
    p = pattern
    stack = [_Frame(start=0)]
    last: _Atom | None = None
    found: list[str] = []
    i = 0
    n = len(p)
    while i < n:
        c = p[i]
        if c == "\\":
            last = _Atom(start=i)
            i += 2
            continue
        if c == "[":
            last = _Atom(start=i)
            i = _skip_class(p, i)
            continue
        if c == "(":
            if p.startswith("(?#", i):
                end = p.find(")", i)
                i = end + 1 if end != -1 else n
                continue
            stack.append(_Frame(start=i))
            last = None
            i = _skip_group_prefix(p, i)
            continue
        if c == ")":
            if len(stack) > 1:
                frame = stack.pop()
                stack[-1].unbounded = stack[-1].unbounded or frame.unbounded
                last = _Atom(start=frame.start, unbounded_inside=frame.unbounded)
            else:
                last = _Atom(start=i)
            i += 1
            continue
        if c in "*+?{":
            q = _quantifier(p, i)
            if q is None:
                last = _Atom(start=i)
                i += 1
                continue
            end, unbounded = q
            if unbounded:
                if last is not None and last.unbounded_inside:
                    found.append(p[last.start : end])
                stack[-1].unbounded = True
            last = None
            i = end
            continue
        if c == "|":
            last = None
            i += 1
            continue
        last = _Atom(start=i)
        i += 1
    return found


# ---------------------------------------------------------------------------
# adversarial inputs


def _fill(unit: str, size: int = INPUT_SIZE) -> str:
    if not unit:
        unit = "a"
    return (unit * (size // len(unit) + 1))[:size]


def generic_inputs(size: int = INPUT_SIZE) -> dict[str, str]:
    """Inputs that provoke backtracking in typical prose regexes."""
    mixed = (
        "It is not just this, it is not only that; and it is not about this — "
        "Es ist nicht nur das, sondern auch: „Nicht nur“ – ‚weniger als‘ … "
        "Moreover, furthermore, additionally, delve 2026-11-17 #12 (x) [y] {z} "
        '"quoted" ’s ’t ** __ ## - * 1. '
    )
    return {
        "letters": _fill("a", size),
        "words": _fill("word ", size),
        "commas": _fill("word, ", size),
        "spaces": _fill(" ", size),
        "newlines": _fill("a\n", size),
        "punctuation": _fill(".,;:—–-!?… ", size),
        "mixed": _fill(mixed, size),
        "mixed_unterminated": _fill(mixed.replace(".", "").replace("?", "").replace("!", ""), size),
    }


def example_input(examples: list[str], size: int = INPUT_SIZE) -> str | None:
    """Positive examples joined without sentence ends and repeated to ``size``."""
    parts = [" ".join(str(e).split()).rstrip(".!?…") for e in examples if str(e).strip()]
    if not parts:
        return None
    return _fill(" ".join(parts) + " ", size)


# ---------------------------------------------------------------------------
# timing in a subprocess

_WORKER = r"""
import json, re, sys, time
job = json.loads(sys.stdin.read())
inputs = job["inputs"]
sys.stdout.write("ready\n"); sys.stdout.flush()
for i, item in enumerate(job["items"]):
    out = {"i": i, "ms": {}}
    try:
        rx = re.compile(item["pattern"], re.MULTILINE)
        for name in item["inputs"]:
            t0 = time.perf_counter()
            for _ in rx.finditer(inputs[name]):
                pass
            out["ms"][name] = round((time.perf_counter() - t0) * 1000, 2)
    except Exception as exc:
        out["error"] = type(exc).__name__ + ": " + str(exc)
    sys.stdout.write(json.dumps(out) + "\n"); sys.stdout.flush()
"""


@dataclass
class TimingItem:
    """One expression and the names of the inputs it runs on."""

    pattern: str
    inputs: list[str]
    label: str = ""


@dataclass
class TimingResult:
    item: TimingItem
    ms: dict[str, float] = field(default_factory=dict)
    error: str | None = None
    timed_out: bool = False

    def problems(self, limit_ms: float = TIME_LIMIT_MS) -> list[str]:
        out = []
        if self.timed_out:
            out.append(f"did not finish on adversarial input within {limit_ms:.0f} ms (worker killed)")
        if self.error:
            out.append(f"failed on adversarial input: {self.error}")
        slow = {k: v for k, v in self.ms.items() if v > limit_ms}
        for name, ms in sorted(slow.items()):
            out.append(f"took {ms:.0f} ms on the 50 kB adversarial input '{name}' (limit {limit_ms:.0f} ms)")
        return out


def _reader(stream, q: queue.Queue) -> None:
    for line in stream:
        q.put(line)
    q.put(None)


def _start(items: list[TimingItem], inputs: dict[str, str]) -> tuple[subprocess.Popen, queue.Queue]:
    needed = sorted({name for it in items for name in it.inputs})
    payload = {
        "inputs": {k: inputs[k] for k in needed},
        "items": [{"pattern": it.pattern, "inputs": it.inputs} for it in items],
    }
    proc = subprocess.Popen(  # noqa: S603 - fixed interpreter and inline code, no shell
        [sys.executable, "-I", "-c", _WORKER],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
    )
    q: queue.Queue = queue.Queue()
    threading.Thread(target=_reader, args=(proc.stdout, q), daemon=True).start()
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(payload, ensure_ascii=False))
    proc.stdin.close()
    return proc, q


def _stop(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.kill()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:  # pragma: no cover - kill should not hang
        pass


def time_patterns(
    items: list[TimingItem],
    inputs: dict[str, str],
    limit_ms: float = TIME_LIMIT_MS,
    startup_timeout: float = 30.0,
) -> list[TimingResult]:
    """Run every item in a worker process; restart the worker after a hang.

    The hard deadline per expression is ``limit_ms`` per input plus one second, so slow but
    finite expressions report their time while runaway backtracking is killed.
    """
    results = [TimingResult(item=it) for it in items]
    pos = 0
    while pos < len(items):
        batch = items[pos:]
        proc, q = _start(batch, inputs)
        try:
            line = q.get(timeout=startup_timeout)
            if line is None or line.strip() != "ready":
                for r in results[pos:]:
                    r.error = "regex worker did not start"
                return results
            done = 0
            while done < len(batch):
                deadline = len(batch[done].inputs) * limit_ms / 1000.0 + 1.0
                t0 = time.monotonic()
                try:
                    line = q.get(timeout=deadline)
                except queue.Empty:
                    results[pos + done].timed_out = True
                    done += 1
                    break
                if line is None:  # worker died (for example on memory exhaustion)
                    results[pos + done].error = "regex worker exited unexpectedly"
                    done += 1
                    break
                data = json.loads(line)
                res = results[pos + data["i"]]
                res.ms = data.get("ms") or {}
                res.error = data.get("error")
                if time.monotonic() - t0 > deadline:
                    res.timed_out = True
                done += 1
            pos += done
        finally:
            _stop(proc)
    return results
