"""Embedding service using Alibaba Bailian text-embedding-v3."""
import os
from typing import List

from openai import OpenAI
from app.core.settings import settings


def get_embedding_client() -> OpenAI:
    """Create OpenAI-compatible client for DashScope."""
    api_key = settings.DASHSCOPE_API_KEY or os.getenv("DASHSCOPE_API_KEY", "")
    return OpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )


# 百炼 API 单次请求最多 10 条
BATCH_SIZE = 10


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Embed a list of texts using text-embedding-v3 (batched, max 10 per request)."""
    if not texts:
        return []

    client = get_embedding_client()
    all_embeddings = []

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        response = client.embeddings.create(
            model=settings.EMBEDDING_MODEL,
            input=batch,
            dimensions=settings.EMBEDDING_DIMENSIONS,
            encoding_format="float",
        )
        all_embeddings.extend([item.embedding for item in response.data])

    return all_embeddings
