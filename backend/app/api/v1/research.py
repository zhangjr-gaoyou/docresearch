"""Research API."""
import io
import json
import zipfile
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse

from app.models.schemas import (
    ResearchProjectCreateRequest,
    ResearchPlanGenerateRequest,
    ResearchPlanResponse,
    ResearchPlanUpdateRequest,
    ResearchJobCreateRequest,
    ResearchJobResponse,
    ResearchStep,
    ResearchLogEntry,
)
from app.services.research_orchestrator import (
    create_research_project,
    generate_research_plan,
    update_research_plan,
    get_plan,
    list_research_plans,
    run_research_job,
    get_job,
    list_jobs,
    request_cancel_research_job,
    resume_research_job,
)
from app.services.collection_store import get_collection
from app.services.job_store import resolve_job_output_dir

router = APIRouter()


def _coerce_research_steps(raw) -> list[ResearchStep]:
    """
    Build ResearchStep list from persisted JSON (may omit fields or use wrong types).
    Prevents 500 from Pydantic validation when plans/jobs carry legacy or partial steps.
    """
    if raw is None or not isinstance(raw, list):
        return []
    out: list[ResearchStep] = []
    for i, item in enumerate(raw):
        if isinstance(item, dict):
            try:
                idx = item.get("index", i)
                idx = int(idx) if idx is not None else i
            except (TypeError, ValueError):
                idx = i
            content = item.get("content", "")
            content = "" if content is None else str(content)
            status = item.get("status")
            if status is None or not isinstance(status, str):
                status = "pending"
            out.append(ResearchStep(index=idx, content=content, status=status))
        elif isinstance(item, str):
            out.append(ResearchStep(index=i, content=item, status="pending"))
    return out


def _plan_to_response(plan: dict) -> ResearchPlanResponse:
    pid = plan.get("plan_id")
    plan_id = "" if pid is None else str(pid)
    top = plan.get("topic")
    topic = "" if top is None else str(top)
    return ResearchPlanResponse(
        plan_id=plan_id,
        topic=topic,
        steps=_coerce_research_steps(plan.get("steps")),
        markdown=plan.get("markdown"),
        collection_id=plan.get("collection_id"),
        title=plan.get("title"),
    )


def _job_log_from_dict(e: dict) -> ResearchLogEntry:
    return ResearchLogEntry(
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
        step_index=e.get("step_index"),
        step_total=e.get("step_total"),
        step_count=e.get("step_count"),
        need_collection_document=e.get("need_collection_document"),
        output_path=e.get("output_path"),
        agent=e.get("agent"),
        response_preview=e.get("response_preview"),
        prompt_slot=e.get("prompt_slot"),
        prompt_preview=e.get("prompt_preview"),
        tool_name=e.get("tool_name"),
        tool_detail=e.get("tool_detail"),
    )


@router.get("/plans", response_model=list)
def list_plans_endpoint():
    """List all saved research plans for dropdown."""
    plans = list_research_plans()
    result = []
    for p in plans:
        coll = get_collection(p.get("collection_id", ""))
        result.append({
            "plan_id": p.get("plan_id", ""),
            "title": p.get("title"),
            "topic": p.get("topic", ""),
            "collection_id": p.get("collection_id", ""),
            "collection_name": coll["name"] if coll else "",
            "steps": p.get("steps") if isinstance(p.get("steps"), list) else [],
            "updated_at": p.get("updated_at", ""),
        })
    return result


@router.get("/plans/{plan_id}", response_model=ResearchPlanResponse)
def get_plan_endpoint(plan_id: str):
    """Get plan by ID."""
    plan = get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return _plan_to_response(plan)


@router.post("/projects", response_model=ResearchPlanResponse)
def create_research_project_endpoint(body: ResearchProjectCreateRequest):
    """Create a research project (saved plan with empty steps, no LLM)."""
    if not get_collection(body.collection_id):
        raise HTTPException(status_code=404, detail="Collection not found")
    plan = create_research_project(body.collection_id, body.topic, body.title)
    return _plan_to_response(plan)


