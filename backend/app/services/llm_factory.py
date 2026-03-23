"""Shared ChatOpenAI factory: timeout, retries, optional model override."""
import os
from typing import Optional

from langchain_openai import ChatOpenAI

from app.core.settings import settings


def get_chat_openai(
    *,
    temperature: float = 0.3,
    model: Optional[str] = None,
) -> ChatOpenAI:
    """
    Create ChatOpenAI for DashScope compatible endpoint.
    Uses LLM_TIMEOUT_SECONDS / LLM_MAX_RETRIES from settings when set.
    """
    api_key = settings.DASHSCOPE_API_KEY or os.getenv("DASHSCOPE_API_KEY", "")
    m = (model or "").strip() or settings.LLM_MODEL
    kw: dict = {
        "model": m,
        "api_key": api_key,
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "temperature": temperature,
    }
    if settings.LLM_TIMEOUT_SECONDS and settings.LLM_TIMEOUT_SECONDS > 0:
        kw["timeout"] = settings.LLM_TIMEOUT_SECONDS
    if settings.LLM_MAX_RETRIES is not None and settings.LLM_MAX_RETRIES >= 0:
        kw["max_retries"] = settings.LLM_MAX_RETRIES
    return ChatOpenAI(**kw)


def get_merge_chat_openai(*, temperature: float = 0.3) -> ChatOpenAI:
    """LLM for scheduler final merge; uses LLM_MERGE_MODEL when non-empty."""
    merge_model = (settings.LLM_MERGE_MODEL or "").strip()
    return get_chat_openai(temperature=temperature, model=merge_model or None)
