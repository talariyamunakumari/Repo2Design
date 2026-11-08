"""End-to-end job: clone -> analyze -> chunk -> embed -> generate -> save."""
import shutil
import traceback

from . import db, generate, index, ingest
from .analyze import analyze_repo
from .chunk import chunk_files


def run(job_id: str):
    root = None
    step = lambda pct, msg: db.update_job(job_id, status="running", progress=pct, message=msg)
    try:
        owner, repo, url = ingest.parse_repo_url(db.get_job(job_id)["repo_url"])
        step(3, "Checking repository")
        sha = ingest.remote_head_sha(url)
        key = f"{owner}_{repo}_{sha[:10]}"
        db.update_job(job_id, repo_key=key)

        if db.get_report(key) and index.exists(key):          # cache hit: same repo + same commit
            db.update_job(job_id, status="done", progress=100, message="Loaded from cache", cached=1)
            return

        step(8, "Cloning repository")
        root = ingest.clone(url)
        step(15, "Reading files")
        files = ingest.load_files(root)
        if not files:
            raise ValueError("No readable files found")

        step(20, "Static analysis (routes, imports, stack)")
        a = analyze_repo(files)
        chunks = chunk_files(files)
        if not chunks:
            raise ValueError("No supported source files found (Python, JS/TS, Java, Go, ...)")

        step(25, f"Embedding {len(chunks)} code chunks")
        ridx = index.build(chunks, key, job_id)

        step(40, "Writing project overview")
        ov = generate.overview(a, job_id)

        step(45, "Summarizing components")
        summaries = generate.summarize_components(
            a, ridx, job_id, progress=lambda i, n: step(45 + int(20 * i / n), f"Summarizing components ({i}/{n})"))
        if not summaries:
            raise ValueError("Could not identify any components")

        step(68, "Building architecture")
        arch = generate.architecture(a, ov, summaries, job_id)
        mermaid = generate.to_mermaid(arch)

        step(75, "Describing REST endpoints")
        endpoints = generate.describe_endpoints(a["routes"], job_id)

        step(88, "Generating interview Q&A")
        qa = generate.interview_qa(a, ridx, ov, arch, job_id)

        report = {"repo_url": url, "commit_sha": sha, "overview": ov, "languages": a["languages"],
                  "stack": a["stack"], "architecture": arch, "mermaid": mermaid,
                  "endpoints": endpoints, "qa": qa,
                  "stats": {"files": a["file_count"], "chunks": len(chunks), "routes": len(a["routes"])}}
        db.save_report(key, url, sha, report)
        db.update_job(job_id, status="done", progress=100, message="Done")
    except Exception as e:
        traceback.print_exc()
        db.update_job(job_id, status="failed", error=str(e)[:500], message="Failed")
    finally:
        if root:
            shutil.rmtree(root, ignore_errors=True)
