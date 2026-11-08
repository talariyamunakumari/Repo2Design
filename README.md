# Repo2Design: GitHub repo to system design generator

Paste a public GitHub URL and get an architecture overview, a component diagram (Mermaid),
a REST API map, and system-design interview Q&A. Runs fully locally with **Ollama**.

**Design idea:** facts (file tree, imports, routes, stack) are extracted with plain code;
the LLM only explains them. This keeps small local models from hallucinating the structure.

```
Browser -> FastAPI -> background job
                        |- git clone (shallow, github.com only)
                        |- static analysis (routes, import graph, stack)
                        |- chunk -> Ollama embeddings -> FAISS
                        |- staged LLM generation (overview, components, architecture, endpoints, Q&A)
                        '- report + latency logs -> SQL (SQLite / PostgreSQL)
```

## UI highlights
- Layered **architecture flow** (Clients > Interface & API > Business logic > Data) with colored tiles, icons and directional arrows; thicker arrows mean more imports.
- **Click any tile** for its responsibility, files, key classes/functions, exposed endpoints, who calls it and what it calls (all linked to GitHub at the analyzed commit).
- Responsive navigation: sidebar on desktop, bottom bar on phones; the flow stacks vertically on narrow screens.
- Searchable API map, Q&A accordion, repo chat, dark mode, recent analyses, export to Markdown/JSON/PDF.

## 1. Prerequisites
- Python 3.10+, Git
- [Ollama](https://ollama.com/download)
- 8 GB RAM for the 7B model (use `qwen2.5-coder:3b` if you have less)

## 2. Run locally
```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

ollama pull qwen2.5-coder:7b      # or :3b
ollama pull nomic-embed-text

uvicorn app.main:app --reload
# open http://localhost:8000   (API docs: /docs)
```
Use a smaller model: `LLM_MODEL=qwen2.5-coder:3b uvicorn app.main:app` (Windows PowerShell: `$env:LLM_MODEL="qwen2.5-coder:3b"`).

Without the web UI: `python -m app.cli https://github.com/owner/repo`

Start with a **small repo** (under 50 files). A full analysis takes 3-15 minutes on CPU.

## 3. API
| Endpoint | Purpose |
|---|---|
| `POST /api/analyze` `{repo_url}` | start a job, returns `job_id` |
| `GET /api/jobs/{id}` | status, progress, message |
| `GET /api/report/{id}` | architecture, mermaid, endpoints, Q&A |
| `POST /api/ask` `{job_id, question}` | RAG chat with file:line citations |
| `GET /api/stats` | avg/max latency per stage from SQL logs |
| `GET /api/health` | health check |

## 4. Tests and evaluation
```bash
python -m pytest -q                                  # unit tests
cp eval/ground_truth.example.json eval/ground_truth.json   # fill with 5 real repos + their routes
python -m eval.eval_routes eval/ground_truth.json    # prints precision / recall
```
Put the precision/recall numbers in this README and on your resume.

## 5. Docker (API + Ollama + PostgreSQL)
```bash
docker compose up --build -d
docker compose logs -f ollama-init     # wait until both models are pulled
# open http://localhost:8000
```

## 6. Deploy (needs a server with 8 GB+ RAM)
Free hosts like Render/Vercel cannot run Ollama. Use an Oracle Cloud Always Free ARM VM or any VPS:
```bash
sudo apt update && sudo apt install -y docker.io docker-compose-plugin git
git clone <your-repo> && cd repo2design
sudo docker compose up -d --build
```
Then put Caddy in front for HTTPS:
```
# /etc/caddy/Caddyfile
yourdomain.com {
    reverse_proxy localhost:8000
}
```
Quick demo alternative: run locally and `cloudflared tunnel --url http://localhost:8000`.

## 7. Limitations
- Public GitHub repos only; max 500 files, 200 KB per file, 300 chunks.
- Route extraction covers FastAPI, Flask, Express, Spring (regex based; router prefixes are not resolved).
- Small local models can still produce weak summaries; routes, imports and stack are verified facts.
- One analysis at a time (local LLM is the bottleneck).
