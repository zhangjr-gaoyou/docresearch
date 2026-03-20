"""Prompt version store: file-based persistence for prompt templates."""
import json
import uuid
from datetime import datetime
from typing import List, Optional

from app.core.settings import settings
from app.services.prompt_defaults import BUILTIN_PROMPTS, SLOT_META

STORE_PATH = settings.DATA_DIR / "prompts.json"


def _load_store() -> dict:
    if not STORE_PATH.exists():
        return {"prompts": []}
    with open(STORE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def ensure_prompts_initialized() -> None:
    """Seed prompts.json with built-in defaults if store is empty or missing."""
    if STORE_PATH.exists():
        data = _load_store()
        if data.get("prompts"):
            return
    now = datetime.now().isoformat()
    prompts = []
    for slot_key, content in BUILTIN_PROMPTS.items():
        meta = SLOT_META.get(slot_key, {})
        title = meta.get("name", slot_key)
        prompts.append({
            "id": str(uuid.uuid4()),
            "slot_key": slot_key,
            "title": title,
            "content": content,
            "published": True,
            "created_at": now,
            "updated_at": now,
        })
    _save_store({"prompts": prompts})


def _save_store(data: dict) -> None:
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def list_prompts(slot_key: Optional[str] = None) -> List[dict]:
    """List all prompts, optionally filtered by slot_key."""
    data = _load_store()
    items = data.get("prompts", [])
    if slot_key:
        items = [p for p in items if p.get("slot_key") == slot_key]
    return sorted(items, key=lambda p: (p.get("slot_key", ""), p.get("created_at", "")), reverse=True)


def get_prompt_by_id(prompt_id: str) -> Optional[dict]:
    """Get a single prompt by ID."""
    data = _load_store()
    for p in data.get("prompts", []):
        if p.get("id") == prompt_id:
            return p
    return None


def get_published_prompt(slot_key: str) -> Optional[dict]:
    """Get the published prompt for a slot. At most one per slot."""
    data = _load_store()
    for p in data.get("prompts", []):
        if p.get("slot_key") == slot_key and p.get("published"):
            return p
    return None


def create_prompt(slot_key: str, title: str, content: str) -> dict:
    """Create a new prompt (unpublished by default)."""
    data = _load_store()
    prompts = data.get("prompts", [])
    now = datetime.now().isoformat()
    prompt = {
        "id": str(uuid.uuid4()),
        "slot_key": slot_key,
        "title": title,
        "content": content,
        "published": False,
        "created_at": now,
        "updated_at": now,
    }
    prompts.append(prompt)
    data["prompts"] = prompts
    _save_store(data)
    return prompt


def update_prompt(prompt_id: str, title: Optional[str] = None, content: Optional[str] = None) -> Optional[dict]:
    """Update prompt title and/or content."""
    data = _load_store()
    for p in data.get("prompts", []):
        if p.get("id") == prompt_id:
            if title is not None:
                p["title"] = title
            if content is not None:
                p["content"] = content
            p["updated_at"] = datetime.now().isoformat()
            _save_store(data)
            return p
    return None


def delete_prompt(prompt_id: str) -> bool:
    """Delete a prompt by ID."""
    data = _load_store()
    prompts = data.get("prompts", [])
    new_prompts = [p for p in prompts if p.get("id") != prompt_id]
    if len(new_prompts) == len(prompts):
        return False
    data["prompts"] = new_prompts
    _save_store(data)
    return True


def publish_prompt(prompt_id: str) -> Optional[dict]:
    """Publish a prompt. Unpublishes all others in the same slot."""
    p = get_prompt_by_id(prompt_id)
    if not p:
        return None
    slot_key = p.get("slot_key")
    data = _load_store()
    for item in data.get("prompts", []):
        if item.get("slot_key") == slot_key:
            item["published"] = item.get("id") == prompt_id
    for item in data.get("prompts", []):
        if item.get("id") == prompt_id:
            item["published"] = True
            item["updated_at"] = datetime.now().isoformat()
    _save_store(data)
    return get_prompt_by_id(prompt_id)
