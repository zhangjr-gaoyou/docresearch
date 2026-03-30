"""Application settings and configuration."""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Project paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    DATA_DIR: Path = BASE_DIR.parent / "data"
    UPLOADS_DIR: Path = DATA_DIR / "uploads"
    INDEX_DIR: Path = DATA_DIR / "faiss_index"
    RESEARCH_OUTPUT_DIR: Path = DATA_DIR / "research_output"

    # Alibaba Bailian (DashScope)
    DASHSCOPE_API_KEY: str = ""
    EMBEDDING_MODEL: str = "text-embedding-v3"
    EMBEDDING_DIMENSIONS: int = 1024
    RERANK_MODEL: str = "qwen3-rerank"
    LLM_MODEL: str = "qwen-plus"
    # HTTP client: long merges need a generous timeout (seconds). 0 = LangChain default.
    LLM_TIMEOUT_SECONDS: float = 600.0
    LLM_MAX_RETRIES: int = 2
    # Max completion tokens for chat completions; 0 = omit (API default). Raise for long tables / map_merge.
    LLM_MAX_OUTPUT_TOKENS: int = 8192
    # Optional: dedicated model for research final merge (empty = LLM_MODEL)
    LLM_MERGE_MODEL: str = ""
    # Keep key-path deterministic: route and final merge default to temperature 0.
    ROUTE_TEMPERATURE: float = 0.0
    FINAL_MERGE_TEMPERATURE: float = 0.0
    # Merge strategy: pairwise | single | direct_join | auto
    MERGE_STRATEGY: str = "pairwise"
    # When full merge_final prompt exceeds this (chars), use pairwise merge rounds.
    MERGE_MAX_SINGLE_PROMPT_CHARS: int = 45000
    # Max chars per document body in one pairwise merge call (each side truncated if needed).
    MERGE_PAIR_MAX_CHARS_EACH: int = 22000
    # If estimated tokens for merge_final prompt exceed this, skip LLM and concatenate doc outputs.
    MERGE_SKIP_LLM_OVER_ESTIMATED_TOKENS: int = 10000
    # Heuristic: estimated_token_count ≈ len(merge_prompt) / MERGE_ESTIMATED_CHARS_PER_TOKEN (zh-heavy ~2).
    MERGE_ESTIMATED_CHARS_PER_TOKEN: float = 2.0
    # Step output validation/retry.
    STEP_OUTPUT_VALIDATE_RETRIES: int = 1
    # Step main prompt length threshold to switch to map-reduce.
    STEP_MAIN_PROMPT_MAX_CHARS: int = 12000
    # map_merge: tree-merge partials when merge prompt would exceed this (chars, heuristic).
    STEP_MAP_MERGE_MAX_PROMPT_CHARS: int = 22000
    # Truncate each side before pairwise map_merge when merging two large partial blobs.
    STEP_MAP_MERGE_PAIR_MAX_CHARS_EACH: int = 14000
    # Safety cap on recursive map_merge depth (log-style reduce).
    STEP_MAP_MERGE_MAX_DEPTH: int = 8

    # Chunking
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 50

    # API
    API_V1_PREFIX: str = "/api/v1"
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        self.INDEX_DIR.mkdir(parents=True, exist_ok=True)
        self.RESEARCH_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()
