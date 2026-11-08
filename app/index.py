"""FAISS vector index over code chunks, cached on disk per repo+commit."""
import json
from pathlib import Path

import faiss

from . import config, llm


def index_dir(key: str) -> Path:
    return Path(config.DATA_DIR) / "indexes" / key


def exists(key: str) -> bool:
    return (index_dir(key) / "index.faiss").exists()


class RepoIndex:
    def __init__(self, idx, chunks):
        self.idx, self.chunks = idx, chunks

    def search(self, query, k=6, component=None):
        q = llm.embed([query], kind="query", stage="embed_query")
        fetch = self.idx.ntotal if component else min(k, self.idx.ntotal)
        _, ids = self.idx.search(q, fetch)
        out = []
        for i in ids[0]:
            if i < 0:
                continue
            c = self.chunks[i]
            if component and c["component"] != component:
                continue
            out.append(c)
            if len(out) >= k:
                break
        return out


def build(chunks, key, job_id=None) -> RepoIndex:
    vecs = llm.embed([f'{c["path"]}\n{c["text"]}' for c in chunks], stage="embed_chunks", job_id=job_id)
    idx = faiss.IndexFlatIP(vecs.shape[1])
    idx.add(vecs)
    d = index_dir(key)
    d.mkdir(parents=True, exist_ok=True)
    faiss.write_index(idx, str(d / "index.faiss"))
    (d / "chunks.json").write_text(json.dumps(chunks))
    return RepoIndex(idx, chunks)


_cache = {}


def load(key: str) -> RepoIndex:
    if key not in _cache:
        d = index_dir(key)
        _cache[key] = RepoIndex(faiss.read_index(str(d / "index.faiss")),
                                json.loads((d / "chunks.json").read_text()))
    return _cache[key]
