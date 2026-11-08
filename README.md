# Repo2Design: GitHub repo to system design generator

Paste a public GitHub URL and get an architecture overview, a component diagram (Mermaid), a REST API map, and system-design interview Q&A. Runs entirely in the cloud via fast, free serverless APIs.

```
Browser -> FastAPI (Render Web Service) -> background job
|- git clone (shallow, github.com only)
|- static analysis (routes, import graph, stack)
|- chunk -> Gemini API Embeddings (Zero RAM) -> FAISS
|- staged LLM generation via Groq (GPT-OSS / Llama 3)
'- report + latency logs -> SQL (SQLite / PostgreSQL)
```

## UI highlights

- Layered **architecture flow** (Clients > Interface & API > Business logic > Data) with colored tiles, icons, and directional arrows; thicker arrows indicate more imports.
- **Click any tile** for its responsibility, files, key classes/functions, exposed endpoints, who calls it, and what it calls (all linked directly back to GitHub).
- Responsive navigation: sidebar on desktop, bottom bar on phones; the structural layout stacks vertically on narrow mobile viewports.
- Searchable API map, Q&A accordion interface, repo chat assistant, dark mode toggles, recent analyses tracking, and native export options to Markdown/JSON/PDF.

## 1. Prerequisites

- Python 3.10+, Git
- Free [Groq Cloud Account Key](https://groq.com) (For high-speed serverless text generation inference)
- Free [Google AI Studio Key](https://google.com) (For zero-RAM tokenized text embeddings)

## 2. Run locally (With Cloud API fallbacks)

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Set up your environment variables locally
export GROQ_API_KEY="your_gsk_key"
export GEMINI_API_KEY="your_aiza_key"

uvicorn app.main:app --reload
# open http://localhost:8000   (API docs: /docs)
```

Without the web UI interface, execute directly through the terminal:

```bash
python -m app.cli https://github.com
```

*Note: Start with a small repository (under 50 files). A full architectural analysis takes less than a minute utilizing high-speed cloud completion layers.*

## 3. API Endpoints Reference

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/analyze` | `POST` | Start an analysis job, returns `job_id` |
| `/api/jobs/{id}` | `GET` | Track processing status, progress, and logs |
| `/api/report/{id}` | `GET` | Retrieve generated architecture overview, mermaid data, and structural Q&A |
| `/api/ask` | `POST` | RAG chat workspace session with file:line citations |
| `/api/stats` | `GET` | View average/maximum latency per parsing stage from SQL logs |
| `/api/health` | `GET` | Server health diagnostics check |

## 4. Tests and Evaluation

Run standard unit tests and verify route parser coverage parameters with these commands:

```bash
python -m pytest -q                                  # run unit tests
cp eval/ground_truth.example.json eval/ground_truth.json   # fill with real repos + their true routes
python -m eval.eval_routes eval/ground_truth.json    # prints precision / recall statistics
```

## 5. Free Cloud Deployment Guide (Render Native Python)

This application is fully optimized to run within Render's **Free Web Service Tier** (which imposes a strict 512MB RAM limitation) by shifting heavy machine learning computations to serverless external cloud endpoints.

### Step-by-Step Settings on Render Dashboard:

1. **Language:** Select `Python` (Do **NOT** choose Docker, as Docker containers incur higher memory overheads).
2. **Build Command:** 
   ```bash
   pip install -r requirements.txt
   ```
3. **Start Command:** 
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port $PORT
   ```
4. **Environment Variables (Configure under the Advanced Section):**
   - `GROQ_API_KEY`: Your secret Groq validation token (`gsk_...`)
   - `GEMINI_API_KEY`: Your secret Gemini AI Studio token (`AIzaSy...`)

## 6. Pipeline Limitations

- Public GitHub repositories only; maximum limits capped at 500 files, 200 KB size per file, and 300 document chunks.
- Route extraction covers FastAPI, Flask, Express, and Spring Framework styles (regex pattern based; dynamic router prefixes are not resolved).
- Throttled pacing loop delay (1.0 second pause) included inside embedding pipelines to respect Google Gemini free tier 30,000 token-per-minute allocation caps.
- Supports handling one background analysis job processing pipeline concurrently.