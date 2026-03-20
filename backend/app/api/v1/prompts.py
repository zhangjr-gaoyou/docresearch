"""Prompts API: CRUD and publish for prompt templates."""
from fastapi import APIRouter, HTTPException

from app.models.schemas import (
    PromptCreateRequest,
    PromptUpdateRequest,
    PromptResponse,
    SlotMetaResponse,
)
from app.services.prompt_store import (
    ensure_prompts_initialized,
    list_prompts,
    get_prompt_by_id,
    create_prompt,
    update_prompt,
    delete_prompt,
    publish_prompt,
)
from app.services.prompt_defaults import SLOT_META

router = APIRouter()


@router.get("/slots", response_model=list[SlotMetaResponse])
def list_slots():
    """List all prompt slots with metadata."""
    ensure_prompts_initialized()
    return [
        SlotMetaResponse(slot_key=k, name=v["name"], placeholders=v.get("placeholders", []))
        for k, v in SLOT_META.items()
    ]


@router.get("", response_model=list[PromptResponse])
def list_prompts_endpoint(slot_key: str | None = None):
    """List prompts, optionally filtered by slot_key."""
    ensure_prompts_initialized()
    items = list_prompts(slot_key=slot_key)
    return [PromptResponse(**p) for p in items]


@router.post("", response_model=PromptResponse)
def create_prompt_endpoint(body: PromptCreateRequest):
    """Create a new prompt (unpublished)."""
    ensure_prompts_initialized()
    if body.slot_key not in SLOT_META:
        raise HTTPException(status_code=400, detail=f"Unknown slot_key: {body.slot_key}")
    prompt = create_prompt(body.slot_key, body.title, body.content)
    return PromptResponse(**prompt)


@router.get("/{prompt_id}", response_model=PromptResponse)
def get_prompt_endpoint(prompt_id: str):
    """Get a prompt by ID."""
    prompt = get_prompt_by_id(prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return PromptResponse(**prompt)


@router.put("/{prompt_id}", response_model=PromptResponse)
def update_prompt_endpoint(prompt_id: str, body: PromptUpdateRequest):
    """Update prompt title and/or content."""
    prompt = update_prompt(prompt_id, title=body.title, content=body.content)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return PromptResponse(**prompt)


@router.delete("/{prompt_id}")
def delete_prompt_endpoint(prompt_id: str):
    """Delete a prompt."""
    if not delete_prompt(prompt_id):
        raise HTTPException(status_code=404, detail="Prompt not found")
    return {"ok": True}


@router.post("/{prompt_id}:publish", response_model=PromptResponse)
def publish_prompt_endpoint(prompt_id: str):
    """Publish a prompt (unpublishes others in same slot)."""
    prompt = publish_prompt(prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return PromptResponse(**prompt)
