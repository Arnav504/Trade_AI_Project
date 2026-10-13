"""
Configuration for ASAN Macro. Loads from environment (.env or Colab).
"""
import os
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "trade.db"
GALLERY_PATH = PROJECT_ROOT / "gallery" / "index.json"

# HTTPS hosts operators may pass to --data-url. Override with DATA_URL_ALLOWLIST.
DEFAULT_DATA_URL_HOSTS = ("raw.githubusercontent.com", "comtradeplus.un.org")


def get_db_path() -> Path:
    """SQLite path. ASAN_DB_PATH overrides the default so tests stay off the dev database."""
    override = os.environ.get("ASAN_DB_PATH", "").strip()
    if override:
        return Path(override)
    return DB_PATH


def get_data_url_allowlist() -> set:
    """Hosts allowed for operator CSV/JSON ingest. IP addresses are never allowed."""
    raw = os.environ.get("DATA_URL_ALLOWLIST", "").strip()
    if not raw:
        return {host.lower() for host in DEFAULT_DATA_URL_HOSTS}
    return {host.strip().lower() for host in raw.split(",") if host.strip()}

def get_openai_api_key():
    # Load .env first so we always use the file (override any stale env)
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(str(env_path), override=True)
        except Exception:
            pass
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    return key or None


def get_gemini_api_key():
    """Use Gemini (free tier) when OpenAI quota is exceeded. Get key at https://aistudio.google.com/apikey"""
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(str(env_path), override=True)
        except Exception:
            pass
    return os.environ.get("GEMINI_API_KEY", "").strip() or None


def use_local_ollama():
    """Use local Ollama (open-source model) when set. No API key or quota."""
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(str(env_path), override=True)
        except Exception:
            pass
    return os.environ.get("USE_LOCAL_LLM", "").strip().lower() in ("1", "true", "yes") or bool(os.environ.get("OLLAMA_MODEL", "").strip())


def get_ollama_base_url():
    return os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1").strip() or "http://localhost:11434/v1"


def get_ollama_model():
    return os.environ.get("OLLAMA_MODEL", "llama3.2").strip() or "llama3.2"


def get_openai_model():
    """Model for OpenAI API (e.g. gpt-4o-mini, gpt-4o). Set OPENAI_MODEL in .env for better quality."""
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(str(env_path), override=True)
        except Exception:
            pass
    return os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"


def get_gemini_model():
    """Model for Gemini API (e.g. gemini-2.0-flash, gemini-1.5-pro). Set GEMINI_MODEL in .env."""
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(str(env_path), override=True)
        except Exception:
            pass
    return os.environ.get("GEMINI_MODEL", "gemini-2.0-flash").strip() or "gemini-2.0-flash"
