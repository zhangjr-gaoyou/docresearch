"""Storage for knowledge extraction jobs and result items."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.core.settings import settings

RESULTS_FILE = settings.DATA_DIR / "knowledge_results.json"
META_FILE = "job_meta.json"
LOGS_FILE = "job_logs.json"


def _now() -> str:
    return datetime.now().isoformat()


def _load_results() -> dict:
    if not RESULTS_FILE.exists():
        return {"items": []}
    try:
        return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"items": []}


def _save_results(data: dict) -> None:
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def list_result_items(
    *,
    collection_id: Optional[str] = None,
    document_id: Optional[str] = None,
    result_type: Optional[str] = None,
    keyword: Optional[str] = None,
) -> list[dict]:
    data = _load_results()
    items = data.get("items", [])
    out: list[dict] = []
    kw = (keyword or "").strip().lower()
    for item in items:
        if collection_id and item.get("collection_id") != collection_id:
            continue
        if document_id and item.get("document_id") != document_id:
            continue
        if result_type and item.get("result_type") != result_type:
            continue
        if kw:
            joined = " ".join(
                [
                    str(item.get("title", "")),
                    str(item.get("content", "")),
                    " ".join(item.get("tags", []) or []),
                ]
            ).lower()
            if kw not in joined:
                continue
        out.append(item)
    out.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return out


def create_result_item(payload: dict) -> dict:
    data = _load_results()
    item = {
        "id": str(uuid.uuid4()),
        "collection_id": payload["collection_id"],
        "document_id": payload["document_id"],
        "document_name": payload.get("document_name", ""),
        "result_type": payload["result_type"],
        "title": payload.get("title", ""),
        "content": payload.get("content", ""),
        "tags": payload.get("tags", []) or [],
        "extra": payload.get("extra"),
        "created_at": _now(),
        "updated_at": _now(),
    }
    data.setdefault("items", []).append(item)
    _save_results(data)
    return item


def update_result_item(item_id: str, payload: dict) -> Optional[dict]:
    data = _load_results()
    items = data.get("items", [])
    for item in items:
        if item.get("id") != item_id:
            continue
        for key in ("title", "content", "tags", "extra"):
            if key in payload and payload[key] is not None:
                item[key] = payload[key]
        item["updated_at"] = _now()
        _save_results(data)
        return item
    return None


def delete_result_item(item_id: str) -> bool:
    data = _load_results()
    items = data.get("items", [])
    idx = next((i for i, x in enumerate(items) if x.get("id") == item_id), None)
    if idx is None:
        return False
    items.pop(idx)
    _save_results(data)
    return True


def bulk_replace_collection_document_items(
    *,
    collection_id: str,
    document_id: str,
    new_items: list[dict],
) -> None:
    data = _load_results()
    items = data.get("items", [])
    kept = [
        x
        for x in items
        if not (x.get("collection_id") == collection_id and x.get("document_id") == document_id)
    ]
    data["items"] = kept + new_items
    _save_results(data)


def _job_dir(job_id: str) -> Path:
    return settings.KNOWLEDGE_OUTPUT_DIR / job_id


def write_job_meta(job_id: str, meta: dict) -> None:
    d = _job_dir(job_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / META_FILE).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def read_job_meta(job_id: str) -> Optional[dict]:
    path = _job_dir(job_id) / META_FILE
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_job_logs(job_id: str, logs: list[dict]) -> None:
    d = _job_dir(job_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / LOGS_FILE).write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8")


def read_job_logs(job_id: str) -> list[dict]:
    path = _job_dir(job_id) / LOGS_FILE
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def list_jobs(limit: int = 50) -> list[dict]:
    base = settings.KNOWLEDGE_OUTPUT_DIR
    if not base.exists():
        return []
    rows: list[dict] = []
    for d in base.iterdir():
        if not d.is_dir():
            continue
        meta = read_job_meta(d.name)
        if meta:
            rows.append(meta)
    rows.sort(key=lambda x: x.get("started_at", ""), reverse=True)
    return rows[:limit]
