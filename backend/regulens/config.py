"""Application settings, loaded from environment variables and the repo-root .env file.

Every setting has a safe local-development default, except secrets (API keys),
which are never hard-coded.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/regulens/config.py -> parents[2] is the repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
SOURCES_CSV = DATA_DIR / "sources.csv"


class Settings(BaseSettings):
    # Real environment variables override values in .env (useful in CI and deployment).
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    database_url: str = "postgresql://regulens:regulens@localhost:5432/regulens"

    # --- Retrieval ---
    embedding_model: str = "nomic-ai/nomic-embed-text-v1.5-Q"
    # Downloaded models live here (git-ignored), not in a temp folder that may be wiped.
    model_cache_dir: Path = REPO_ROOT / ".cache" / "models"
    # Which chunk index the API searches (see regulens/index_configs.py).
    default_index: str = "baseline"

    # --- LLM (used from Phase 2) ---
    gemini_api_key: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    """Return one shared Settings object (read .env only once)."""
    return Settings()
