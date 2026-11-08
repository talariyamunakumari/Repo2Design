"""
Thin LLM wrapper: dynamically switches between Cloud (Groq + Gemini API) and Local (Ollama).
Fully optimized with batching and automatic fallback key rotation to remain 100% free.
"""
import time
import os
import json
import numpy as np

from . import config, db

# Global variables for clients
ollama_client = None
groq_client = None
gemini_client = None

if config.IS_CLOUD:
    from groq import Groq
    from google import genai
    
    groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    gemini_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
else:
    import ollama
    ollama_client = ollama.Client(host=config.OLLAMA_HOST, timeout=config.LLM_TIMEOUT)

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


def embed(texts, kind="document", stage="embed", job_id=None, batch=32):
    global gemini_client  # Declared globally to prevent scoping runtime errors during rotation
    
    prefix = "search_document: " if kind == "document" else "search_query: "
    t, vecs = time.time(), []
    
    # Track available API tokens for automated rotation safety checks
    api_keys = [os.environ.get("GEMINI_API_KEY")]
    if os.environ.get("GEMINI_API_KEY_BACKUP"):
        api_keys.append(os.environ.get("GEMINI_API_KEY_BACKUP"))
        
    current_key_idx = 0

    if config.IS_CLOUD:
        # --- Cloud Path (Google Gemini Cloud API with Smart Batching + Key Rotation) ---
        i = 0
        while i < len(texts):
            # Pacing delay between batch calls to stay within free allocation bounds
            if i > 0:
                time.sleep(2.0)
                
            batch_texts = [prefix + x[:2000] for x in texts[i:i + batch]]
            
            try:
                response = gemini_client.models.embed_content(
                    model=config.EMBED_MODEL,
                    contents=batch_texts
                )
                # Success: extract vectors and increment our slice counter index
                for embedding in response.embeddings:
                    vecs.append(embedding.values)
                i += batch
                
            except Exception as e:
                # If a rate limit or daily limit hits, check if a backup key exists
                if "429" in str(e) and current_key_idx + 1 < len(api_keys):
                    current_key_idx += 1
                    print(f"Daily requests limit encountered. Rotating to backup API key index: {current_key_idx}")
                    from google import genai
                    gemini_client = genai.Client(api_key=api_keys[current_key_idx])
                    continue  # Repeat the exact same index loop slice using the new backup token
                else:
                    # Fail securely if no alternate keys remain or a non-429 error occurs
                    db.log("embed", stage, (time.time() - t) * 1000, model=config.EMBED_MODEL, job_id=job_id, error=e)
                    raise RuntimeError(f"Embedding failed: {e}")
    else:
        # --- Local Path (Ollama Fallback) ---
        for i in range(0, len(texts), batch):
            part = [prefix + x[:2000] for x in texts[i:i + batch]]
            vecs += ollama_client.embed(model=config.EMBED_MODEL, input=part)["embeddings"]
            
    db.log("embed", stage, (time.time() - t) * 1000, model=config.EMBED_MODEL, job_id=job_id)
    v = np.array(vecs, dtype="float32")
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    return v / np.where(norms == 0, 1, norms)
