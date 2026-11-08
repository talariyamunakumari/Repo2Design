import os

# Base Directories
DATA_DIR = os.getenv("DATA_DIR", "data")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///" + os.path.join(DATA_DIR, "app.db"))

# --- 100% FREE CLOUD FALLBACK OVERRIDES ---
# If GROQ_API_KEY is detected (like on Render), we use free high-speed cloud infrastructure.
# Otherwise, it falls back to your local Ollama instance for local development.
IS_CLOUD = "GROQ_API_KEY" in os.environ

if IS_CLOUD:
    OLLAMA_HOST = ""  # Not needed in the cloud
    LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile") # Free high-speed Llama 3 model on Groq
    EMBED_MODEL = os.getenv("EMBED_MODEL", "gemini-embedding-001") # Memory-efficient embedding model
else:
    OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5-coder:7b")
    EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

# Operational Parameters
MAX_FILES = int(os.getenv("MAX_FILES", "500"))
MAX_FILE_KB = int(os.getenv("MAX_FILE_KB", "200"))
MAX_CHUNKS = int(os.getenv("MAX_CHUNKS", "300"))
CLONE_TIMEOUT = int(os.getenv("CLONE_TIMEOUT", "120"))
MAX_COMPONENTS = int(os.getenv("MAX_COMPONENTS", "8"))
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "600"))
