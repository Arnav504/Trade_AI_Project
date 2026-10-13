"""Public read API: gallery JSON, plus a rate-limited background brief."""
import json
import os
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agent import last_brief, run_agent
from api.cache import cache_get, cache_put
from api.rate_limit import RateLimiter
from config import GALLERY_PATH
from report_contract import DISCLAIMER, QueryRejected, guard_query

app = FastAPI(title="ASAN Macro", version="1.0.0")
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


class AnalyzeIn(BaseModel):
    query: str = Field(min_length=1, max_length=400)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def produce_brief(query: str) -> dict:
    text = run_agent(user_query=query)
    brief = last_brief()
    if brief is None:
        payload = {"summary": text, "focus": query, "disclaimer": DISCLAIMER, "source": "llm"}
    else:
        payload = brief.model_dump()
    payload["full_report"] = text
    return payload


def _failed(payload: dict) -> bool:
    summary = (payload.get("summary") or "").strip()
    report = (payload.get("full_report") or "").strip()
    for text in (summary, report):
        if text.startswith("Error:") or text.startswith("Refused:") or text.startswith("Ollama error"):
            return True
    return False


def _execute(job_id: str) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job["status"] = "running"
        query = job["query"]
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


def _public_job(job: dict) -> dict:
    body = {"status": job["status"], "job_id": job["id"], "cached": False}
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
        _jobs[job_id] = {"id": job_id, "query": query, "status": "queued", "brief": None, "error": None}

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
