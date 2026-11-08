"""Thin Ollama wrapper: timing + SQL logging + one retry on bad JSON."""
import time

import numpy as np
import ollama

from . import config, db

client = ollama.Client(host=config.OLLAMA_HOST, timeout=config.LLM_TIMEOUT)
SYSTEM = ("You are a senior software architect. Use ONLY the provided facts and code. "
          "If something is not shown, say 'unknown'. Be concise and concrete.")


def ask(prompt, schema=None, system=SYSTEM, stage="generic", job_id=None, retries=1):
    last = None
    for _ in range(retries + 1):
        t = time.time()
        try:
            kwargs = {"format": schema.model_json_schema()} if schema else {}
            r = client.chat(model=config.LLM_MODEL,
                            messages=[{"role": "system", "content": system},
                                      {"role": "user", "content": prompt}],
                            options={"temperature": 0.2, "num_ctx": 8192}, **kwargs)
            text = r["message"]["content"]
            result = schema.model_validate_json(text) if schema else text.strip()
            db.log("llm", stage, (time.time() - t) * 1000, model=config.LLM_MODEL, job_id=job_id)
            return result
        except Exception as e:   # connection error, timeout, invalid JSON ...
            last = e
            db.log("llm", stage, (time.time() - t) * 1000, model=config.LLM_MODEL, job_id=job_id, error=e)
    raise RuntimeError(f"LLM call failed at stage '{stage}': {last}")


def embed(texts, kind="document", stage="embed", job_id=None, batch=16):
    prefix = "search_document: " if kind == "document" else "search_query: "
    t, vecs = time.time(), []
    try:
        for i in range(0, len(texts), batch):
            part = [prefix + x[:2000] for x in texts[i:i + batch]]
            vecs += client.embed(model=config.EMBED_MODEL, input=part)["embeddings"]
    except Exception as e:
        db.log("embed", stage, (time.time() - t) * 1000, model=config.EMBED_MODEL, job_id=job_id, error=e)
        raise RuntimeError(f"Embedding failed: {e}")
    db.log("embed", stage, (time.time() - t) * 1000, model=config.EMBED_MODEL, job_id=job_id)
    v = np.array(vecs, dtype="float32")
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    return v / np.where(norms == 0, 1, norms)
