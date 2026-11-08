# Repo2Design: GitHub repo to system design generator

Paste a public GitHub URL and get an architecture overview, a component diagram (Mermaid),
a REST API map, and system-design interview Q&A. 

This project features an intelligent **Dual-Mode Architecture**: it runs 100% locally and completely offline on your computer, but automatically switches to high-speed, zero-RAM free cloud infrastructure when deployed to platforms like Render.

---

## 🔁 Smart Environment Switching (How it works)

The application automatically changes its behavior based on where it is running:

| Component | Running Locally (Your PC) | Running Online (Render Cloud) |
| :--- | :--- | :--- |
| **Detection Trigger** | Runs offline (No `GROQ_API_KEY` set) | Automatically triggered by `GROQ_API_KEY` env var |
| **Text Generation (LLM)** | **Ollama** (`qwen2.5-coder:7b`) | **Groq Cloud API** (`openai/gpt-oss-20b`) |
| **Embeddings Model** | **Ollama** (`nomic-embed-text`) | **Google Gemini API** (`gemini-embedding-001`) |
| **Server RAM Footprint**| Requires 8GB+ RAM to load weights | ~120MB (Safely under Render's 512MB free cap) |
| **Network Cost** | 100% Offline / Private | Serverless Free Tier APIs |

---

## UI Highlights
- Layered **architecture flow** (Clients > Interface & API > Business logic > Data) with colored tiles, icons, and directional arrows; thicker arrows indicate more imports.
- **Click any tile** for its responsibility, files, key classes/functions, exposed endpoints, who calls it, and what it calls (all linked directly back to GitHub).
- Responsive navigation: sidebar on desktop, bottom bar on phones; the structural layout stacks vertically on narrow mobile viewports.
- Searchable API map, Q&A accordion interface, repo chat assistant, dark mode toggles, recent analyses tracking, and native export options to Markdown/JSON/PDF.

---

## 1. Local Prerequisites (Offline Mode)
- Python 3.10+, Git
- [Ollama App Installed](https://ollama.com)
- 8 GB RAM minimum to run the 7B parameter model locally

## 2. Running Locally (100% Offline)
Make sure your background Ollama app is open and running on your computer, then execute the following commands in your terminal:

```bash
# 1. Download the offline models onto your computer
ollama pull qwen2.5-coder:7b
ollama pull nomic-embed-text

# 2. Set up your Python virtual environment
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 3. Boot up the local web app
uvicorn app.main:app --reload
# Open http://localhost:8000   (API documentation available at /docs)
```

Without the web UI, you can execute directly through your local CLI:
```bash
python -m app.cli https://github.com
```

---

## 3. Free Cloud Deployment Guide (Render Python Native)
This codebase is completely optimized to run within Render's **Free Web Service Tier** (which imposes a strict 512MB RAM limitation) by dynamically shifting heavy machine learning computations to serverless external cloud endpoints.

### Step-by-Step Settings on Render Dashboard:
1. **Language:** Select `Python` (Do **NOT** choose Docker, as Docker containers incur higher memory overheads).
2. **Build Command:** 
   ```bash
   pip install -r requirements.txt
   ```
3. **Start Command:** 
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port \$PORT
   ```
4. **Environment Variables (Configure under the Advanced Section):**
   - `GROQ_API_KEY`: Your secret Groq validation token (`gsk_...`)
   - `GEMINI_API_KEY`: Your secret Gemini AI Studio token (`AIzaSy...`)
   - `GEMINI_API_KEY_BACKUP`: *(Optional)* A second free Gemini key. The pipeline includes automatic API key rotation to seamlessly bypass daily 429 free tier limits if your main key runs out of daily requests!

---

## 4. API Endpoints Reference

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/analyze` | `POST` | Start an analysis job, returns `job_id` |
| `/api/jobs/{id}` | `GET` | Track processing status, progress, and logs |
| `/api/report/{id}` | `GET` | Retrieve generated architecture overview, mermaid data, and structural Q&A |
| `/api/ask` | `POST` | RAG chat workspace session with file:line citations |
| `/api/stats` | `GET` | View average/maximum latency per parsing stage from SQL logs |
| `/api/health` | `GET` | Server health diagnostics check |

---

## 5. Pipeline Limitations
- Public GitHub repositories only; maximum limits capped at 500 files, 200 KB size per file, and 300 document chunks.
- Route extraction covers FastAPI, Flask, Express, and Spring Framework styles (regex pattern based; dynamic router prefixes are not resolved).
- Throttled pacing loop delay (2.0 second batch interval pause) included inside cloud embedding pipelines to safely respect Google Gemini free tier allocation caps.
- Supports handling one background analysis job processing pipeline concurrently.
