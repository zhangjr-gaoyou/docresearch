"""Rerank service using Alibaba Bailian qwen3-rerank."""
import os
from typing import List, Optional

import dashscope
from dashscope import TextReRank
from http import HTTPStatus

from app.core.settings import settings
from app.services.prompt_registry import get_prompt


def init_dashscope():
    """Initialize DashScope API key."""
    api_key = settings.DASHSCOPE_API_KEY or os.getenv("DASHSCOPE_API_KEY", "")
    dashscope.api_key = api_key


def rerank_documents(
    query: str,
    documents: List[str],
    top_n: Optional[int] = None,
) -> List[tuple[str, float, int]]:
    """
    Rerank documents by relevance to query.
    Returns list of (content, score, original_index).
    """
    if not documents:
        return []

    init_dashscope()
    top_n = top_n or len(documents)

    instruct = get_prompt("search.rerank_instruct")
    resp = TextReRank.call(
        model=settings.RERANK_MODEL,
        query=query,
        documents=documents,
        top_n=min(top_n, len(documents)),
        return_documents=True,
        instruct=instruct,
    )

    if resp.status_code != HTTPStatus.OK:
        raise RuntimeError(f"Rerank API error: {resp.message or resp.code}")

    results = []
    for item in resp.output.get("results", []):
        doc = item.get("document", {})
        text = doc.get("text", "")
        score = item.get("relevance_score", 0.0)
        idx = item.get("index", 0)
        results.append((text, score, idx))

    return results
