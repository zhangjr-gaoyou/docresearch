"""Research orchestrator: plan generation, step execution, result merging."""
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from langchain_openai import ChatOpenAI

from app.core.settings import settings
from app.services.job_store import (
    fix_stale_running_jobs,
    read_job_logs,
    read_job_meta,
    write_job_logs,
    write_job_meta,
)
from app.services.plan_store import save_plan as _persist_plan, load_all_plans

# In-memory store (loaded from file on startup)
_plans: dict = {}
_jobs: dict = {}

# Load persisted plans on module init
_plans.update(load_all_plans())
# Mark stale running jobs as interrupted
fix_stale_running_jobs()


def _get_llm():
    """Create LLM client for DashScope (Qwen)."""
    api_key = settings.DASHSCOPE_API_KEY or os.getenv("DASHSCOPE_API_KEY", "")
    return ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        temperature=0.3,
    )


def create_research_project(collection_id: str, topic: str, title: str) -> dict:
    """
    Persist a research project (plan) with empty steps — no LLM call.
    """
    t = (topic or "").strip()
    ti = (title or "").strip()
    plan_id = str(uuid.uuid4())
    plan = {
        "plan_id": plan_id,
        "collection_id": collection_id,
        "title": ti,
        "topic": t,
        "steps": [],
        "markdown": f"# {ti}\n\n**研究主题**：{t}\n\n（尚未生成研究步骤，请点击「制定研究计划」）",
    }
    _plans[plan_id] = plan
    _persist_plan(plan)
    return plan


def generate_research_plan(
    collection_id: str,
    topic: str,
    plan_id: Optional[str] = None,
) -> dict:
    """
    Generate research plan steps via LLM.
    If plan_id is set, update that existing plan in place; otherwise create a new plan_id.
    """
    from app.services.research.plan_agent import generate_plan_steps

    t = (topic or "").strip()
    steps = generate_plan_steps(collection_id, t)
    md = f"# 研究计划：{t}\n\n" + "\n".join(f"{i + 1}. {s['content']}" for i, s in enumerate(steps))

    if plan_id:
        plan = get_plan(plan_id)
        if not plan:
            raise ValueError(f"Plan {plan_id} not found")
        plan["collection_id"] = collection_id
        plan["topic"] = t
        plan["steps"] = steps
        plan["markdown"] = md
        _plans[plan_id] = plan
        _persist_plan(plan)
        return plan

    new_id = str(uuid.uuid4())
    plan = {
        "plan_id": new_id,
        "collection_id": collection_id,
        "topic": t,
        "title": None,
        "steps": steps,
        "markdown": md,
    }
    _plans[new_id] = plan
    _persist_plan(plan)
    return plan


def update_research_plan(plan_id: str, steps: List[dict]) -> dict:
    """Save human-edited plan steps."""
    if plan_id not in _plans:
        raise ValueError(f"Plan {plan_id} not found")
    plan = _plans[plan_id]
    plan["steps"] = steps
    plan["markdown"] = f"# 研究计划：{plan['topic']}\n\n" + "\n".join(f"{s['index']+1}. {s['content']}" for s in steps)
    _persist_plan(plan)
    return plan


def get_plan(plan_id: str) -> Optional[dict]:
    """Get plan by ID (from memory, load from store if missing)."""
    if plan_id in _plans:
        return _plans[plan_id]
    from app.services.plan_store import get_plan_from_store
    p = get_plan_from_store(plan_id)
    if p:
        _plans[plan_id] = p
    return p


def list_research_plans():
    """List all saved plans for dropdown."""
    from app.services.plan_store import list_plans
    return list_plans()


def _add_log(logs: list, message: str, level: str = "info", **extra):
    """Append execution log entry."""
    logs.append({
        "time": datetime.now().strftime("%H:%M:%S"),
        "message": message,
        "level": level,
        **extra,
    })


class _PersistingLogList(list):
    """List that persists to disk and optionally notifies on append."""

    def __init__(self, job_id: str, on_append: Optional[Callable[[dict], None]] = None):
        super().__init__()
        self._job_id = job_id
        self.on_append = on_append or (lambda _: None)

    def append(self, item):
        super().append(item)
        self.on_append(item)
        write_job_logs(self._job_id, list(self))


def _flush_job_meta(job_id: str, job: dict) -> None:
    """Write job metadata to disk."""
    meta = {
        "job_id": job_id,
        "collection_id": job.get("collection_id", ""),
        "plan_id": job.get("plan_id", ""),
        "topic": job.get("topic", ""),
        "title": job.get("title"),
        "status": job.get("status", "running"),
        "progress": job.get("progress", ""),
        "output_path": job.get("output_path"),
        "started_at": job.get("started_at", ""),
        "updated_at": datetime.now().isoformat(),
    }
    write_job_meta(job_id, meta)


