"""Clone a public GitHub repo safely and list the files worth analysing."""
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import config

SKIP_DIRS = {".git", "node_modules", "dist", "build", "venv", ".venv", "__pycache__",
             ".idea", ".vscode", "target", "vendor", ".next", "coverage"}
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".lock", ".zip", ".tar",
            ".gz", ".pdf", ".woff", ".woff2", ".ttf", ".mp4", ".mp3", ".jar", ".class",
            ".pyc", ".so", ".dll", ".exe", ".map"}
URL_RE = re.compile(r"^https://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")
_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


def parse_repo_url(url: str):
    """Return (owner, repo, clean_url). Only github.com HTTPS URLs are allowed (SSRF guard)."""
    m = URL_RE.match(url.strip())
    if not m:
        raise ValueError("Only URLs like https://github.com/<owner>/<repo> are allowed")
    owner, repo = m.groups()
    return owner, repo, f"https://github.com/{owner}/{repo}"


def remote_head_sha(clean_url: str) -> str:
    out = subprocess.run(["git", "ls-remote", clean_url, "HEAD"], check=True, timeout=30,
                         capture_output=True, text=True, env=_ENV).stdout
    if not out.strip():
        raise ValueError("Repository not found, private, or empty")
    return out.split()[0]


def clone(clean_url: str) -> str:
    dest = tempfile.mkdtemp(prefix="repo_")
    try:
        subprocess.run(["git", "clone", "--depth", "1", "--no-tags", clean_url, dest],
                       check=True, timeout=config.CLONE_TIMEOUT,
                       capture_output=True, env=_ENV)
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return dest


def list_files(root: str):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in sorted(filenames):
            p = Path(dirpath) / name
            if p.is_symlink() or p.suffix.lower() in SKIP_EXT:
                continue
            try:
                if p.stat().st_size > config.MAX_FILE_KB * 1024:
                    continue
            except OSError:
                continue
            out.append(p)
            if len(out) >= config.MAX_FILES:
                return out
    return out


def read_text(p: Path):
    try:
        data = p.read_bytes()
    except OSError:
        return None
    if b"\0" in data:
        return None
    return data.decode("utf-8", errors="ignore")


def load_files(root: str):
    """Return [(relative_posix_path, text)] for every readable text file."""
    result = []
    for p in list_files(root):
        text = read_text(p)
        if text is not None:
            result.append((os.path.relpath(p, root).replace(os.sep, "/"), text))
    return result
