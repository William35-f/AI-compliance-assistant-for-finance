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
    # Defaults below are the winners of the Phase 4 experiments (README "Experiments"):
    # the "heading" index (document title + section heading embedded with each chunk)
    # searched in hybrid mode (vector + BM25 merged with reciprocal rank fusion).
    default_index: str = "heading"
    retrieval_mode: str = "hybrid"  # vector | fts | hybrid (see regulens/retrieval.py)
    retrieval_k: int = 5
    # The cross-encoder reranker did NOT help on top of heading + hybrid and costs ~1.3 s per query.
    rerank: bool = False
    reranker_model: str = "jinaai/jina-reranker-v1-turbo-en"
    # Refuse without calling the LLM when the best chunk's cosine similarity is below this.
    # Calibrated on the eval set: lowest in-scope score 0.656 (paraphrased) / 0.706; clearly
    # unrelated questions score 0.52-0.58. Near-domain questions (e.g. EU AI Act, 0.737) can't
    # be separated by similarity; the LLM's "answerable: false" handles those.
    min_retrieval_score: float = 0.60

    # --- LLM: Google Gemini ---
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-2.5-flash-lite"  # answers questions
    gemini_judge_model: str = "gemini-2.5-flash-lite"  # grades answers in evals
    # Client-side pacing. Free-tier limits are per model and change often;
    # check yours at https://aistudio.google.com and keep this at or below it.
    gemini_requests_per_minute: float = 10
    # Gemini 3 models accept "minimal" | "low" | "medium" | "high"; None = model default.
    gemini_thinking_level: str | None = None
    # Paid-tier list prices (USD per 1M tokens) used to ESTIMATE cost per query.
    # On the free tier the real cost is $0.
    price_input_per_mtok: float = 0.10
    price_output_per_mtok: float = 0.40


@lru_cache
def get_settings() -> Settings:
    """Return one shared Settings object (read .env only once)."""
    return Settings()
