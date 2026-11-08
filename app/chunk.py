"""Split source files into retrievable chunks with path + line metadata."""
import ast
import math

from . import config
from .analyze import SOURCE_EXT, component_of, ext_of

MAX_CHARS = 2000


def chunk_windows(path, text, size=50, overlap=10):
    lines, out = text.splitlines(), []
    for s in range(0, len(lines), size - overlap):
        block = lines[s:s + size]
        if block:
            out.append({"path": path, "start": s + 1, "end": s + len(block),
                        "text": "\n".join(block)[:MAX_CHARS]})
    return out


def chunk_python(path, text):
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return chunk_windows(path, text)
    lines, out = text.splitlines(), []
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            s, e = n.lineno, n.end_lineno or n.lineno
            if e - s + 1 > 80:                      # big class: window it
                out += [{**c, "start": c["start"] + s - 1, "end": c["end"] + s - 1}
                        for c in chunk_windows(path, "\n".join(lines[s - 1:e]))]
            else:
                out.append({"path": path, "start": s, "end": e, "text": "\n".join(lines[s - 1:e])[:MAX_CHARS]})
    return out or chunk_windows(path, text)


def chunk_files(files):
    chunks = []
    for path, text in files:
        if ext_of(path) not in SOURCE_EXT or not text.strip():
            continue
        cs = chunk_python(path, text) if ext_of(path) == ".py" else chunk_windows(path, text)
        for c in cs:
            c["component"] = component_of(path)
        chunks += cs
    if len(chunks) > config.MAX_CHUNKS:               # even sampling keeps all components represented
        step = math.ceil(len(chunks) / config.MAX_CHUNKS)
        chunks = chunks[::step]
    return chunks
