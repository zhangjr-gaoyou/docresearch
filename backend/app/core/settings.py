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
