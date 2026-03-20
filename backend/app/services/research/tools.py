"""Research tools: list documents, read collection document, read/write step results."""
import re
from pathlib import Path
from typing import Optional

from app.core.settings import settings
from app.services.document_loader import load_document
from app.services.collection_store import get_collection

ALLOWED_SUFFIXES = (".pdf", ".docx", ".doc", ".md", ".markdown")
MAX_DOC_NAMES_IN_PROMPT = 50
STEP_DIR = "steps"
STEP_FILE_PATTERN = "step_{idx:02d}.md"


def list_collection_document_files(collection_id: str) -> list[Path]:
    """
    List document files in a collection (from UPLOADS_DIR).
    Returns sorted list of Paths for PDF, DOCX, MD files.
    """
    uploads_dir = settings.UPLOADS_DIR / collection_id
    if not uploads_dir.exists():
        return []
    files = [
        f
        for f in uploads_dir.iterdir()
        if f.is_file() and f.suffix.lower() in ALLOWED_SUFFIXES
    ]
    return sorted(files, key=lambda p: p.name)


def get_collection_document_names(collection_id: str) -> list[tuple[str, str]]:
    """
    Returns (doc_key/stem, display_name) for each document.
    display_name from collection_store metadata or path.name.
    """
    paths = list_collection_document_files(collection_id)
    coll = get_collection(collection_id)
    doc_by_id = {d["id"]: d for d in (coll.get("documents") or [])} if coll else {}
    result = []
    for p in paths:
        stem = p.stem
        display = (doc_by_id.get(stem) or {}).get("filename") or p.name
        result.append((stem, display))
    return result


def read_collection_document_text(file_path: Path) -> str:
    """
    Load document content from a Path (typically from list_collection_document_files).
    Returns raw text content.
    """
    doc = load_document(file_path)
    return doc.content


def _step_file_path(job_output_dir: Path, doc_key: str, step_index: int) -> Path:
    """Build path for step result file."""
    steps_dir = job_output_dir / STEP_DIR / _safe_doc_key(doc_key)
    return steps_dir / STEP_FILE_PATTERN.format(idx=step_index)


def _safe_doc_key(doc_key: str) -> str:
    """Sanitize doc key for filesystem (remove path separators, etc)."""
    return re.sub(r'[^\w\-.]', '_', doc_key) or "doc"


def read_step_result_markdown(
    job_output_dir: Path,
    doc_key: str,
    step_index: int,
) -> Optional[str]:
    """
    Read step result markdown file.
    Returns content or None if file does not exist.
    """
    path = _step_file_path(job_output_dir, doc_key, step_index)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def write_step_result_markdown(
    job_output_dir: Path,
    doc_key: str,
    step_index: int,
    content: str,
) -> Path:
    """
    Write step result to markdown file.
    Returns the written file path.
    """
    path = _step_file_path(job_output_dir, doc_key, step_index)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
