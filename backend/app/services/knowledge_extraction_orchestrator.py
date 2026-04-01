"""Async knowledge extraction orchestrator."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from typing import Callable, Optional

from app.services.collection_store import get_collection
from app.services.research.tools import list_collection_document_files, read_collection_document_text
from app.services.knowledge_extraction_agent import extract_document_knowledge
from app.services.knowledge_store import (
    create_result_item,
    bulk_replace_collection_document_items,
    write_job_logs,
    write_job_meta,
    read_job_logs,
    read_job_meta,
    list_jobs as list_jobs_from_disk,
)
from app.services.graph_store_neo4j import Neo4jGraphStore
from app.services.knowledge_retrieval_service import build_collection_retrieval_index

_jobs: dict[str, dict] = {}


def _add_log(logs: list, message: str, level: str = "info", **extra):
    logs.append(
        {
            "time": datetime.now().strftime("%H:%M:%S"),
            "message": message,
            "level": level,
            **extra,
        }
    )


class _PersistingLogList(list):
    def __init__(self, job_id: str, on_append: Optional[Callable[[dict], None]] = None):
        super().__init__()
        self.job_id = job_id
        self.on_append = on_append or (lambda _: None)

    def append(self, item):
        super().append(item)
        self.on_append(item)
        write_job_logs(self.job_id, list(self))


def _flush_meta(job_id: str, job: dict) -> None:
    write_job_meta(
        job_id,
        {
            "job_id": job_id,
            "collection_id": job.get("collection_id"),
            "status": job.get("status"),
            "progress": job.get("progress", ""),
            "started_at": job.get("started_at"),
            "updated_at": datetime.now().isoformat(),
        },
    )


def _result_items_from_doc(collection_id: str, document_id: str, document_name: str, extracted: dict) -> list[dict]:
    summary = extracted.get("summary", {})
    structure = extracted.get("structure", {})
    points = extracted.get("key_points", {})
    domain = extracted.get("domain", {})
    ontology = extracted.get("ontology", {})

    items = []
    items.append(
        {
            "collection_id": collection_id,
            "document_id": document_id,
            "document_name": document_name,
            "result_type": "summary",
            "title": str(summary.get("title") or "文档概要"),
            "content": str(summary.get("summary") or ""),
            "tags": list(summary.get("tags") or []),
            "extra": {"raw": summary, "domain": domain, "ontology": ontology},
        }
    )
    items.append(
        {
            "collection_id": collection_id,
            "document_id": document_id,
            "document_name": document_name,
            "result_type": "structure",
            "title": str(structure.get("title") or "文档结构"),
            "content": json.dumps(structure, ensure_ascii=False),
            "tags": ["结构化"],
            "extra": {"raw": structure, "domain": domain},
        }
    )
    for p in (points.get("points") or []):
        items.append(
            {
                "collection_id": collection_id,
                "document_id": document_id,
                "document_name": document_name,
                "result_type": "knowledge_point",
                "title": str(p.get("point") or "知识点"),
                "content": str(p.get("point") or ""),
                "tags": list(p.get("tags") or []),
                "extra": {"raw": p},
            }
        )
    return items


def _worker(job_id: str) -> None:
    job = _jobs.get(job_id)
    if not job:
        return
    coll_id = job["collection_id"]
    logs = job["logs"]
    graph_store = Neo4jGraphStore()
    cancel_event = job.get("cancel_event")
    try:
        files = list_collection_document_files(coll_id)
        _add_log(logs, f"开始知识提取，文档数：{len(files)}")
        _flush_meta(job_id, job)
        for i, fp in enumerate(files, 1):
            if isinstance(cancel_event, threading.Event) and cancel_event.is_set():
                raise RuntimeError("__knowledge_job_cancelled__")
            doc_key = fp.stem
            doc_name = fp.name
            _add_log(logs, f"[{i}/{len(files)}] 读取文档", document=doc_name, step="read")
            txt = read_collection_document_text(fp)
            _add_log(logs, f"[{i}/{len(files)}] 执行知识提取", document=doc_name, step="extract")
            extracted = extract_document_knowledge(job["topic"], txt)
            domain = extracted.get("domain", {}) if isinstance(extracted.get("domain"), dict) else {}
            ontology = extracted.get("ontology", {}) if isinstance(extracted.get("ontology"), dict) else {}
            graph_metrics = extracted.get("graph_metrics", {}) if isinstance(extracted.get("graph_metrics"), dict) else {}
            structure_obj = extracted.get("structure", {}) if isinstance(extracted.get("structure"), dict) else {}
            structure_metrics = (
                structure_obj.get("structure_metrics", {})
                if isinstance(structure_obj.get("structure_metrics"), dict)
                else {}
            )
            _add_log(
                logs,
                f"[{i}/{len(files)}] 业务领域识别：{domain.get('domain', 'unknown')}",
                document=doc_name,
                step="domain",
            )
            _add_log(
                logs,
                f"[{i}/{len(files)}] 领域本体生成：实体类型{len(ontology.get('entity_types') or [])}，谓语{len(ontology.get('predicates') or [])}",
                document=doc_name,
                step="ontology",
            )
            _add_log(
                logs,
                (
                    f"[{i}/{len(files)}] 本体约束映射："
                    f"关系映射{int(graph_metrics.get('edge_relation_mapped', 0))}，"
                    f"类型降级{int(graph_metrics.get('node_type_downgraded', 0))}，"
                    f"弃边{int(graph_metrics.get('edges_dropped', 0))}"
                ),
                document=doc_name,
                step="graph_constraint",
            )
            _add_log(
                logs,
                (
                    f"[{i}/{len(files)}] 结构关系修复："
                    f"section_ref_invalid={int(structure_metrics.get('invalid_section_ref_count', 0))}，"
                    f"paragraph_relinked={int(structure_metrics.get('auto_relinked_count', 0))}，"
                    f"unmatched_paragraph={int(structure_metrics.get('unmatched_paragraph_count', 0))}"
                ),
                document=doc_name,
                step="structure_relation",
            )
            _add_log(
                logs,
                (
                    f"[{i}/{len(files)}] 图谱质量指标："
                    f"对齐率{float(graph_metrics.get('align_rate', 0.0)):.2f}，"
                    f"降级率{float(graph_metrics.get('node_type_downgraded', 0))/max(int(graph_metrics.get('entity_count', 0)), 1):.2f}，"
                    f"弃边率{float(graph_metrics.get('drop_rate', 0.0)):.2f}，"
                    f"实体归一{int(graph_metrics.get('canonical_entity_merge_count', 0))}，"
                    f"扩展建议{int(graph_metrics.get('schema_proposals', 0))}"
                ),
                document=doc_name,
                step="graph_quality",
            )
            new_items = [create_result_item(x) for x in _result_items_from_doc(coll_id, doc_key, doc_name, extracted)]
            # ensure dedupe by replacing then re-create ids for this run
            bulk_replace_collection_document_items(
                collection_id=coll_id,
                document_id=doc_key,
                new_items=new_items,
            )
            graph = extracted.get("graph", {}) or {}
            nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
            edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
            if graph_store.enabled():
                graph_store.upsert_graph(
                    collection_id=coll_id,
                    document_id=doc_key,
                    nodes=nodes,
                    edges=edges,
                )
            build_collection_retrieval_index(
                collection_id=coll_id,
                document_id=doc_key,
                document_name=doc_name,
                extracted=extracted,
                document_text=txt,
            )
            _add_log(
                logs,
                f"[{i}/{len(files)}] 完成：summary/structure/knowledge_points/graph",
                document=doc_name,
                step="done",
            )
            job["progress"] = f"{i}/{len(files)}"
            _flush_meta(job_id, job)
        job["status"] = "completed"
        job["progress"] = "completed"
        _add_log(logs, "知识提取完成", level="success")
    except Exception as e:
        if str(e) == "__knowledge_job_cancelled__":
            job["status"] = "cancelled"
            job["progress"] = "用户已中止，未执行的文档不再处理"
            _add_log(logs, "知识提取已中止", level="warning")
        else:
            job["status"] = "failed"
            job["progress"] = str(e)
            _add_log(logs, f"知识提取失败：{e}", level="error")
    finally:
        _flush_meta(job_id, job)


def run_knowledge_job(collection_id: str, topic: str, on_log: Optional[Callable[[dict], None]] = None) -> str:
    coll = get_collection(collection_id)
    if not coll:
        raise ValueError("Collection not found")
    job_id = str(uuid.uuid4())
    logs = _PersistingLogList(job_id, on_append=on_log)
    job = {
        "job_id": job_id,
        "collection_id": collection_id,
        "status": "running",
        "progress": "starting",
        "topic": topic or coll.get("name") or "知识提取",
        "logs": logs,
        "started_at": datetime.now().isoformat(),
        "cancel_event": threading.Event(),
    }
    _jobs[job_id] = job
    _flush_meta(job_id, job)
    t = threading.Thread(target=_worker, args=(job_id,), daemon=True)
    t.start()
    return job_id


def get_job(job_id: str) -> Optional[dict]:
    if job_id in _jobs:
        j = _jobs[job_id]
        return {
            "job_id": j["job_id"],
            "collection_id": j["collection_id"],
            "status": j["status"],
            "progress": j.get("progress"),
            "logs": list(j.get("logs", [])),
            "started_at": j.get("started_at"),
            "updated_at": datetime.now().isoformat(),
        }
    meta = read_job_meta(job_id)
    if not meta:
        return None
    return {
        "job_id": meta.get("job_id", job_id),
        "collection_id": meta.get("collection_id", ""),
        "status": meta.get("status", "unknown"),
        "progress": meta.get("progress", ""),
        "logs": read_job_logs(job_id),
        "started_at": meta.get("started_at"),
        "updated_at": meta.get("updated_at"),
    }


def list_jobs(limit: int = 50) -> list[dict]:
    rows = list_jobs_from_disk(limit=limit * 2)
    seen = {x.get("job_id") for x in rows}
    for jid, j in _jobs.items():
        if jid in seen:
            continue
        rows.append(
            {
                "job_id": jid,
                "collection_id": j.get("collection_id", ""),
                "status": j.get("status", "running"),
                "progress": j.get("progress", ""),
                "started_at": j.get("started_at", ""),
                "updated_at": datetime.now().isoformat(),
            }
        )
    rows.sort(key=lambda x: x.get("started_at", ""), reverse=True)
    return rows[:limit]


def request_cancel_knowledge_job(job_id: str) -> tuple[bool, str]:
    """Signal a running in-memory knowledge job to stop after current boundary."""
    job = _jobs.get(job_id)
    if not job:
        return False, "job_not_found"
    if job.get("status") != "running":
        return False, "not_running"
    ev = job.get("cancel_event")
    if isinstance(ev, threading.Event):
        ev.set()
    return True, "ok"
