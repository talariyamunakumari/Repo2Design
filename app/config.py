import os

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5-coder:7b")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
DATA_DIR = os.getenv("DATA_DIR", "data")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///" + os.path.join(DATA_DIR, "app.db"))

MAX_FILES = int(os.getenv("MAX_FILES", "500"))
MAX_FILE_KB = int(os.getenv("MAX_FILE_KB", "200"))
MAX_CHUNKS = int(os.getenv("MAX_CHUNKS", "300"))
CLONE_TIMEOUT = int(os.getenv("CLONE_TIMEOUT", "120"))
MAX_COMPONENTS = int(os.getenv("MAX_COMPONENTS", "8"))
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "600"))