@router.post("/plans:generate", response_model=ResearchPlanResponse)
def generate_plan_endpoint(body: ResearchPlanGenerateRequest):
    """Generate research plan steps from topic (new plan or update existing plan_id)."""
    if not get_collection(body.collection_id):
        raise HTTPException(status_code=404, detail="Collection not found")
    try:
        plan = generate_research_plan(
            body.collection_id,
            body.topic,
            plan_id=body.plan_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _plan_to_response(plan)


@router.put("/plans/{plan_id}", response_model=ResearchPlanResponse)
def update_plan_endpoint(plan_id: str, body: ResearchPlanUpdateRequest):
    """Save human-edited plan steps."""
    try:
        plan = update_research_plan(plan_id, [s.model_dump() for s in body.steps])
        return _plan_to_response(plan)
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
            log_entries.append(_job_log_from_dict(e))
        except Exception as ex:
            log_entries.append(ResearchLogEntry(time="?", message=f"[解析失败: {ex}]", level="info"))
    return ResearchJobResponse(
        job_id=job["job_id"],
        status=job["status"],
        steps=_coerce_research_steps(job.get("steps")),
        result_markdown=job.get("result_markdown"),
        progress=job.get("progress"),
        output_path=job.get("output_path"),
        logs=log_entries,
        started_at=job.get("started_at"),
        title=job.get("title"),
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


@router.post("/jobs/{job_id}/resume")
def resume_job_endpoint(job_id: str):
    """Continue a cancelled or interrupted job from saved step outputs on disk."""
    ok, reason = resume_research_job(job_id)
    if ok:
        return {"ok": True}
    if reason in ("job_not_found",):
        raise HTTPException(status_code=404, detail="Job not found")
    if reason in ("plan_not_found", "collection_not_found"):
        raise HTTPException(status_code=404, detail="Plan or collection missing; cannot resume")
    if reason == "already_running":
        raise HTTPException(status_code=400, detail="Job is already running")
    if reason == "not_resumable":
        raise HTTPException(status_code=400, detail="Job cannot be resumed (e.g. completed or failed)")
    raise HTTPException(status_code=400, detail=reason)


@router.get("/jobs/{job_id}/download/final")
def download_job_final_markdown(job_id: str):
    """Download merged report final.md for a job."""
    d = resolve_job_output_dir(job_id)
    if not d:
        raise HTTPException(status_code=404, detail="Job output not found")
    path = d / "final.md"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="final.md not available yet")
    return FileResponse(
        path,
        filename=f"research_{job_id}_final.md",
        media_type="text/markdown; charset=utf-8",
    )


@router.get("/jobs/{job_id}/download/package")
def download_job_output_package(job_id: str):
    """Zip entire job output directory (plan.md, final.md, steps/, etc.)."""
    d = resolve_job_output_dir(job_id)
    if not d:
        raise HTTPException(status_code=404, detail="Job output not found")
    files = [f for f in d.rglob("*") if f.is_file()]
    if not files:
        raise HTTPException(status_code=404, detail="No files in job output")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(files):
            zf.write(f, f.relative_to(d).as_posix())
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="research_{job_id}.zip"',
        },
    )


@router.get("/jobs/{job_id}", response_model=ResearchJobResponse)
def get_job_endpoint(job_id: str):
    """Get research job status and result."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    log_entries = []
    for e in job.get("logs", []):
        try:
            log_entries.append(_job_log_from_dict(e))
        except Exception as ex:
            log_entries.append(ResearchLogEntry(time="?", message=f"[解析失败: {ex}]", level="info"))
    return ResearchJobResponse(
        job_id=job["job_id"],
        status=job["status"],
        steps=_coerce_research_steps(job.get("steps")),
        result_markdown=job.get("result_markdown"),
        progress=job.get("progress"),
        output_path=job.get("output_path"),
        logs=log_entries,
        started_at=job.get("started_at"),
        title=job.get("title"),
    )
