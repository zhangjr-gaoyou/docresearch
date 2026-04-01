"""Collections API."""
import logging
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException

from app.core.settings import settings
from app.models.schemas import CollectionCreate, CollectionResponse, DocumentInfo, CollectionCrawlRequest
from app.services.collection_store import (
    create_collection,
    list_collections,
    get_collection,
    add_documents_to_collection,
    remove_document_from_collection,
)
from app.services.document_loader import load_document
from app.services.chunker import chunk_text
from app.services.vector_store import VectorStore
from app.services.web_crawler import fetch_and_extract_markdown, suggest_markdown_filename

router = APIRouter()
logger = logging.getLogger(__name__)

# python-docx 仅支持 .docx，不支持旧版 .doc 二进制格式
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".md", ".markdown"}


def _dedupe_filename(existing: set[str], filename: str) -> str:
    if filename not in existing:
        return filename
    stem = Path(filename).stem
    suffix = Path(filename).suffix or ".md"
    idx = 2
    while True:
        candidate = f"{stem}-{idx}{suffix}"
        if candidate not in existing:
            return candidate
        idx += 1


@router.post("", response_model=CollectionResponse)
def create_collection_endpoint(body: CollectionCreate):
    """Create a new document collection."""
    coll = create_collection(body.name)
    return CollectionResponse(id=coll["id"], name=coll["name"])


@router.get("", response_model=list[CollectionResponse])
def list_collections_endpoint():
    """List all collections."""
    colls = list_collections()
    return [CollectionResponse(id=c["id"], name=c["name"]) for c in colls]


@router.get("/{collection_id}/documents", response_model=list[DocumentInfo])
def list_documents_endpoint(collection_id: str):
    """List documents in a collection."""
    coll = get_collection(collection_id)
    if not coll:
        raise HTTPException(status_code=404, detail="Collection not found")
    docs = coll.get("documents") or []
    return [
        DocumentInfo(
            id=d["id"],
            filename=d.get("filename") or "unknown",
            file_type=d.get("file_type") or "",
        )
        for d in docs
    ]


@router.delete("/{collection_id}/documents/{document_id}")
def delete_document_endpoint(collection_id: str, document_id: str):
    """Remove document from collection metadata, delete uploaded file, and remove vectors."""
    coll = get_collection(collection_id)
    if not coll:
        raise HTTPException(status_code=404, detail="Collection not found")
    docs = coll.get("documents") or []
    if not any(d.get("id") == document_id for d in docs):
        raise HTTPException(status_code=404, detail="Document not found in collection")

    store = VectorStore(collection_id)
    if store.delete_needs_reembed(document_id):
        api_key = settings.DASHSCOPE_API_KEY or os.environ.get("DASHSCOPE_API_KEY", "")
        if not api_key:
            raise HTTPException(
                status_code=503,
                detail="DASHSCOPE_API_KEY not configured. Re-indexing remaining documents requires embeddings.",
            )

    removed_chunks = store.delete_by_document_id(document_id)

    upload_dir = settings.UPLOADS_DIR / collection_id
    if upload_dir.is_dir():
        for p in upload_dir.glob(f"{document_id}.*"):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not delete upload file %s", p)

    remove_document_from_collection(collection_id, document_id)

    return {
        "ok": True,
        "document_id": document_id,
        "removed_chunks": removed_chunks,
    }


@router.post("/{collection_id}/documents:upload")
async def upload_documents(collection_id: str, files: list[UploadFile] = File(...)):
    """Upload documents to collection, chunk, embed, and index."""
    coll = get_collection(collection_id)
    if not coll:
        raise HTTPException(status_code=404, detail="Collection not found")

    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    # 检查 API Key
    api_key = settings.DASHSCOPE_API_KEY or __import__("os").environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="DASHSCOPE_API_KEY not configured. Please set it in backend/.env",
        )

    upload_dir = settings.UPLOADS_DIR / collection_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    store = VectorStore(collection_id)
    added = []

    for file in files:
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {suffix}. Supported: pdf, docx, md",
            )

        try:
            content = await file.read()
        except Exception as e:
            logger.exception("Failed to read file %s", file.filename)
            raise HTTPException(status_code=400, detail=f"Failed to read file: {e}") from e

        doc_id = str(uuid.uuid4())
        save_path = upload_dir / f"{doc_id}{suffix}"
        save_path.write_bytes(content)

        try:
            doc = load_document(save_path)
        except Exception as e:
            logger.exception("Failed to parse document %s", file.filename)
            save_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail=f"Failed to parse document '{file.filename}': {e}",
            ) from e

        if not doc.content.strip():
            logger.warning("Document %s has no extractable text, skipping embedding", file.filename)
            added.append({"id": doc_id, "filename": file.filename or "unknown", "file_type": suffix.lstrip(".")})
            continue

        try:
            chunks = chunk_text(doc.content, doc_id)
            store.add_chunks(chunks)
        except Exception as e:
            logger.exception("Failed to embed document %s", file.filename)
            save_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=503,
                detail=f"Embedding failed (check DASHSCOPE_API_KEY): {e}",
            ) from e

        added.append({
            "id": doc_id,
            "filename": file.filename or "unknown",
            "file_type": suffix.lstrip("."),
        })

    add_documents_to_collection(collection_id, added)

    return {"uploaded": len(added), "documents": added}


@router.post("/{collection_id}/crawl", response_model=dict)
def crawl_document_endpoint(collection_id: str, body: CollectionCrawlRequest):
    """Crawl one web URL, save markdown into collection, and index to vector store."""
    coll = get_collection(collection_id)
    if not coll:
        raise HTTPException(status_code=404, detail="Collection not found")

    api_key = settings.DASHSCOPE_API_KEY or os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="DASHSCOPE_API_KEY not configured. Please set it in backend/.env",
        )

    try:
        page = fetch_and_extract_markdown(str(body.url))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to crawl url %s", body.url)
        raise HTTPException(status_code=502, detail=f"Failed to fetch page: {e}") from e

    existing_filenames = {
        str(d.get("filename", "")).strip()
        for d in (coll.get("documents") or [])
        if d.get("filename")
    }
    filename = _dedupe_filename(existing_filenames, suggest_markdown_filename(page.title))

    upload_dir = settings.UPLOADS_DIR / collection_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    doc_id = str(uuid.uuid4())
    save_path = upload_dir / f"{doc_id}.md"
    save_path.write_text(page.markdown, encoding="utf-8")

    try:
        chunks = chunk_text(page.markdown, doc_id)
        VectorStore(collection_id).add_chunks(chunks)
    except Exception as e:
        logger.exception("Failed to embed crawled page %s", body.url)
        save_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=503,
            detail=f"Embedding failed (check DASHSCOPE_API_KEY): {e}",
        ) from e

    doc_meta = {"id": doc_id, "filename": filename, "file_type": "md"}
    add_documents_to_collection(collection_id, [doc_meta])
    return {"document": doc_meta}
