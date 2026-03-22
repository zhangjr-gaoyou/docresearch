"""Job metadata and logs persistence for research tasks."""
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from app.core.settings import settings

META_FILE = "job_meta.json"
LOGS_FILE = "job_logs.json"


def _job_dir(job_id: str) -> Path:
    return settings.RESEARCH_OUTPUT_DIR / job_id


def resolve_job_output_dir(job_id: str) -> Optional[Path]:
    """
    Return resolved job output directory if it exists and stays under RESEARCH_OUTPUT_DIR.
    Rejects path traversal (job_id must be a single path segment).
    """
    if not job_id or "\x00" in job_id:
        return None
    if "/" in job_id or "\\" in job_id or job_id in (".", ".."):
        return None
    base = settings.RESEARCH_OUTPUT_DIR.resolve()
    d = (settings.RESEARCH_OUTPUT_DIR / job_id).resolve()
    try:
        d.relative_to(base)
    except ValueError:
        return None
    if not d.is_dir():
        return None
    return d


def write_job_meta(job_id: str, meta: dict) -> None:
    """Write job_meta.json to job output directory."""
    d = _job_dir(job_id)
    d.mkdir(parents=True, exist_ok=True)
    path = d / META_FILE
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def read_job_meta(job_id: str) -> Optional[dict]:
    """Read job_meta.json. Returns None if not found."""
    path = _job_dir(job_id) / META_FILE
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_job_logs(job_id: str, logs: list) -> None:
    """Write full logs array to job_logs.json."""
    d = _job_dir(job_id)
    d.mkdir(parents=True, exist_ok=True)
    path = d / LOGS_FILE
    path.write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8")


def read_job_logs(job_id: str) -> list:
    """Read job_logs.json. Returns empty list if not found."""
    path = _job_dir(job_id) / LOGS_FILE
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def list_jobs(limit: int = 50) -> list[dict]:
    """List jobs from disk by scanning RESEARCH_OUTPUT_DIR. Returns sorted by started_at desc."""
    base = settings.RESEARCH_OUTPUT_DIR
    if not base.exists():
        return []
    results = []
    for item in base.iterdir():
        if not item.is_dir():
            continue
        meta = read_job_meta(item.name)
        if meta:
            results.append(meta)
    results.sort(key=lambda m: m.get("started_at", ""), reverse=True)
    return results[:limit]


def fix_stale_running_jobs() -> None:
    """On startup: mark any disk meta with status=running as interrupted."""
    base = settings.RESEARCH_OUTPUT_DIR
    if not base.exists():
        return
    for item in base.iterdir():
        if not item.is_dir():
            continue
        meta = read_job_meta(item.name)
        if meta and meta.get("status") == "running":
            meta["status"] = "interrupted"
            meta["progress"] = "进程重启后已中断"
            meta["updated_at"] = datetime.now().isoformat()
            write_job_meta(item.name, meta)
