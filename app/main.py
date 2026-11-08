import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db, index, ingest, llm, pipeline

RUN_LOCK = threading.Lock()   # local LLMs are slow: one analysis at a time


@asynccontextmanager
async def lifespan(app):
    db.init_db()
    yield


app = FastAPI(title="Repo2Design", lifespan=lifespan)


class AnalyzeIn(BaseModel):
    repo_url: str = Field(max_length=200)


class AskIn(BaseModel):
    job_id: str
    question: str = Field(min_length=3, max_length=500)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    t = time.time()
    resp = await call_next(request)
    if request.url.path.startswith("/api"):
        db.log("http", f"{request.method} {request.url.path.split('/')[2] if request.url.path.count('/') > 1 else ''}",
               (time.time() - t) * 1000, status=resp.status_code)
    return resp


def _worker(job_id: str):
    try:
        pipeline.run(job_id)
    finally:
        RUN_LOCK.release()


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/analyze")
def analyze(body: AnalyzeIn, bg: BackgroundTasks):
    try:
        _, _, url = ingest.parse_repo_url(body.repo_url)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not RUN_LOCK.acquire(blocking=False):
        raise HTTPException(429, "Another analysis is running. Please try again in a few minutes.")
    try:
        job_id = db.create_job(url)
    except Exception:
        RUN_LOCK.release()
        raise
    bg.add_task(_worker, job_id)
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return {k: job[k] for k in ("id", "status", "progress", "message", "error", "cached", "repo_url")}


@app.get("/api/report/{job_id}")
def report(job_id: str):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["status"] != "done":
        raise HTTPException(409, f"Job is {job['status']}")
    return db.get_report(job["repo_key"])


@app.post("/api/ask")
def ask(body: AskIn):
    job = db.get_job(body.job_id)
    if not job or job["status"] != "done" or not index.exists(job["repo_key"]):
        raise HTTPException(404, "Analyze a repository first")
    chunks = index.load(job["repo_key"]).search(body.question, k=6)
    from .generate import fmt_chunks
    try:
        answer = llm.ask(f"Question about the codebase: {body.question}\n\nCode excerpts:\n{fmt_chunks(chunks)}\n\n"
                         "Answer using only these excerpts and mention file names. "
                         "If the excerpts don't contain the answer, say so.", stage="ask")
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    return {"answer": answer,
            "sources": [{"path": c["path"], "start": c["start"], "end": c["end"]} for c in chunks]}


@app.get("/api/stats")
def stats():
    return db.stats()


app.mount("/", StaticFiles(directory=str(Path(__file__).resolve().parent.parent / "web"), html=True), name="web")
