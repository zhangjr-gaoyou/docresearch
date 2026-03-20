"""Tools API: document reading and analysis."""
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.core.settings import settings
from app.services.document_loader import load_document
from app.services.research.step_execution_agent import execute_step

router = APIRouter()


@router.post("/documents:read")
async def read_document(file: UploadFile):
    """Read document content (PDF, DOCX, Markdown)."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".pdf", ".docx", ".doc", ".md", ".markdown"):
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")

    tmp = settings.UPLOADS_DIR / "_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    path = tmp / f"{uuid.uuid4()}{suffix}"
    try:
        content = await file.read()
        path.write_bytes(content)
        doc = load_document(path)
        return {"content": doc.content, "filename": doc.filename, "file_type": doc.file_type}
    finally:
        if path.exists():
            path.unlink(missing_ok=True)


@router.post("/documents:analyze")
async def analyze_document(file: UploadFile = File(...), topic: str = Form("")):
    """
    Analyze document content. Uses map-reduce for large documents.
    topic: optional analysis focus.
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".pdf", ".docx", ".doc", ".md", ".markdown"):
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")

    tmp = settings.UPLOADS_DIR / "_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    path = tmp / f"{uuid.uuid4()}{suffix}"
    try:
        content = await file.read()
        path.write_bytes(content)
        doc = load_document(path)
    finally:
        if path.exists():
            path.unlink(missing_ok=True)

    step_content = "分析文档主要内容与结构"
    if topic:
        step_content = f"围绕主题「{topic}」分析文档"

    result = execute_step(
        topic=topic or "文档分析",
        step_content=step_content,
        step_index=0,
        prior_step_markdown="",
        collection_doc_markdown=doc.content,
        doc_label=doc.filename or "",
        on_log=None,
    )
    return {"analysis": result, "filename": doc.filename}
