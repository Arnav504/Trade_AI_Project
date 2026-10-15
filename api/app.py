"""Public read API: gallery JSON, plus a rate-limited background brief."""
import json
import os
import threading
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agent import last_brief, run_agent
from analytics import describe_spans
from api.cache import cache_get, cache_put
from api.rate_limit import RateLimiter
from config import GALLERY_PATH
from database import init_db
from focus import plan_focus, spans_for_plan
from gallery_build import charts_for_focus, compare_with_accounts
from live_slice import ensure_question_slice
from macro_data import ensure_macro, render_macro
from report_contract import DISCLAIMER, QueryRejected, guard_query
from web_context import public_notes


@asynccontextmanager
async def _lifespan(_app):
    init_db()
    yield


app = FastAPI(title="ASAN Macro", version="1.0.0", lifespan=_lifespan)


app.state.limiter = RateLimiter(
    limit=int(os.environ.get("ASAN_RATE_LIMIT", "5")),
    window_seconds=int(os.environ.get("ASAN_RATE_WINDOW", "3600")),
)

_origins = [item.strip() for item in os.environ.get("CORS_ORIGINS", "*").split(",") if item.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_worker = threading.Semaphore(2)
_job_id: ContextVar[str | None] = ContextVar("asan_job_id", default=None)


class AnalyzeIn(BaseModel):
    query: str = Field(min_length=1, max_length=400)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _model_failed(text: str) -> bool:
    return text.startswith(("Error:", "Ollama error", "Gemini API error", "Agent reached max"))


def _empty_payload(query: str, plan: dict) -> dict:
    macro = render_macro(plan["regions"])
    summary = "No official rows for this question."
    return {
        "summary": summary,
        "key_regions_sectors": "Comtrade returned no rows for this reporter, partner, and chapter.",
        "so_what": compare_with_accounts("", macro),
        "whats_next": "A later official release for this slice is the next check. The sample corridors stay available.",
        "disclaimer": DISCLAIMER,
        "focus": query,
        "source": "tool_output",
        "full_report": summary,
        "charts": {"top_flows": [], "yoy": [], "series": []},
        "macro": macro,
        "web_notes": public_notes(query),
        "tool_trace": [],
    }


def _attach_figures(payload: dict, query: str, plan: dict, text: str) -> dict:
    spans = spans_for_plan(plan, query)
    change = describe_spans(spans)
    macro = render_macro(plan["regions"])
    payload["charts"] = charts_for_focus(query)
    payload["macro"] = macro
    payload["web_notes"] = public_notes(query)
    if text.startswith("Refused:"):
        return payload
    if _model_failed(text):
        payload["summary"] = change or "No official rows for this question."
        payload["key_regions_sectors"] = change or "No official rows for this question."
        payload["so_what"] = compare_with_accounts(change, macro)
        payload["whats_next"] = (
            "Another year for this same reporter, partner, and chapter is what would move the chart."
        )
        payload["source"] = "tool_output"
        return payload
    if change and change not in (payload.get("summary") or ""):
        payload["summary"] = f"{change} {payload.get('summary') or ''}".strip()
    so_what = payload.get("so_what") or ""
    if "world bank" not in so_what.lower():
        payload["so_what"] = f"{so_what} {compare_with_accounts(change, macro)}".strip()
    return payload


def _set_stage(stage: str) -> None:
    job_id = _job_id.get()
    if not job_id:
        return
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is not None:
            job["stage"] = stage


def produce_brief(query: str) -> dict:
    try:
        cleaned = guard_query(query)
    except QueryRejected as exc:
        text = f"Refused: {exc}"
        return {
            "summary": text,
            "focus": query,
            "disclaimer": DISCLAIMER,
            "source": "llm",
            "full_report": text,
            "charts": {"top_flows": [], "yoy": [], "series": []},
            "macro": "",
            "web_notes": {"summary": "", "links": []},
        }
    if cleaned:
        query = cleaned

    plan = plan_focus(query)
    _set_stage("Fetching UN Comtrade…")
    info = ensure_question_slice(plan, query)
    _set_stage("Loading World Bank and IMF…")
    ensure_macro(plan.get("regions") or [], plan.get("year_from"), plan.get("year_to"))
    if info["status"] == "empty":
        return _empty_payload(query, plan)

    _set_stage("Writing the brief…")
    text = run_agent(user_query=query)
    brief = last_brief()
    if brief is None:
        payload = {"summary": text, "focus": query, "disclaimer": DISCLAIMER, "source": "llm"}
    else:
        payload = brief.model_dump()
    payload["full_report"] = text
    return _attach_figures(payload, query, plan, text)


def _failed(payload: dict) -> bool:
    """A refusal stays an error. A summary rewritten from tool rows is a finished brief."""
    summary = (payload.get("summary") or "").strip()
    return summary.startswith(("Error:", "Refused:", "Ollama error"))


def _execute(job_id: str) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job["status"] = "running"
        query = job["query"]
    token = _job_id.set(job_id)
    with _worker:
        try:
            payload = produce_brief(query)
            status = "error" if _failed(payload) else "complete"
            if status == "complete":
                cache_put(query, payload)
            with _jobs_lock:
                _jobs[job_id]["status"] = status
                _jobs[job_id]["brief"] = payload
                if status == "error":
                    _jobs[job_id]["error"] = payload.get("summary") or "The model did not return a brief."
        except Exception as exc:
            with _jobs_lock:
                _jobs[job_id]["status"] = "error"
                _jobs[job_id]["error"] = f"Error: {exc}"
        finally:
            _job_id.reset(token)


def _public_job(job: dict) -> dict:
    body = {"status": job["status"], "job_id": job["id"], "cached": False}
    if job.get("stage"):
        body["stage"] = job["stage"]
    if job.get("brief") is not None:
        body["brief"] = job["brief"]
    if job.get("error"):
        body["error"] = job["error"]
    return body


@app.get("/health")
def health():
    return {"ok": True, "gallery": GALLERY_PATH.exists()}


@app.get("/gallery")
def gallery():
    if not GALLERY_PATH.exists():
        raise HTTPException(status_code=404, detail="Gallery has not been exported.")
    return json.loads(GALLERY_PATH.read_text(encoding="utf-8"))


@app.post("/analyze")
def analyze(body: AnalyzeIn, request: Request):
    try:
        query = guard_query(body.query)
    except QueryRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not query:
        raise HTTPException(status_code=400, detail="Enter a short trade focus.")

    cached = cache_get(query)
    if cached:
        return {"status": "complete", "cached": True, "brief": cached}

    if not app.state.limiter.allow(_client_ip(request)):
        raise HTTPException(
            status_code=429,
            detail="Live generation is limited to 5 new queries per hour. The sample briefs stay available.",
        )

    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _jobs[job_id] = {
            "id": job_id,
            "query": query,
            "status": "queued",
            "stage": "Queued",
            "brief": None,
            "error": None,
        }

    if os.environ.get("ASAN_ANALYZE_SYNC", "").strip() == "1":
        _execute(job_id)
        with _jobs_lock:
            return _public_job(_jobs[job_id])

    threading.Thread(target=_execute, args=(job_id,), daemon=True).start()
    return {"status": "queued", "job_id": job_id, "cached": False}


@app.get("/analyze/{job_id}")
def analyze_status(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Unknown job.")
        return _public_job(job)
