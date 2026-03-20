"""Prompt registry: resolve published prompt or built-in default per slot."""
import logging
from typing import Any

from app.services.prompt_defaults import BUILTIN_PROMPTS, SLOT_META
from app.services.prompt_store import get_published_prompt

logger = logging.getLogger(__name__)


def get_prompt(slot_key: str, **kwargs: Any) -> str:
    """
    Get prompt content for a slot. Uses published version if available, else built-in.
    Formats with kwargs. On format error, falls back to built-in.
    """
    default = BUILTIN_PROMPTS.get(slot_key, "")
    published = get_published_prompt(slot_key)
    template = (published.get("content") if published else default) or default

    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, ValueError) as e:
            logger.warning("Prompt format failed for %s: %s, using built-in", slot_key, e)
            try:
                return default.format(**kwargs)
            except Exception:
                return default
    return template
