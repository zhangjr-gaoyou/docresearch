"""Knowledge extraction API."""

from fastapi import APIRouter, HTTPException

from app.models.schemas import (
    KnowledgeJobCreateRequest,
    KnowledgeJobResponse,
    KnowledgeLogEntry,
    KnowledgeResultItem,
    KnowledgeResultCreateRequest,
    KnowledgeResultUpdateRequest,
    KnowledgeGraphResponse,
    KnowledgeRetrieveRequest,
    KnowledgeRetrieveResponse,
    KnowledgeCitationItem,
    KnowledgeRetrieveLogItem,
)
from app.services.collection_store import get_collection
from app.services.knowledge_extraction_orchestrator import (
    run_knowledge_job,
    get_job,
    list_jobs,
    request_cancel_knowledge_job,
)
from app.services.knowledge_store import (
    list_result_items,
    create_result_item,
    update_result_item,
    delete_result_item,
)
from app.services.graph_store_neo4j import Neo4jGraphStore
from app.services.knowledge_retrieval_service import retrieve_and_answer

router = APIRouter()


@router.post("/jobs", response_model=KnowledgeJobResponse)
def create_knowledge_job(body: KnowledgeJobCreateRequest):
    coll = get_collection(body.collection_id)
    if not coll:
        raise HTTPException(status_code=404, detail="Collection not found")
    job_id = run_knowledge_job(body.collection_id, topic=coll.get("name", "知识提取"))
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=500, detail="Failed to create knowledge job")
    return KnowledgeJobResponse(
        job_id=job["job_id"],
        collection_id=job["collection_id"],
        status=job["status"],
        progress=job.get("progress"),
        logs=[KnowledgeLogEntry(**x) for x in job.get("logs", [])],
        started_at=job.get("started_at"),
        updated_at=job.get("updated_at"),
    )


@router.get("/jobs", response_model=list[KnowledgeJobResponse])
def list_knowledge_jobs(limit: int = 50):
    rows = list_jobs(limit=limit)
    out = []
    for x in rows:
        out.append(
            KnowledgeJobResponse(
                job_id=x.get("job_id", ""),
                collection_id=x.get("collection_id", ""),
                status=x.get("status", "unknown"),
                progress=x.get("progress"),
                logs=[],
                started_at=x.get("started_at"),
                updated_at=x.get("updated_at"),
            )
        )
    return out


@router.get("/jobs/{job_id}", response_model=KnowledgeJobResponse)
def get_knowledge_job(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return KnowledgeJobResponse(
        job_id=job["job_id"],
        collection_id=job["collection_id"],
        status=job["status"],
        progress=job.get("progress"),
        logs=[KnowledgeLogEntry(**x) for x in job.get("logs", [])],
        started_at=job.get("started_at"),
        updated_at=job.get("updated_at"),
    )


@router.post("/jobs/{job_id}/cancel")
def cancel_knowledge_job(job_id: str):
    ok, reason = request_cancel_knowledge_job(job_id)
    if not ok and reason == "job_not_found":
        raise HTTPException(status_code=404, detail="Job not found or not running on this server")
    if not ok and reason == "not_running":
        raise HTTPException(status_code=400, detail="Job is not running")
    return {"ok": True}


@router.get("/results", response_model=list[KnowledgeResultItem])
def list_results(
    collection_id: str,
    document_id: str | None = None,
    result_type: str | None = None,
    keyword: str | None = None,
):
    rows = list_result_items(
        collection_id=collection_id,
        document_id=document_id,
        result_type=result_type,
        keyword=keyword,
    )
    return [KnowledgeResultItem(**x) for x in rows]


@router.post("/results", response_model=KnowledgeResultItem)
def create_result(body: KnowledgeResultCreateRequest):
    if not get_collection(body.collection_id):
        raise HTTPException(status_code=404, detail="Collection not found")
    row = create_result_item(body.model_dump())
    return KnowledgeResultItem(**row)


@router.put("/results/{item_id}", response_model=KnowledgeResultItem)
def update_result(item_id: str, body: KnowledgeResultUpdateRequest):
    row = update_result_item(item_id, body.model_dump(exclude_unset=True))
    if not row:
        raise HTTPException(status_code=404, detail="Result item not found")
    return KnowledgeResultItem(**row)


@router.delete("/results/{item_id}")
def delete_result(item_id: str):
    ok = delete_result_item(item_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Result item not found")
    return {"ok": True}


@router.get("/graph", response_model=KnowledgeGraphResponse)
def get_graph(collection_id: str, limit: int = 300):
    if not get_collection(collection_id):
        raise HTTPException(status_code=404, detail="Collection not found")
    store = Neo4jGraphStore()
    data = store.read_graph(collection_id=collection_id, limit=limit)
    return KnowledgeGraphResponse(nodes=data.get("nodes", []), edges=data.get("edges", []))


@router.post("/retrieve", response_model=KnowledgeRetrieveResponse)
def retrieve_knowledge(body: KnowledgeRetrieveRequest):
    if not get_collection(body.collection_id):
        raise HTTPException(status_code=404, detail="Collection not found")
    result = retrieve_and_answer(body.collection_id, body.query, top_k=body.top_k)
    log_rows = result.get("logs") or []
    log_items: list[KnowledgeRetrieveLogItem] = []
    for x in log_rows:
        if isinstance(x, dict):
            log_items.append(
                KnowledgeRetrieveLogItem(
                    time=str(x.get("time", "")),
                    message=str(x.get("message", "")),
                    level=str(x.get("level") or "info"),
                )
            )
    return KnowledgeRetrieveResponse(
        answer=str(result.get("answer", "")),
        route=str(result.get("route", "analysis")),
        citations=[KnowledgeCitationItem(**x) for x in (result.get("citations") or [])],
        retrieved_chunks=list(result.get("retrieved_chunks") or []),
        logs=log_items,
    )
