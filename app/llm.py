"""Thin LLM wrapper: dynamically switches between Cloud (Groq + HF) and Local (Ollama)."""
import time
import os
import json
import numpy as np
from . import config, db
from groq import Groq
from langchain_huggingface import HuggingFaceEmbeddings
import ollama

# Lazy-initialize clients to prevent import crashing based on environment settings
if config.IS_CLOUD:
    ollama_client = None
    groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    # Automatically downloads the small, free embedding model into memory on Render startup
    hf_client = HuggingFaceEmbeddings(model_name=config.EMBED_MODEL)
else:
    ollama_client = ollama.Client(host=config.OLLAMA_HOST, timeout=config.LLM_TIMEOUT)
    groq_client = None
    hf_client = None

SYSTEM = ("You are a senior software architect. Use ONLY the provided facts and code. "
          "If something is not shown, say 'unknown'. Be concise and concrete.")


def ask(prompt, schema=None, system=SYSTEM, stage="generic", job_id=None, retries=1):
    last = None
    for _ in range(retries + 1):
        t = time.time()
        try:
            if config.IS_CLOUD:
                # --- Cloud Path (Groq) ---
                kwargs = {}
                current_system = system
                if schema:
                    # Instruct Groq to generate in structured JSON Mode
                    kwargs["response_format"] = {"type": "json_object"}
                    current_system += f"\nYou MUST respond with a valid JSON object strictly matching this schema: {json.dumps(schema.model_json_schema())}"

                r = groq_client.chat.completions.create(
                    model=config.LLM_MODEL,
                    messages=[
                        {"role": "system", "content": current_system},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.2,
                    **kwargs
                )
                text = r.choices[0].message.content
            else:
                # --- Local Path (Ollama) ---
                kwargs = {"format": schema.model_json_schema()} if schema else {}
                r = ollama_client.chat(model=config.LLM_MODEL,
                                messages=[{"role": "system", "content": system},
                                          {"role": "user", "content": prompt}],
                                options={"temperature": 0.2, "num_ctx": 8192}, **kwargs)
                text = r["message"]["content"]

            # Universal output validator (Works identically for Ollama and Groq strings/JSON)
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
        if config.IS_CLOUD:
            # --- Cloud Path (HuggingFace In-Memory) ---
            prepared_texts = [prefix + x[:2000] for x in texts]
            vecs = hf_client.embed_documents(prepared_texts)
        else:
            # --- Local Path (Ollama) ---
            for i in range(0, len(texts), batch):
                part = [prefix + x[:2000] for x in texts[i:i + batch]]
                vecs += ollama_client.embed(model=config.EMBED_MODEL, input=part)["embeddings"]
    except Exception as e:
        db.log("embed", stage, (time.time() - t) * 1000, model=config.EMBED_MODEL, job_id=job_id, error=e)
        raise RuntimeError(f"Embedding failed: {e}")
        
    db.log("embed", stage, (time.time() - t) * 1000, model=config.EMBED_MODEL, job_id=job_id)
    v = np.array(vecs, dtype="float32")
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    return v / np.where(norms == 0, 1, norms)
