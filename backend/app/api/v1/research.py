"""Research API."""
import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.models.schemas import (
    ResearchPlanGenerateRequest,
    ResearchPlanResponse,
    ResearchPlanUpdateRequest,
    ResearchJobCreateRequest,
    ResearchJobResponse,
    ResearchStep,
    ResearchLogEntry,
)
from app.services.research_orchestrator import (
    generate_research_plan,
    update_research_plan,
    get_plan,
    list_research_plans,
    run_research_job,
    get_job,
    list_jobs,
    request_cancel_research_job,
)
from app.services.collection_store import get_collection

router = APIRouter()


@router.get("/plans", response_model=list)
def list_plans_endpoint():
    """List all saved research plans for dropdown."""
    plans = list_research_plans()
    result = []
    for p in plans:
        coll = get_collection(p.get("collection_id", ""))
        result.append({
            "plan_id": p["plan_id"],
            "topic": p["topic"],
            "collection_id": p.get("collection_id", ""),
            "collection_name": coll["name"] if coll else "",
            "steps": p.get("steps", []),
            "updated_at": p.get("updated_at", ""),
        })
    return result


@router.get("/plans/{plan_id}", response_model=ResearchPlanResponse)
def get_plan_endpoint(plan_id: str):
    """Get plan by ID."""
    plan = get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return ResearchPlanResponse(
        plan_id=plan["plan_id"],
        topic=plan["topic"],
        steps=[ResearchStep(**s) for s in plan["steps"]],
        markdown=plan.get("markdown"),
        collection_id=plan.get("collection_id"),
    )


@router.post("/plans:generate", response_model=ResearchPlanResponse)
def generate_plan_endpoint(body: ResearchPlanGenerateRequest):
    """Generate research plan from topic."""
    if not get_collection(body.collection_id):
        raise HTTPException(status_code=404, detail="Collection not found")

    plan = generate_research_plan(body.collection_id, body.topic)
    return ResearchPlanResponse(
        plan_id=plan["plan_id"],
        topic=plan["topic"],
        steps=[ResearchStep(**s) for s in plan["steps"]],
        markdown=plan.get("markdown"),
        collection_id=plan.get("collection_id"),
    )


@router.put("/plans/{plan_id}", response_model=ResearchPlanResponse)
def update_plan_endpoint(plan_id: str, body: ResearchPlanUpdateRequest):
    """Save human-edited plan steps."""
    try:
        plan = update_research_plan(plan_id, [s.model_dump() for s in body.steps])
        return ResearchPlanResponse(
            plan_id=plan["plan_id"],
            topic=plan["topic"],
            steps=[ResearchStep(**s) for s in plan["steps"]],
            markdown=plan.get("markdown"),
            collection_id=plan.get("collection_id"),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


def _sse_event(event: str, data: dict) -> str:
    """Format SSE event."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/jobs:stream")
def create_job_stream_endpoint(body: ResearchJobCreateRequest):
    """Start research job in background, return job_id immediately via SSE done event."""
    if not get_collection(body.collection_id):
        raise HTTPException(status_code=404, detail="Collection not found")
    if not get_plan(body.plan_id):
        raise HTTPException(status_code=404, detail="Plan not found")

    job_id = run_research_job(body.collection_id, body.plan_id, body.topic)
    job = get_job(job_id)

    def generate():
        yield _sse_event(
            "done",
            {
                "job_id": job["job_id"],
                "status": job["status"],
                "result_markdown": job.get("result_markdown"),
                "output_path": job.get("output_path"),
            },
        )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/jobs", response_model=list)
def list_jobs_endpoint(limit: int = 50):
    """List research job history (from disk + in-memory running)."""
    return list_jobs(limit=limit)


@router.post("/jobs", response_model=ResearchJobResponse)
def create_job_endpoint(body: ResearchJobCreateRequest):
    """Start research job in background. Returns immediately with job_id."""
    if not get_collection(body.collection_id):
        raise HTTPException(status_code=404, detail="Collection not found")
    if not get_plan(body.plan_id):
        raise HTTPException(status_code=404, detail="Plan not found")

    job_id = run_research_job(body.collection_id, body.plan_id, body.topic)
    job = get_job(job_id)
    log_entries = []
    for e in job.get("logs", []):
        try:
            log_entries.append(ResearchLogEntry(
                time=e.get("time", ""),
                message=e.get("message", ""),
                level=e.get("level", "info"),
                document=e.get("document"),
                document_count=e.get("document_count"),
                doc_index=e.get("doc_index"),
                doc_total=e.get("doc_total"),
                char_count=e.get("char_count"),
                chunk_index=e.get("chunk_index"),
                chunk_total=e.get("chunk_total"),
                step_count=e.get("step_count"),
                agent=e.get("agent"),
                response_preview=e.get("response_preview"),
            ))
        except Exception as ex:
            log_entries.append(ResearchLogEntry(time="?", message=f"[解析失败: {ex}]", level="info"))
    return ResearchJobResponse(
        job_id=job["job_id"],
        status=job["status"],
        steps=[ResearchStep(**s) for s in job["steps"]],
        result_markdown=job.get("result_markdown"),
        progress=job.get("progress"),
        output_path=job.get("output_path"),
        logs=log_entries,
        started_at=job.get("started_at"),
    )


@router.post("/jobs/{job_id}/cancel")
def cancel_job_endpoint(job_id: str):
    """Request cancellation of a running research job (stops before next step / merge)."""
    ok, reason = request_cancel_research_job(job_id)
    if not ok and reason == "job_not_found":
        raise HTTPException(status_code=404, detail="Job not found or not running on this server")
    if not ok and reason == "not_running":
        raise HTTPException(status_code=400, detail="Job is not running")
    return {"ok": True}


@router.get("/jobs/{job_id}", response_model=ResearchJobResponse)
def get_job_endpoint(job_id: str):
    """Get research job status and result."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    log_entries = []
    for e in job.get("logs", []):
        try:
            log_entries.append(ResearchLogEntry(
                time=e.get("time", ""),
                message=e.get("message", ""),
                level=e.get("level", "info"),
                document=e.get("document"),
                document_count=e.get("document_count"),
                doc_index=e.get("doc_index"),
                doc_total=e.get("doc_total"),
                char_count=e.get("char_count"),
                chunk_index=e.get("chunk_index"),
                chunk_total=e.get("chunk_total"),
                step_count=e.get("step_count"),
                agent=e.get("agent"),
                response_preview=e.get("response_preview"),
            ))
        except Exception as ex:
            log_entries.append(ResearchLogEntry(time="?", message=f"[解析失败: {ex}]", level="info"))
    return ResearchJobResponse(
        job_id=job["job_id"],
        status=job["status"],
        steps=[ResearchStep(**s) for s in job["steps"]],
        result_markdown=job.get("result_markdown"),
        progress=job.get("progress"),
        output_path=job.get("output_path"),
        logs=log_entries,
        started_at=job.get("started_at"),
    )