def _run_research_job_worker(job_id: str) -> None:
    """Background worker: run scheduler and update job state."""
    job = _jobs.get(job_id)
    if not job:
        return
    collection_id = job["collection_id"]
    plan_id = job["plan_id"]
    topic = job["topic"]
    plan = get_plan(plan_id)
    if not plan:
        job["status"] = "failed"
        job["progress"] = "Plan not found"
        _flush_job_meta(job_id, job)
        return

    output_dir = settings.RESEARCH_OUTPUT_DIR / job_id
    logs = job["logs"]

    from app.services.research.exceptions import ResearchJobCancelled
    from app.services.research.scheduler_agent import run_scheduler

    def on_progress(p: str):
        job["progress"] = p
        _flush_job_meta(job_id, job)

    cancel_event = job.get("cancel_event")
    resume_flag = bool(job.pop("resume", False))

    try:
        final_md, output_path = run_scheduler(
            collection_id=collection_id,
            plan=plan,
            topic=topic,
            job_output_dir=output_dir,
            logs=logs,
            on_progress=on_progress,
            cancel_event=cancel_event,
            resume=resume_flag,
        )
        from app.services.research.tools import list_collection_document_files
        doc_count = len(list_collection_document_files(collection_id))
        job["status"] = "completed"
        job["result_markdown"] = final_md
        job["progress"] = f"Completed {doc_count} documents"
        job["output_path"] = output_path
        _add_log(logs, "研究计划执行完成", level="success")
    except ResearchJobCancelled:
        job["status"] = "cancelled"
        job["progress"] = "用户已中止，未执行的步骤不再运行"
        job["output_path"] = str(output_dir.resolve())
        _add_log(logs, "任务已由用户中止", level="warning")
    except Exception as e:
        job["status"] = "failed"
        job["progress"] = str(e)
        _add_log(logs, f"执行失败：{str(e)}", level="error")
    finally:
        _flush_job_meta(job_id, job)


def run_research_job(
    collection_id: str,
    plan_id: str,
    topic: str,
    on_log: Optional[Callable[[dict], None]] = None,
) -> str:
    """
    Start research job in background. Returns job_id immediately.
    """
    plan = get_plan(plan_id)
    if not plan:
        raise ValueError(f"Plan {plan_id} not found")

    job_id = str(uuid.uuid4())
    output_dir = settings.RESEARCH_OUTPUT_DIR / job_id
    output_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now().isoformat()
    logs = _PersistingLogList(job_id, on_append=on_log)
    job = {
        "job_id": job_id,
        "collection_id": collection_id,
        "plan_id": plan_id,
        "topic": topic,
        "title": plan.get("title"),
        "status": "running",
        "steps": plan["steps"],
        "result_markdown": None,
        "progress": "",
        "logs": logs,
        "output_path": None,
        "started_at": now,
        "cancel_event": threading.Event(),
    }
    _jobs[job_id] = job
    _flush_job_meta(job_id, job)

    _add_log(logs, f"开始执行研究计划，主题：{topic}", level="info")

    # Save research plan to plan.md
    plan_md = f"""# 研究计划

- **研究主题**：{topic}
- **执行时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- **文档集**：{collection_id}

## 研究步骤

"""
    for i, s in enumerate(plan["steps"], 1):
        content = (s.get("content") or "").strip()
        plan_md += f"{i}. {content}\n\n"
    (output_dir / "plan.md").write_text(plan_md.strip(), encoding="utf-8")
    _add_log(logs, "研究计划已保存到 plan.md", level="info")

    thread = threading.Thread(target=_run_research_job_worker, args=(job_id,), daemon=True)
    thread.start()

    return job_id


def resume_research_job(job_id: str) -> tuple[bool, str]:
    """
    Continue a cancelled (or interrupted-on-disk) job from saved step outputs.
    Returns (ok, reason): ok | already_running | not_resumable | job_not_found | plan_not_found
    """
    job = _jobs.get(job_id)
    if job:
        if job.get("status") == "running":
            return False, "already_running"
        if job.get("status") != "cancelled":
            return False, "not_resumable"
        job["cancel_event"] = threading.Event()
        job["status"] = "running"
        job["resume"] = True
        job["progress"] = "继续执行中…"
        job["result_markdown"] = None
        _add_log(job["logs"], "从已保存进度继续执行研究计划", level="info")
        _flush_job_meta(job_id, job)
        thread = threading.Thread(target=_run_research_job_worker, args=(job_id,), daemon=True)
        thread.start()
        return True, "ok"

    meta = read_job_meta(job_id)
    if not meta:
        return False, "job_not_found"
    if meta.get("status") not in ("cancelled", "interrupted"):
        return False, "not_resumable"

    plan_id = meta.get("plan_id", "")
    plan = get_plan(plan_id)
    if not plan:
        return False, "plan_not_found"

    coll_id = meta.get("collection_id", "")
    from app.services.collection_store import get_collection as _get_coll
    if not _get_coll(coll_id):
        return False, "collection_not_found"

    logs = _PersistingLogList(job_id)
    logs.extend(read_job_logs(job_id))
    write_job_logs(job_id, list(logs))

    output_dir = settings.RESEARCH_OUTPUT_DIR / job_id
    job = {
        "job_id": job_id,
        "collection_id": coll_id,
        "plan_id": plan_id,
        "topic": meta.get("topic", ""),
        "title": meta.get("title") or plan.get("title"),
        "status": "running",
        "steps": plan["steps"],
        "result_markdown": None,
        "progress": "继续执行中…",
        "logs": logs,
        "output_path": meta.get("output_path") or str(output_dir.resolve()),
        "started_at": meta.get("started_at", ""),
        "cancel_event": threading.Event(),
        "resume": True,
    }
    _jobs[job_id] = job
    _flush_job_meta(job_id, job)
    _add_log(logs, "从磁盘恢复任务并继续执行（跳过已保存的步骤）", level="info")

    thread = threading.Thread(target=_run_research_job_worker, args=(job_id,), daemon=True)
    thread.start()
    return True, "ok"


