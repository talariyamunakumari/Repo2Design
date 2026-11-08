"""SQL layer: jobs, cached reports, and request/LLM latency logs."""
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from . import config

os.makedirs(config.DATA_DIR, exist_ok=True)
_sqlite = config.DATABASE_URL.startswith("sqlite")
engine = create_engine(config.DATABASE_URL, pool_pre_ping=True,
                       connect_args={"check_same_thread": False} if _sqlite else {})
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    repo_url: Mapped[str] = mapped_column(String(300))
    repo_key: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(String(300), default="")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cached: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class Report(Base):
    __tablename__ = "reports"
    repo_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    repo_url: Mapped[str] = mapped_column(String(300))
    commit_sha: Mapped[str] = mapped_column(String(64))
    data: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RequestLog(Base):
    __tablename__ = "request_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(10))          # "http" | "llm" | "embed"
    stage: Mapped[str] = mapped_column(String(100))        # endpoint path or pipeline stage
    model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    job_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


@contextmanager
def session():
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def init_db():
    Base.metadata.create_all(engine)
    with session() as s:   # jobs left running by a crash/restart can never finish
        for j in s.scalars(select(Job).where(Job.status.in_(["queued", "running"]))):
            j.status, j.error, j.finished_at = "failed", "Server restarted", now()


def create_job(repo_url: str) -> str:
    jid = str(uuid.uuid4())
    with session() as s:
        s.add(Job(id=jid, repo_url=repo_url))
    return jid


def update_job(job_id: str, **fields):
    with session() as s:
        j = s.get(Job, job_id)
        for k, v in fields.items():
            setattr(j, k, v)
        if fields.get("status") in ("done", "failed"):
            j.finished_at = now()


def get_job(job_id: str):
    with session() as s:
        j = s.get(Job, job_id)
        if not j:
            return None
        return {c.name: getattr(j, c.name) for c in Job.__table__.columns}


def save_report(repo_key: str, repo_url: str, sha: str, data: dict):
    with session() as s:
        s.merge(Report(repo_key=repo_key, repo_url=repo_url, commit_sha=sha,
                       data=json.dumps(data), created_at=now()))


def get_report(repo_key: str):
    with session() as s:
        r = s.get(Report, repo_key)
        return json.loads(r.data) if r else None


def log(kind, stage, latency_ms, model=None, status=None, job_id=None, error=None):
    try:
        with session() as s:
            s.add(RequestLog(kind=kind, stage=stage, model=model, latency_ms=int(latency_ms),
                             status=status, job_id=job_id, error=(error or None) and str(error)[:500]))
    except Exception:
        pass   # logging must never break the request


def stats():
    with session() as s:
        rows = s.execute(select(RequestLog.kind, RequestLog.stage, func.count(),
                                func.avg(RequestLog.latency_ms), func.max(RequestLog.latency_ms))
                         .group_by(RequestLog.kind, RequestLog.stage)).all()
        errors = s.scalar(select(func.count()).where(RequestLog.error.is_not(None)))
    return {"errors": errors or 0,
            "by_stage": [{"kind": k, "stage": st, "calls": c, "avg_ms": round(a or 0), "max_ms": m}
                         for k, st, c, a, m in rows]}
