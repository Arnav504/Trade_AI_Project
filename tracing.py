"""Per-run tool traces. A context var keeps concurrent API jobs from sharing a list."""
import time
from contextvars import ContextVar
from typing import Any, Callable, Optional


_trace: ContextVar[Optional[list]] = ContextVar("asan_tool_trace", default=None)


def begin_trace():
    buf: list[dict[str, Any]] = []
    token = _trace.set(buf)
    return token


def end_trace(token) -> None:
    _trace.reset(token)


def current_trace() -> list:
    buf = _trace.get()
    return buf if buf is not None else []


def record_trace(name: str, args: Any, latency_ms: float) -> None:
    buf = _trace.get()
    if buf is None:
        return
    if isinstance(args, dict):
        safe = {k: v for k, v in args.items() if v is not None}
    else:
        safe = {"args": args}
    buf.append({"name": name, "args": safe, "latency_ms": round(latency_ms, 2)})


def traced_call(name: str, fn: Callable, **kwargs):
    start = time.perf_counter()
    try:
        return fn(**kwargs)
    except Exception as exc:
        return f"Tool error: {exc}"
    finally:
        record_trace(name, kwargs, (time.perf_counter() - start) * 1000)
