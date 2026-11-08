"""Thin LLM wrapper: dynamically switches between Cloud (Groq + Gemini API) and Local (Ollama)."""
import time
import os
import json
import numpy as np

from . import config, db

# Lazy-initialize clients to prevent crashes based on environment settings
if config.IS_CLOUD:
    from groq import Groq
    from google import genai
    
    ollama_client = None
    groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    # Uses lightweight cloud clients instead of local RAM
    gemini_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
else:
    import ollama
    ollama_client = ollama.Client(host=config.OLLAMA_HOST, timeout=config.LLM_TIMEOUT)
    groq_client = None
    gemini_client = None

SYSTEM = ("You are a senior software architect. Use ONLY the provided facts and code. "
          "If something is not shown, say 'unknown'. Be concise and concrete.")


def ask(prompt, schema=None, system=SYSTEM, stage="generic", job_id=None, retries=1):
    last = None
    for _ in range(retries + 1):
        t = time.time()
        try:
            if config.IS_CLOUD:
                kwargs = {}
                current_system = system
                if schema:
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
                kwargs = {"format": schema.model_json_schema()} if schema else {}
                r = ollama_client.chat(model=config.LLM_MODEL,
                                messages=[{"role": "system", "content": system},
                                          {"role": "user", "content": prompt}],
                                options={"temperature": 0.2, "num_ctx": 8192}, **kwargs)
                text = r["message"]["content"]

            result = schema.model_validate_json(text) if schema else text.strip()
            db.log("llm", stage, (time.time() - t) * 1000, model=config.LLM_MODEL, job_id=job_id)
            return result
        except Exception as e:
            last = e
            db.log("llm", stage, (time.time() - t) * 1000, model=config.LLM_MODEL, job_id=job_id, error=e)
    raise RuntimeError(f"LLM call failed at stage '{stage}': {last}")


def embed(texts, kind="document", stage="embed", job_id=None, batch=16):
    prefix = "search_document: " if kind == "document" else "search_query: "
    t, vecs = time.time(), []
    try:
        if config.IS_CLOUD:
            # --- Cloud Path (Google Gemini Cloud API - Optimized to bypass 429 Quota Rate Limits) ---
            for idx, x in enumerate(texts):
                # Rate limit pacing: pause briefly after every chunk to prevent exceeding 30k tokens/min
                if idx > 0:
                    time.sleep(1.0)
                    
                response = gemini_client.models.embed_content(
                    model="gemini-embedding-001",
                    contents=prefix + x[:2000]
                )
                vecs.append(response.embeddings[0].values)

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
