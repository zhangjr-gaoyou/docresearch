"""Knowledge retrieval service: four-layer recall + RRF + LLM answer."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage

from app.core.settings import settings
from app.services.graph_store_neo4j import Neo4jGraphStore
from app.services.llm_factory import get_chat_openai
from app.services.rerank import rerank_documents
from app.services.retrieval import search_and_rerank

INDEX_FILE = settings.DATA_DIR / "knowledge_retrieval_index.json"


def _load_index() -> dict:
    if not INDEX_FILE.exists():
        return {"items": []}
    try:
        return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"items": []}


def _save_index(data: dict) -> None:
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _tokens(text: str) -> set[str]:
    raw = re.findall(r"[\u4e00-\u9fa5]{1,}|[A-Za-z0-9_]+", text or "")
    return {x.lower() for x in raw if x.strip()}


def _lex_score(query: str, text: str) -> float:
    q = _tokens(query)
    t = _tokens(text)
    if not q or not t:
        return 0.0
    hit = len(q & t)
    return hit / max(len(q), 1)


def _route_by_rule(query: str) -> str:
    q = (query or "").strip()
    if any(k in q for k in ("关系", "关联", "上级", "下游", "依赖", "谁和谁")):
        return "relation"
    if any(k in q for k in ("是什么", "多少", "参数", "定义", "步骤")):
        return "fact"
    if any(k in q for k in ("讲了什么", "概述", "概要", "总结")):
        return "summary"
    return "analysis"


def _route_by_llm(query: str, rule_route: str) -> str:
    route = rule_route if rule_route in {"summary", "fact", "relation", "analysis"} else "analysis"
    prompt = (
        "你是查询路由分类器。请将用户问题分类为以下四类之一："
        "summary/fact/relation/analysis。\n"
        "定义：\n"
        "- summary: 概括、总结、讲了什么。\n"
        "- fact: 具体事实、定义、参数、步骤。\n"
        "- relation: 实体关系、上下游、依赖、多跳关联。\n"
        "- analysis: 需要综合多个证据分析。\n"
        "请只输出严格 JSON：{\"route\":\"summary|fact|relation|analysis\"}。\n"
        f"规则分类结果: {route}\n"
        f"用户问题: {query}"
    )
    try:
        llm = get_chat_openai(temperature=0.0)
        text = str(llm.invoke([HumanMessage(content=prompt)]).content or "").strip()
        obj = json.loads(text)
        candidate = str(obj.get("route") or "").strip().lower()
        if candidate in {"summary", "fact", "relation", "analysis"}:
            return candidate
    except Exception:
        return route
    return route


def _weights(route: str) -> dict[str, float]:
    if route == "summary":
        return {"summary": 1.0, "structure": 0.7, "knowledge_point": 0.3, "graph_triple": 0.2}
    if route == "fact":
        return {"summary": 0.2, "structure": 0.3, "knowledge_point": 1.0, "graph_triple": 0.6}
    if route == "relation":
        return {"summary": 0.2, "structure": 0.2, "knowledge_point": 0.6, "graph_triple": 1.0}
    return {"summary": 0.6, "structure": 0.8, "knowledge_point": 0.9, "graph_triple": 0.7}


def build_collection_retrieval_index(
    *,
    collection_id: str,
    document_id: str,
    document_name: str,
    extracted: dict,
    document_text: str | None = None,
) -> None:
    """Build/update four-layer retrieval entries for one document."""
    data = _load_index()
    items = data.get("items", [])
    kept = [
        x
        for x in items
        if not (
            x.get("collection_id") == collection_id
            and x.get("document_id") == document_id
            and x.get("layer") in {"summary", "structure", "knowledge_point", "graph_triple"}
        )
    ]

    now = datetime.now().isoformat()
    summary = extracted.get("summary", {}) if isinstance(extracted.get("summary"), dict) else {}
    structure = extracted.get("structure", {}) if isinstance(extracted.get("structure"), dict) else {}
    points = extracted.get("key_points", {}) if isinstance(extracted.get("key_points"), dict) else {}
    graph = extracted.get("graph", {}) if isinstance(extracted.get("graph"), dict) else {}

    out: list[dict] = []
    out.append(
        {
            "id": f"{collection_id}:{document_id}:summary",
            "collection_id": collection_id,
            "document_id": document_id,
            "document_name": document_name,
            "layer": "summary",
            "content": str(summary.get("summary") or ""),
            "section_path": "文档概要",
            "metadata": {"title": summary.get("title"), "tags": summary.get("tags", [])},
            "updated_at": now,
        }
    )

    for i, s in enumerate((structure.get("sections") or [])):
        if not isinstance(s, dict):
            continue
        out.append(
            {
                "id": f"{collection_id}:{document_id}:structure:sec:{i}",
                "collection_id": collection_id,
                "document_id": document_id,
                "document_name": document_name,
                "layer": "structure",
                "content": str(s.get("summary") or ""),
                "section_path": str(s.get("name") or f"章节{i+1}"),
                "metadata": {"level": "section"},
                "updated_at": now,
            }
        )
    para_bodies: list[str] = []
    if isinstance(document_text, str) and document_text.strip():
        para_bodies = [x.strip() for x in re.split(r"\n\s*\n+", document_text) if x.strip()]
        if not para_bodies:
            para_bodies = [x.strip() for x in document_text.splitlines() if x.strip()]
        para_bodies = para_bodies[:256]

    for i, p in enumerate((structure.get("paragraph_notes") or [])):
        if not isinstance(p, dict):
            continue
        p_name = str(p.get("name") or f"段落{i+1}")
        p_summary = str(p.get("summary") or "")
        p_body = str(p.get("content") or p.get("text") or p.get("body") or "").strip()
        if not p_body and i < len(para_bodies):
            p_body = para_bodies[i]
        out.append(
            {
                "id": f"{collection_id}:{document_id}:structure:para:{i}",
                "collection_id": collection_id,
                "document_id": document_id,
                "document_name": document_name,
                "layer": "structure",
                "content": p_summary,
                "section_path": p_name,
                "metadata": {"level": "paragraph"},
                "updated_at": now,
            }
        )
        if p_body:
            out.append(
                {
                    "id": f"{collection_id}:{document_id}:structure:para_body:{i}",
                    "collection_id": collection_id,
                    "document_id": document_id,
                    "document_name": document_name,
                    "layer": "structure",
                    "content": p_body,
                    "section_path": f"{p_name}/正文",
                    "metadata": {"level": "paragraph_body"},
                    "updated_at": now,
                }
            )

    for i, kp in enumerate((points.get("points") or [])):
        if not isinstance(kp, dict):
            continue
        text = str(kp.get("point") or "")
        tags = kp.get("tags") or []
        out.append(
            {
                "id": f"{collection_id}:{document_id}:kp:{i}",
                "collection_id": collection_id,
                "document_id": document_id,
                "document_name": document_name,
                "layer": "knowledge_point",
                "content": text,
                "section_path": "",
                "metadata": {"tags": tags, "keywords": " ".join(tags)},
                "updated_at": now,
            }
        )

    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
    node_label = {str(n.get("id", "")): str(n.get("label") or n.get("id") or "") for n in nodes if isinstance(n, dict)}
    for i, e in enumerate(edges):
        if not isinstance(e, dict):
            continue
        s = str(e.get("source") or "")
        t = str(e.get("target") or "")
        if not s or not t:
            continue
        rel = str(e.get("relation") or "关联")
        triple_text = f"{node_label.get(s, s)} {rel} {node_label.get(t, t)}"
        out.append(
            {
                "id": f"{collection_id}:{document_id}:triple:{i}",
                "collection_id": collection_id,
                "document_id": document_id,
                "document_name": document_name,
                "layer": "graph_triple",
                "content": triple_text,
                "section_path": "图谱路径",
                "metadata": {"source": s, "target": t, "relation": rel},
                "updated_at": now,
            }
        )

    data["items"] = kept + out
    _save_index(data)


def _rrf_fuse(per_layer: dict[str, list[dict]], layer_weights: dict[str, float], k: int = 60) -> list[dict]:
    scores: dict[str, float] = defaultdict(float)
    rows: dict[str, dict] = {}
    for layer, items in per_layer.items():
        w = layer_weights.get(layer, 1.0)
        for rank, item in enumerate(items, 1):
            iid = str(item.get("id"))
            scores[iid] += w * (1.0 / (k + rank))
            rows[iid] = item
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    out = []
    for iid, sc in ranked:
        r = dict(rows[iid])
        r["rrf_score"] = sc
        out.append(r)
    return out


def _all_paragraph_bodies(candidates: list[dict]) -> list[dict]:
    out = []
    for x in candidates:
        meta = x.get("metadata") if isinstance(x.get("metadata"), dict) else {}
        if meta.get("level") == "paragraph_body":
            out.append(x)
    return out


def _doc_ids_from_fused(fused: list[dict]) -> set[str]:
    s: set[str] = set()
    for it in fused:
        did = it.get("document_id")
        if did:
            s.add(str(did))
    return s


def _filter_bodies_by_docs(bodies: list[dict], doc_ids: set[str]) -> list[dict]:
    if not doc_ids:
        return bodies
    return [b for b in bodies if str(b.get("document_id") or "") in doc_ids]


def _para_body_id_from_para_summary_id(item_id: str) -> str | None:
    if ":structure:para:" not in item_id or ":structure:para_body:" in item_id:
        return None
    return item_id.replace(":structure:para:", ":structure:para_body:")


def _apply_rerank_boost(
    *,
    subquery: str,
    sub_pool: list[dict],
    base_weight: float,
    para_scores: dict[str, float],
    para_evidence: dict[str, set[str]],
    layer_tag: str,
    top_n: int = 5,
) -> None:
    if not sub_pool or base_weight <= 0:
        return
    texts = [str(b.get("content", "")) for b in sub_pool]
    try:
        rr = rerank_documents(subquery, texts, top_n=min(top_n, len(texts)))
    except Exception:
        for i, b in enumerate(sub_pool[:top_n]):
            pid = str(b.get("id", ""))
            if not pid:
                continue
            rank_boost = base_weight / (1 + i)
            para_scores[pid] = max(para_scores.get(pid, 0.0), rank_boost)
            para_evidence.setdefault(pid, set()).add(layer_tag)
        return
    for rank, (_txt, rel_score, idx) in enumerate(rr, 1):
        if idx < 0 or idx >= len(sub_pool):
            continue
        row = sub_pool[idx]
        pid = str(row.get("id", ""))
        if not pid:
            continue
        try:
            rs = float(rel_score)
        except (TypeError, ValueError):
            rs = 1.0 / rank
        combined = base_weight * (0.35 + 0.65 * min(max(rs, 0.0), 1.0))
        para_scores[pid] = max(para_scores.get(pid, 0.0), combined)
        para_evidence.setdefault(pid, set()).add(layer_tag)


def _resolve_top_paragraphs(
    *,
    query: str,
    collection_id: str,
    fused: list[dict],
    all_candidates: list[dict],
    vector_chunks: list[dict],
    top_k: int,
    log,
) -> tuple[list[dict], dict[str, set[str]]]:
    """
    Turn multi-layer RRF hits + vector chunks into ranked paragraph_body (and optional vector-only) rows.
    Returns (ordered list of index rows for top_k display/LLM, para_id -> evidence layers).
    """
    bodies_all = _all_paragraph_bodies(all_candidates)
    doc_ids = _doc_ids_from_fused(fused)
    bodies = _filter_bodies_by_docs(bodies_all, doc_ids)
    if len(bodies) < max(top_k, 3) and bodies_all and doc_ids:
        bodies = bodies_all
    log(f"段落池：全文 {len(bodies_all)}，选用 {len(bodies)}（文档过滤 {len(doc_ids)} 个）。")

    para_scores: dict[str, float] = {}
    para_evidence: dict[str, set[str]] = defaultdict(set)
    body_by_id = {str(b.get("id")): b for b in bodies if b.get("id")}

    fused_for_analysis = fused[: max(top_k * 3, 12)]

    for item in fused_for_analysis:
        iid = str(item.get("id", ""))
        rrf = float(item.get("rrf_score", 0.0))
        layer = str(item.get("layer", ""))
        meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        level = meta.get("level")
        doc_id = str(item.get("document_id") or "")

        if level == "paragraph_body" and iid in body_by_id:
            para_scores[iid] = max(para_scores.get(iid, 0.0), rrf)
            para_evidence[iid].add(layer or "structure")
            continue

        alt = _para_body_id_from_para_summary_id(iid)
        if alt and alt in body_by_id:
            para_scores[alt] = max(para_scores.get(alt, 0.0), rrf * 0.95)
            para_evidence[alt].add(layer or "structure")
            continue

        hint = str(item.get("content", ""))[:500]
        subq = f"{query}\n相关线索：{hint}"
        sub_pool = _filter_bodies_by_docs(bodies, {doc_id}) if doc_id else bodies
        if not sub_pool:
            sub_pool = bodies[: min(80, len(bodies))]
        _apply_rerank_boost(
            subquery=subq,
            sub_pool=sub_pool,
            base_weight=rrf,
            para_scores=para_scores,
            para_evidence=para_evidence,
            layer_tag=layer,
            top_n=5,
        )

    vec_weight = 0.85
    for i, ch in enumerate(vector_chunks[: max(top_k * 2, 8)]):
        txt = str(ch.get("content", ""))[:2000]
        if not txt.strip():
            continue
        did = str(ch.get("document_id") or "")
        pseudo_rrf = vec_weight / (1 + i)
        subq = f"{query}\n向量片段：{txt[:400]}"
        sub_pool = _filter_bodies_by_docs(bodies, {did}) if did else bodies
        if not sub_pool:
            sub_pool = bodies[: min(60, len(bodies))]
        _apply_rerank_boost(
            subquery=subq,
            sub_pool=sub_pool,
            base_weight=pseudo_rrf,
            para_scores=para_scores,
            para_evidence=para_evidence,
            layer_tag="vector_chunk",
            top_n=4,
        )

    ranked_ids = sorted(para_scores.keys(), key=lambda x: para_scores[x], reverse=True)
    result_rows: list[dict] = []
    seen = set()
    for pid in ranked_ids:
        if pid in seen:
            continue
        row = body_by_id.get(pid)
        if row:
            seen.add(pid)
            r = dict(row)
            r["paragraph_score"] = para_scores[pid]
            r["evidence_layers"] = sorted(para_evidence.get(pid, set()))
            result_rows.append(r)
        if len(result_rows) >= top_k:
            break

    if len(result_rows) < top_k and bodies:
        try:
            texts = [str(b.get("content", "")) for b in bodies[: min(100, len(bodies))]]
            rr = rerank_documents(query, texts, top_n=min(top_k * 2, len(texts)))
            for _c, _s, idx in rr:
                if idx < 0 or idx >= len(bodies):
                    continue
                b = bodies[idx]
                pid = str(b.get("id", ""))
                if pid in seen:
                    continue
                r = dict(b)
                r["paragraph_score"] = float(para_scores.get(pid, 0.0) or _s)
                r["evidence_layers"] = sorted(para_evidence.get(pid, {"fallback_rerank"}))
                result_rows.append(r)
                seen.add(pid)
                if len(result_rows) >= top_k:
                    break
        except Exception:
            for b in bodies:
                pid = str(b.get("id", ""))
                if pid in seen:
                    continue
                r = dict(b)
                r["paragraph_score"] = float(para_scores.get(pid, 0.0))
                r["evidence_layers"] = sorted(para_evidence.get(pid, {"fallback_lex"}))
                result_rows.append(r)
                seen.add(pid)
                if len(result_rows) >= top_k:
                    break

    if len(result_rows) < top_k and vector_chunks:
        for i, ch in enumerate(vector_chunks):
            if len(result_rows) >= top_k:
                break
            did = str(ch.get("document_id") or "")
            meta = ch.get("metadata") if isinstance(ch.get("metadata"), dict) else {}
            synth = {
                "id": f"vector_only:{collection_id}:{did}:{i}",
                "collection_id": collection_id,
                "document_id": did or None,
                "document_name": "",
                "layer": "raw_chunk",
                "content": str(ch.get("content", "")),
                "section_path": "向量片段",
                "metadata": {**meta, "source": "vector_chunk", "level": "raw_chunk"},
                "paragraph_score": 0.55 / (1 + i),
                "evidence_layers": ["vector_chunk"],
            }
            result_rows.append(synth)

    return result_rows[:top_k], dict(para_evidence)


def _neo4j_relation_context(collection_id: str, query: str, limit: int = 8) -> list[dict]:
    store = Neo4jGraphStore()
    if not store.enabled():
        return []
    graph = store.read_graph(collection_id=collection_id, limit=500)
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    q = query.lower()
    matched_ids = {
        str(n.get("id"))
        for n in nodes
        if q in str(n.get("label", "")).lower() or q in str(n.get("id", "")).lower()
    }
    out = []
    for e in edges:
        s = str(e.get("source", ""))
        t = str(e.get("target", ""))
        if s in matched_ids or t in matched_ids:
            out.append(
                {
                    "id": f"neo4j:{s}:{e.get('relation')}:{t}",
                    "layer": "graph_triple",
                    "content": f"{s} {e.get('relation', '关联')} {t}",
                    "document_id": str(e.get("document_id", "")),
                    "document_name": "",
                    "section_path": "Neo4j子图",
                    "metadata": {"source": s, "target": t, "relation": e.get("relation", "关联")},
                }
            )
            if len(out) >= limit:
                break
    return out


def retrieve_and_answer(collection_id: str, query: str, top_k: int = 8, *, skip_llm: bool = False) -> dict:
    logs: list[dict[str, str]] = []

    def log(message: str, level: str = "info") -> None:
        logs.append({"time": datetime.now().isoformat(timespec="seconds"), "message": message, "level": level})

    log("开始知识检索。")
    idx = _load_index().get("items", [])
    candidates = [x for x in idx if x.get("collection_id") == collection_id]
    log(f"已加载索引，共 {len(candidates)} 条候选。")
    rule_route = _route_by_rule(query)
    if skip_llm:
        route = rule_route
        log(f"查询路由完成（仅规则）：{route}。")
    else:
        route = _route_by_llm(query, rule_route)
        log(f"查询路由完成：规则={rule_route}，LLM二阶段={route}。")
    layer_w = _weights(route)
    layer_rows: dict[str, list[dict]] = {"summary": [], "structure": [], "knowledge_point": [], "graph_triple": []}

    for layer in layer_rows:
        rows = [x for x in candidates if x.get("layer") == layer]
        rows.sort(key=lambda r: _lex_score(query, str(r.get("content", ""))), reverse=True)
        layer_rows[layer] = rows[: max(top_k * 3, 12)]
        log(f"层召回：{layer} 预召回 {len(layer_rows[layer])} 条。")

    # graph relation retrieval from neo4j as extra source
    neo4j_rows = _neo4j_relation_context(collection_id, query, limit=top_k)
    layer_rows["graph_triple"].extend(neo4j_rows)
    log(f"Neo4j 补充关系 {len(neo4j_rows)} 条。")

    # rerank within each layer
    for layer, rows in list(layer_rows.items()):
        docs = [str(r.get("content", "")) for r in rows]
        if not docs:
            log(f"层重排：{layer} 无候选，跳过。")
            continue
        try:
            rr = rerank_documents(query, docs, top_n=min(len(docs), max(top_k, 8)))
            layer_rows[layer] = [rows[idx] for _, _, idx in rr]
            log(f"层重排：{layer} 完成，保留 {len(layer_rows[layer])} 条。")
        except Exception:
            layer_rows[layer] = rows[:top_k]
            log(f"层重排：{layer} 失败，回退词法前 {len(layer_rows[layer])} 条。", level="warning")

    fused = _rrf_fuse(layer_rows, layer_w)[: max(top_k * 3, 12)]
    log(f"RRF 融合完成（分析用），候选 {len(fused)} 条。")

    vector_chunks: list[dict] = []
    try:
        vector_chunks = search_and_rerank(collection_id, query, top_k=max(top_k, 8))
        log(f"向量原文路：检索到 {len(vector_chunks)} 条 chunk。")
    except Exception as e:
        log(f"向量原文路失败：{e}", level="warning")

    top_paragraphs, _ = _resolve_top_paragraphs(
        query=query,
        collection_id=collection_id,
        fused=fused,
        all_candidates=candidates,
        vector_chunks=vector_chunks,
        top_k=top_k,
        log=log,
    )
    log(
        f"段落定位完成：Top-{min(top_k, len(top_paragraphs))} 段落/片段 "
        f"（共 {len(top_paragraphs)} 条用于总结）。"
    )
    if top_paragraphs:
        id_preview = ", ".join(str(p.get("id", ""))[:48] for p in top_paragraphs[:5])
        log(f"定位段落 id 预览：{id_preview}")

    fallback_fusion = False
    citations: list[dict] = []
    if top_paragraphs:
        for p in top_paragraphs:
            ev = p.get("evidence_layers")
            if not isinstance(ev, list):
                ev = list(ev) if ev else []
            meta = p.get("metadata") if isinstance(p.get("metadata"), dict) else {}
            citations.append(
                {
                    "layer": "paragraph",
                    "document_id": p.get("document_id"),
                    "document_name": p.get("document_name"),
                    "section_path": p.get("section_path"),
                    "score": float(p.get("paragraph_score", 0.0)),
                    "content": str(p.get("content", "")),
                    "metadata": {
                        **meta,
                        "id": p.get("id"),
                        "evidence_layers": ev,
                        "source_level": meta.get("level") or ("raw_chunk" if p.get("layer") == "raw_chunk" else "paragraph_body"),
                    },
                }
            )
        log(f"引用输出：以段落/向量片段为主，共 {len(citations)} 条。")
    else:
        fallback_fusion = True
        log("无可用段落正文，回退为 RRF 融合条目直接作答。", level="warning")
        citations = [
            {
                "layer": str(x.get("layer", "")),
                "document_id": x.get("document_id"),
                "document_name": x.get("document_name"),
                "section_path": x.get("section_path"),
                "score": float(x.get("rrf_score", 0.0)),
                "content": str(x.get("content", "")),
                "metadata": (
                    {
                        **(x.get("metadata") if isinstance(x.get("metadata"), dict) else {}),
                        "id": x.get("id"),
                        "evidence_layers": [str(x.get("layer", ""))],
                        "fallback": True,
                    }
                ),
            }
            for x in fused[:top_k]
        ]

    context_chunks = []
    for i, c in enumerate(citations, 1):
        context_chunks.append(
            f"[{i}] 文档={c.get('document_name') or c.get('document_id') or '-'} "
            f"位置={c.get('section_path') or '-'}\n{c['content']}"
        )
    context = "\n\n".join(context_chunks)
    if fallback_fusion:
        prompt = (
            "你是知识检索问答助手。当前缺少段落级原文，下列证据来自多路检索融合（概要/结构化/知识点/图谱等）。"
            "请尽量基于证据回答，并在答案末尾给出引用编号。\n\n"
            f"问题：{query}\n\n证据：\n{context}\n\n"
            "输出要求：\n1) 直接回答\n2) 若证据不足，明确写“证据不足”\n3) 结尾添加“引用: [1][2]...”。"
        )
    else:
        prompt = (
            "你是知识检索问答助手。下列内容是已定位的 Top-K 文章段落或向量检索原文片段，"
            "请**仅依据**这些段落作答，不要引入段落以外的推断；并在答案末尾用引用编号对应段落序号 [1][2]…\n\n"
            f"问题：{query}\n\n段落证据：\n{context}\n\n"
            "输出要求：\n1) 直接回答\n2) 若段落不足以回答，明确写“证据不足”\n3) 结尾添加“引用: [1][2]...”。"
        )
    answer = ""
    if skip_llm:
        log("已跳过 LLM 回答生成（仅检索证据）。")
    else:
        try:
            llm = get_chat_openai(temperature=0.1)
            answer = str(llm.invoke([HumanMessage(content=prompt)]).content or "").strip()
            log("答案生成完成。")
        except Exception:
            answer = "证据已检索完成，但回答生成失败。请检查 LLM 配置。"
            log("答案生成失败，已返回兜底信息。", level="warning")

    return {
        "answer": answer,
        "route": route,
        "citations": citations,
        "retrieved_chunks": fused[: top_k * 2],
        "logs": logs,
    }
