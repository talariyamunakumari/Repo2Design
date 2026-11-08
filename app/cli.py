"""Run the pipeline without the web server:  python -m app.cli https://github.com/owner/repo"""
import json
import sys

from . import db, pipeline

if __name__ == "__main__":
    db.init_db()
    jid = db.create_job(sys.argv[1])
    pipeline.run(jid)
    job = db.get_job(jid)
    print(job["status"], job["error"] or "")
    if job["status"] == "done":
        print(json.dumps(db.get_report(job["repo_key"]), indent=2)[:5000])
