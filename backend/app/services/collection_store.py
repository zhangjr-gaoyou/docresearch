"""Collection and document metadata store (file-based for MVP)."""
import json
import uuid
from pathlib import Path
from typing import List, Optional

from app.core.settings import settings


STORE_PATH = settings.DATA_DIR / "collections.json"


def _load_store() -> dict:
    if not STORE_PATH.exists():
        return {"collections": {}}
    with open(STORE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_store(data: dict):
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def create_collection(name: str) -> dict:
    """Create a new collection."""
    data = _load_store()
    cid = str(uuid.uuid4())
    data["collections"][cid] = {
        "id": cid,
        "name": name,
        "documents": [],
    }
    _save_store(data)
    return data["collections"][cid]


def list_collections() -> List[dict]:
    """List all collections."""
    data = _load_store()
    return list(data["collections"].values())


def get_collection(collection_id: str) -> Optional[dict]:
    """Get collection by ID."""
    data = _load_store()
    return data["collections"].get(collection_id)


def add_documents_to_collection(collection_id: str, documents: List[dict]) -> None:
    """Add document metadata to collection."""
    data = _load_store()
    if collection_id not in data["collections"]:
        raise ValueError(f"Collection {collection_id} not found")
    coll = data["collections"][collection_id]
    coll["documents"].extend(documents)
    _save_store(data)


def remove_document_from_collection(collection_id: str, document_id: str) -> Optional[dict]:
    """Remove one document from collection metadata. Returns removed entry or None."""
    data = _load_store()
    if collection_id not in data["collections"]:
        return None
    coll = data["collections"][collection_id]
    docs = coll.get("documents") or []
    idx = next((i for i, d in enumerate(docs) if d.get("id") == document_id), None)
    if idx is None:
        return None
    removed = docs.pop(idx)
    _save_store(data)
    return removed