def request_cancel_research_job(job_id: str) -> tuple[bool, str]:
    """
    Signal a running in-memory job to stop after the current LLM boundary.
    Returns (ok, reason) where reason is 'ok' | 'job_not_found' | 'not_running'.
    """
    job = _jobs.get(job_id)
    if not job:
        return False, "job_not_found"
    if job.get("status") != "running":
        return False, "not_running"
    ev = job.get("cancel_event")
    if isinstance(ev, threading.Event):
        ev.set()
    return True, "ok"


def get_job(job_id: str) -> Optional[dict]:
    """Get job by ID. Hydrates from disk if not in memory."""
    if job_id in _jobs:
        j = _jobs[job_id]
        if not j.get("title") and j.get("plan_id"):
            pl = get_plan(j["plan_id"])
            if pl and pl.get("title"):
                j["title"] = pl["title"]
        return j

    meta = read_job_meta(job_id)
    if not meta:
        return None

    logs = read_job_logs(job_id)
    output_path = meta.get("output_path")
    result_markdown = meta.get("result_markdown")

    if result_markdown is None and output_path:
        final_path = Path(output_path) / "final.md" if output_path else None
        if final_path and Path(final_path).exists():
            try:
                result_markdown = Path(final_path).read_text(encoding="utf-8")
            except OSError:
                result_markdown = None
    if result_markdown is None:
        final_path = settings.RESEARCH_OUTPUT_DIR / job_id / "final.md"
        if final_path.exists():
            try:
                result_markdown = final_path.read_text(encoding="utf-8")
            except OSError:
                result_markdown = None

    plan = get_plan(meta.get("plan_id", "")) if meta.get("plan_id") else None
    steps = plan.get("steps", []) if plan else []
    display_title = meta.get("title")
    if not display_title and plan:
        display_title = plan.get("title")

    return {
        "job_id": job_id,
        "collection_id": meta.get("collection_id", ""),
        "plan_id": meta.get("plan_id", ""),
        "topic": meta.get("topic", ""),
        "title": display_title,
        "status": meta.get("status", "unknown"),
        "steps": steps,
        "result_markdown": result_markdown,
        "progress": meta.get("progress", ""),
        "output_path": output_path or str(settings.RESEARCH_OUTPUT_DIR / job_id),
        "logs": logs,
        "started_at": meta.get("started_at", ""),
    }


def _enrich_job_list_row(meta: dict) -> dict:
    """Ensure list rows have title when plan has one (backfill old job_meta without title)."""
    row = dict(meta)
    if not row.get("title") and row.get("plan_id"):
        pl = get_plan(row["plan_id"])
        if pl and pl.get("title"):
            row["title"] = pl["title"]
    return row


def list_jobs(limit: int = 50) -> list[dict]:
    """List research jobs from disk (and merge with in-memory running jobs)."""
    from app.services.job_store import list_jobs as _list_jobs_from_disk
    disk = [_enrich_job_list_row(m) for m in _list_jobs_from_disk(limit=limit * 2)]
    seen = {j["job_id"] for j in disk}
    for jid, j in _jobs.items():
        if jid not in seen:
            meta = {
                "job_id": jid,
                "collection_id": j.get("collection_id", ""),
                "plan_id": j.get("plan_id", ""),
                "topic": j.get("topic", ""),
                "title": j.get("title"),
                "status": j.get("status", "running"),
                "progress": j.get("progress", ""),
                "output_path": j.get("output_path"),
                "started_at": j.get("started_at", ""),
                "updated_at": datetime.now().isoformat(),
            }
            disk.insert(0, _enrich_job_list_row(meta))
            seen.add(jid)
    disk.sort(key=lambda m: m.get("started_at", ""), reverse=True)
    return disk[:limit]
