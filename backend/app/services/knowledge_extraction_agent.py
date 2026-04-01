"""Knowledge extraction logic for one document."""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage

from app.services.llm_factory import get_chat_openai
from app.services.prompt_registry import get_prompt


def _parse_json_object(text: str) -> dict[str, Any]:
    txt = (text or "").strip()
    if "```" in txt:
        parts = txt.split("```")
        if len(parts) >= 2:
            txt = parts[1]
            if txt.startswith("json"):
                txt = txt[4:]
            txt = txt.strip()
    try:
        return json.loads(txt)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", txt)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return {}


def _fallback_summary(content: str) -> dict:
    text = (content or "").strip()
    head = text[:500]
    return {"title": "文档概要", "summary": head if head else "文档未提及", "tags": ["自动提取"]}


def _fallback_structure(content: str) -> dict:
    lines = [x.strip() for x in (content or "").splitlines() if x.strip()]
    sections = []
    for i, ln in enumerate(lines[:12], 1):
        sections.append({"name": f"段落{i}", "summary": ln[:120], "content": ln[:400]})
    return {"title": "文档结构", "sections": sections, "paragraph_notes": sections[:8]}


def _fallback_points(content: str) -> dict:
    text = (content or "").strip()
    pts = []
    for i, chunk in enumerate([text[j : j + 120] for j in range(0, min(len(text), 480), 120)], 1):
        if chunk.strip():
            pts.append({"point": chunk.strip(), "tags": ["待确认"]})
    return {"title": "知识点", "points": pts[:8]}


def _fallback_graph(points: list[dict]) -> dict:
    nodes = []
    edges = []
    for i, p in enumerate(points[:10], 1):
        nid = f"kp_{i}"
        nodes.append({"id": nid, "label": str(p.get("point", ""))[:60], "type": "KnowledgePoint"})
        if i > 1:
            edges.append({"source": f"kp_{i-1}", "target": nid, "relation": "RELATED_TO"})
    return {"title": "知识图谱", "nodes": nodes, "edges": edges}


def _fallback_domain(summary: dict) -> dict:
    txt = str(summary.get("summary") or "")
    domain = "通用业务"
    if any(k in txt for k in ("医疗", "医院", "药", "诊疗")):
        domain = "医疗健康"
    elif any(k in txt for k in ("金融", "银行", "证券", "保险", "基金")):
        domain = "金融服务"
    elif any(k in txt for k in ("制造", "供应链", "工厂", "设备")):
        domain = "制造业"
    elif any(k in txt for k in ("电商", "零售", "平台", "订单")):
        domain = "零售电商"
    return {"domain": domain, "description": "基于概要自动识别", "confidence": 0.4}


def _fallback_ontology(domain: dict) -> dict:
    d = str(domain.get("domain") or "通用业务")
    if d == "医疗健康":
        return {
            "entity_types": ["患者", "医生", "医院", "疾病", "药物", "检查项"],
            "predicates": ["诊断为", "治疗于", "开具", "并发", "检查结果"],
            "notes": "医疗默认本体",
        }
    if d == "金融服务":
        return {
            "entity_types": ["客户", "账户", "产品", "机构", "交易", "风险事件"],
            "predicates": ["开通", "购买", "发生于", "关联", "评级为"],
            "notes": "金融默认本体",
        }
    return {
        "entity_types": ["主体", "对象", "事件", "时间", "地点"],
        "predicates": ["属于", "关联", "发生于", "影响", "依赖"],
        "notes": "通用默认本体",
    }


def _normalize_graph_result(raw_graph: dict) -> dict:
    """Accept nodes/edges or entities/relationships and normalize to nodes/edges."""
    if not isinstance(raw_graph, dict):
        return {"title": "知识图谱", "nodes": [], "edges": []}
    nodes = raw_graph.get("nodes")
    edges = raw_graph.get("edges")
    if isinstance(nodes, list) and isinstance(edges, list):
        return {
            "title": str(raw_graph.get("title") or "知识图谱"),
            "nodes": nodes,
            "edges": edges,
        }

    entities = raw_graph.get("entities")
    relationships = raw_graph.get("relationships")
    if not isinstance(entities, list):
        entities = []
    if not isinstance(relationships, list):
        relationships = []

    out_nodes = []
    for e in entities:
        if not isinstance(e, dict):
            continue
        eid = str(e.get("id") or e.get("name") or "").strip()
        if not eid:
            continue
        out_nodes.append(
            {
                "id": eid,
                "label": str(e.get("label") or eid),
                "type": str(e.get("type") or "Entity"),
                "attributes": e.get("attributes") if isinstance(e.get("attributes"), dict) else {},
            }
        )

    out_edges = []
    for r in relationships:
        if not isinstance(r, dict):
            continue
        src = str(r.get("source") or r.get("subject") or "").strip()
        tgt = str(r.get("target") or r.get("object") or "").strip()
        rel = str(r.get("relation") or r.get("predicate") or "RELATED_TO").strip()
        if not src or not tgt:
            continue
        out_edges.append({"source": src, "target": tgt, "relation": rel})

    return {
        "title": str(raw_graph.get("title") or "知识图谱"),
        "nodes": out_nodes,
        "edges": out_edges,
    }


def _safe_float(v: Any, default: float = 0.5) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, f))


def _fallback_graph_candidates(points: list[dict], ontology: dict) -> dict:
    etypes = [str(x) for x in (ontology.get("entity_types") or []) if str(x).strip()]
    preds = [str(x) for x in (ontology.get("predicates") or []) if str(x).strip()]
    default_type = etypes[0] if etypes else "Entity"
    default_rel = preds[0] if preds else "RELATED_TO"
    entities = []
    relations = []
    for i, p in enumerate(points[:12], 1):
        text = str((p or {}).get("point") or "").strip()
        if not text:
            continue
        eid = f"kp_{i}"
        entities.append(
            {
                "id": eid,
                "label": text[:48],
                "type": default_type,
                "confidence": 0.55,
                "source_spans": [{"text": text[:160], "start": -1, "end": -1}],
            }
        )
        if i > 1:
            relations.append(
                {
                    "source": f"kp_{i-1}",
                    "target": eid,
                    "relation": default_rel,
                    "confidence": 0.5,
                    "evidence_text": text[:160],
                    "evidence_span": {"start": -1, "end": -1},
                }
            )
    return {"title": "知识图谱候选", "entities": entities, "relationships": relations}


def _fallback_schema_align(candidates: dict, ontology: dict) -> dict:
    ents = candidates.get("entities") if isinstance(candidates.get("entities"), list) else []
    rels = candidates.get("relationships") if isinstance(candidates.get("relationships"), list) else []
    allowed_types = {str(x).strip() for x in (ontology.get("entity_types") or []) if str(x).strip()}
    allowed_predicates = {str(x).strip() for x in (ontology.get("predicates") or []) if str(x).strip()}
    out_nodes = []
    for e in ents:
        if not isinstance(e, dict):
            continue
        et = str(e.get("type") or "Entity")
        mapped = et if et in allowed_types or not allowed_types else "Entity"
        out_nodes.append(
            {
                "id": str(e.get("id") or e.get("label") or "").strip(),
                "label": str(e.get("label") or e.get("id") or ""),
                "type": mapped,
                "original_type": et,
                "align_reason": "matched" if mapped == et else "type_not_in_ontology",
                "confidence": _safe_float(e.get("confidence"), 0.5),
                "source_spans": e.get("source_spans") if isinstance(e.get("source_spans"), list) else [],
                "aliases": e.get("aliases") if isinstance(e.get("aliases"), list) else [],
            }
        )
    valid_ids = {str(x.get("id")) for x in out_nodes if isinstance(x, dict) and str(x.get("id") or "")}
    out_edges = []
    for r in rels:
        if not isinstance(r, dict):
            continue
        src = str(r.get("source") or "").strip()
        tgt = str(r.get("target") or "").strip()
        if not src or not tgt or src not in valid_ids or tgt not in valid_ids:
            continue
        rel = str(r.get("relation") or "RELATED_TO").strip()
        mapped_rel = rel if rel in allowed_predicates or not allowed_predicates else "RELATED_TO"
        out_edges.append(
            {
                "source": src,
                "target": tgt,
                "relation": mapped_rel,
                "original_relation": rel,
                "align_reason": "matched" if mapped_rel == rel else "predicate_not_in_ontology",
                "confidence": _safe_float(r.get("confidence"), 0.5),
                "evidence_text": str(r.get("evidence_text") or ""),
                "evidence_span": r.get("evidence_span") if isinstance(r.get("evidence_span"), dict) else {},
            }
        )
    return {"title": "知识图谱对齐", "nodes": out_nodes, "edges": out_edges, "schema_proposals": []}


def _fallback_entity_resolve(aligned: dict) -> dict:
    nodes = aligned.get("nodes") if isinstance(aligned.get("nodes"), list) else []
    mapping: dict[str, str] = {}
    by_norm: dict[str, str] = {}
    merged_aliases = 0
    for n in nodes:
        if not isinstance(n, dict):
            continue
        nid = str(n.get("id") or "").strip()
        label = str(n.get("label") or nid).strip()
        if not nid:
            continue
        norm = re.sub(r"\s+", "", label.lower())
        if norm in by_norm:
            mapping[nid] = by_norm[norm]
            merged_aliases += 1
        else:
            by_norm[norm] = nid
            mapping[nid] = nid
    return {"canonical_map": mapping, "merged_aliases": merged_aliases}


def _apply_entity_resolution(aligned: dict, resolve: dict) -> dict:
    nodes = aligned.get("nodes") if isinstance(aligned.get("nodes"), list) else []
    edges = aligned.get("edges") if isinstance(aligned.get("edges"), list) else []
    cmap = resolve.get("canonical_map") if isinstance(resolve.get("canonical_map"), dict) else {}
    merged_aliases = int(resolve.get("merged_aliases") or 0)
    canonical_nodes: dict[str, dict] = {}
    for n in nodes:
        if not isinstance(n, dict):
            continue
        old_id = str(n.get("id") or "").strip()
        if not old_id:
            continue
        cid = str(cmap.get(old_id) or old_id)
        row = dict(n)
        row["id"] = cid
        row_aliases = row.get("aliases")
        aliases = row_aliases if isinstance(row_aliases, list) else []
        if old_id != cid and old_id not in aliases:
            aliases.append(old_id)
        row["aliases"] = aliases
        if cid not in canonical_nodes:
            canonical_nodes[cid] = row
        else:
            ex = canonical_nodes[cid]
            ex_aliases = ex.get("aliases")
            ex_aliases = ex_aliases if isinstance(ex_aliases, list) else []
            for a in aliases:
                if a not in ex_aliases:
                    ex_aliases.append(a)
            ex["aliases"] = ex_aliases
            ex["confidence"] = max(_safe_float(ex.get("confidence"), 0.5), _safe_float(row.get("confidence"), 0.5))
            spans = ex.get("source_spans") if isinstance(ex.get("source_spans"), list) else []
            for sp in (row.get("source_spans") if isinstance(row.get("source_spans"), list) else []):
                spans.append(sp)
            ex["source_spans"] = spans
    out_edges = []
    for e in edges:
        if not isinstance(e, dict):
            continue
        src = str(cmap.get(str(e.get("source") or ""), str(e.get("source") or "")))
        tgt = str(cmap.get(str(e.get("target") or ""), str(e.get("target") or "")))
        if not src or not tgt:
            continue
        row = dict(e)
        row["source"] = src
        row["target"] = tgt
        out_edges.append(row)
    return {"title": aligned.get("title", "知识图谱"), "nodes": list(canonical_nodes.values()), "edges": out_edges, "merged_aliases": merged_aliases}


def _apply_ontology_constraints(graph: dict, ontology: dict) -> tuple[dict, dict]:
    """Constrain node types / predicates with explainable alignment and drop stats."""
    allowed_types = {
        str(x).strip()
        for x in (ontology.get("entity_types") or [])
        if str(x).strip()
    }
    allowed_predicates = {
        str(x).strip()
        for x in (ontology.get("predicates") or [])
        if str(x).strip()
    }
    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
    metrics = {
        "node_type_downgraded": 0,
        "edge_relation_mapped": 0,
        "edges_dropped": 0,
        "edge_total_before": len(edges),
        "edge_total_after": 0,
        "allowed_entity_types": len(allowed_types),
        "allowed_predicates": len(allowed_predicates),
    }

    if allowed_types:
        for n in nodes:
            if not isinstance(n, dict):
                continue
            cur_type = str(n.get("type") or "").strip()
            if cur_type and cur_type in allowed_types:
                continue
            if cur_type:
                attrs = n.get("attributes")
                if not isinstance(attrs, dict):
                    attrs = {}
                attrs["original_type"] = cur_type
                n["attributes"] = attrs
            n["type"] = "Entity"
            n["align_reason"] = "type_not_in_ontology"
            metrics["node_type_downgraded"] += 1
        else:
            if not n.get("align_reason"):
                n["align_reason"] = "matched"
        if n.get("confidence") is None:
            n["confidence"] = 0.7

    valid_ids = {str(n.get("id") or "") for n in nodes if isinstance(n, dict) and str(n.get("id") or "")}
    filtered_edges = []
    if allowed_predicates:
        for e in edges:
            if not isinstance(e, dict):
                continue
            src = str(e.get("source") or "").strip()
            tgt = str(e.get("target") or "").strip()
            if not src or not tgt or src not in valid_ids or tgt not in valid_ids:
                metrics["edges_dropped"] += 1
                continue
            cur_rel = str(e.get("relation") or "").strip()
            if cur_rel and cur_rel in allowed_predicates:
                if not e.get("align_reason"):
                    e["align_reason"] = "matched"
            else:
                if cur_rel:
                    e["original_relation"] = cur_rel
                e["relation"] = "RELATED_TO"
                e["align_reason"] = "predicate_not_in_ontology"
                metrics["edge_relation_mapped"] += 1
            if e.get("confidence") is None:
                e["confidence"] = 0.6
            if e.get("evidence_text") is None:
                e["evidence_text"] = ""
            if not isinstance(e.get("evidence_span"), dict):
                e["evidence_span"] = {}
            filtered_edges.append(e)
    else:
        for e in edges:
            if not isinstance(e, dict):
                continue
            src = str(e.get("source") or "").strip()
            tgt = str(e.get("target") or "").strip()
            if not src or not tgt or src not in valid_ids or tgt not in valid_ids:
                metrics["edges_dropped"] += 1
                continue
            if e.get("confidence") is None:
                e["confidence"] = 0.6
            if e.get("evidence_text") is None:
                e["evidence_text"] = ""
            if not isinstance(e.get("evidence_span"), dict):
                e["evidence_span"] = {}
            if not e.get("align_reason"):
                e["align_reason"] = "matched"
            filtered_edges.append(e)

    metrics["edge_total_after"] = len(filtered_edges)
    metrics["align_rate"] = round(
        (metrics["edge_total_after"] - metrics["edge_relation_mapped"]) / max(metrics["edge_total_after"], 1),
        4,
    )
    metrics["drop_rate"] = round(metrics["edges_dropped"] / max(metrics["edge_total_before"], 1), 4)
    return {"title": graph.get("title", "知识图谱"), "nodes": nodes, "edges": filtered_edges}, metrics


def _extract_paragraph_bodies(doc_text: str, limit: int = 128) -> list[str]:
    txt = (doc_text or "").strip()
    if not txt:
        return []
    blocks = [x.strip() for x in re.split(r"\n\s*\n+", txt) if x.strip()]
    if not blocks:
        blocks = [x.strip() for x in txt.splitlines() if x.strip()]
    out: list[str] = []
    for b in blocks:
        if len(b) > 1200:
            out.append(b[:1200])
        else:
            out.append(b)
        if len(out) >= limit:
            break
    return out


def _enrich_structure_with_paragraph_body(structure: dict, doc_text: str) -> dict:
    if not isinstance(structure, dict):
        return {"title": "文档结构", "sections": [], "paragraph_notes": []}
    out = dict(structure)
    notes = out.get("paragraph_notes")
    if not isinstance(notes, list):
        return out
    para_bodies = _extract_paragraph_bodies(doc_text)
    enriched: list[dict[str, Any]] = []
    for i, p in enumerate(notes):
        row = dict(p) if isinstance(p, dict) else {"name": f"段落{i+1}", "summary": str(p)}
        body = str(row.get("content") or row.get("text") or row.get("body") or "").strip()
        if not body and i < len(para_bodies):
            body = para_bodies[i]
        if body:
            row["content"] = body
        enriched.append(row)
    out["paragraph_notes"] = enriched
    return out


def _normalize_structure_output(structure: dict, doc_text: str) -> dict:
    """
    Normalize structure output to ensure paragraph_notes has:
    - name
    - summary
    - content (preferred from model output, fallback from raw text blocks)
    """
    if not isinstance(structure, dict):
        return {"title": "文档结构", "sections": [], "paragraph_notes": []}

    out = dict(structure)
    sections = out.get("sections")
    notes = out.get("paragraph_notes")
    if not isinstance(sections, list):
        sections = []
    if not isinstance(notes, list):
        notes = []

    normalized_sections: list[dict[str, Any]] = []
    section_ids: list[str] = []
    for i, s in enumerate(sections):
        row = dict(s) if isinstance(s, dict) else {"name": f"章节{i+1}", "summary": str(s)}
        sid = str(row.get("id") or "").strip() or f"sec_{i+1}"
        row["id"] = sid
        if not row.get("name"):
            row["name"] = f"章节{i+1}"
        if row.get("summary") is None:
            row["summary"] = ""
        normalized_sections.append(row)
        section_ids.append(sid)

    normalized_notes: list[dict[str, Any]] = []
    invalid_section_ref_count = 0
    auto_relinked_count = 0
    unmatched_paragraph_count = 0
    for i, p in enumerate(notes):
        row = dict(p) if isinstance(p, dict) else {"name": f"段落{i+1}", "summary": str(p)}
        if not row.get("name"):
            row["name"] = f"段落{i+1}"
        if row.get("summary") is None:
            row["summary"] = ""

        # Accept common aliases when model returns varied field names.
        content = str(
            row.get("content")
            or row.get("paragraph_content")
            or row.get("text")
            or row.get("body")
            or ""
        ).strip()
        if content:
            row["content"] = content

        raw_ref = str(row.get("section_ref") or "").strip()
        if raw_ref and raw_ref in section_ids:
            row["section_ref"] = raw_ref
        else:
            if raw_ref:
                invalid_section_ref_count += 1
            if section_ids:
                # fallback: attach paragraph to nearest section by order.
                idx = min(i, len(section_ids) - 1)
                row["section_ref"] = section_ids[idx]
                row["relation_fix_reason"] = "auto_relinked_by_order"
                auto_relinked_count += 1
            else:
                row["section_ref"] = "unmatched"
                row["relation_fix_reason"] = "no_sections"
                unmatched_paragraph_count += 1
        normalized_notes.append(row)

    out["sections"] = normalized_sections
    out["paragraph_notes"] = normalized_notes
    out["structure_metrics"] = {
        "section_count": len(normalized_sections),
        "paragraph_count": len(normalized_notes),
        "invalid_section_ref_count": invalid_section_ref_count,
        "auto_relinked_count": auto_relinked_count,
        "unmatched_paragraph_count": unmatched_paragraph_count,
    }
    return _enrich_structure_with_paragraph_body(out, doc_text)


def extract_document_knowledge(topic: str, doc_text: str) -> dict:
    llm = get_chat_openai(temperature=0)
    base_doc = doc_text[:12000]

    summary_prompt = get_prompt("knowledge.extract.summary", topic=topic, document_text=base_doc)
    structure_prompt = get_prompt("knowledge.extract.structure", topic=topic, document_text=base_doc)
    points_prompt = get_prompt("knowledge.extract.key_points", topic=topic, document_text=base_doc)

    summary_raw = (llm.invoke([HumanMessage(content=summary_prompt)]).content or "").strip()
    structure_raw = (llm.invoke([HumanMessage(content=structure_prompt)]).content or "").strip()
    points_raw = (llm.invoke([HumanMessage(content=points_prompt)]).content or "").strip()

    summary = _parse_json_object(summary_raw) or _fallback_summary(base_doc)
    structure = _parse_json_object(structure_raw) or _fallback_structure(base_doc)
    structure = _normalize_structure_output(structure, doc_text)
    points = _parse_json_object(points_raw) or _fallback_points(base_doc)

    domain_prompt = get_prompt(
        "knowledge.extract.domain",
        topic=topic,
        summary_json=json.dumps(summary, ensure_ascii=False),
        document_text=base_doc,
    )
    domain_raw = (llm.invoke([HumanMessage(content=domain_prompt)]).content or "").strip()
    domain = _parse_json_object(domain_raw) or _fallback_domain(summary)

    ontology_prompt = get_prompt(
        "knowledge.extract.ontology",
        topic=topic,
        domain_json=json.dumps(domain, ensure_ascii=False),
        summary_json=json.dumps(summary, ensure_ascii=False),
        document_text=base_doc,
    )
    ontology_raw = (llm.invoke([HumanMessage(content=ontology_prompt)]).content or "").strip()
    ontology = _parse_json_object(ontology_raw) or _fallback_ontology(domain)

    points_items = points.get("points") if isinstance(points.get("points"), list) else []

    graph_candidates_prompt = get_prompt(
        "knowledge.extract.graph_candidates",
        topic=topic,
        domain_json=json.dumps(domain, ensure_ascii=False),
        ontology_json=json.dumps(ontology, ensure_ascii=False),
        summary_json=json.dumps(summary, ensure_ascii=False),
        document_text=base_doc,
        points_json=json.dumps(points_items, ensure_ascii=False),
    )
    graph_candidates_raw = (llm.invoke([HumanMessage(content=graph_candidates_prompt)]).content or "").strip()
    graph_candidates = _parse_json_object(graph_candidates_raw) or _fallback_graph_candidates(points_items, ontology)

    schema_align_prompt = get_prompt(
        "knowledge.extract.schema_align",
        topic=topic,
        domain_json=json.dumps(domain, ensure_ascii=False),
        ontology_json=json.dumps(ontology, ensure_ascii=False),
        candidates_json=json.dumps(graph_candidates, ensure_ascii=False),
        document_text=base_doc,
    )
    schema_align_raw = (llm.invoke([HumanMessage(content=schema_align_prompt)]).content or "").strip()
    schema_aligned = _parse_json_object(schema_align_raw) or _fallback_schema_align(graph_candidates, ontology)
    schema_proposals = (
        schema_aligned.get("schema_proposals")
        if isinstance(schema_aligned.get("schema_proposals"), list)
        else []
    )

    entity_resolve_prompt = get_prompt(
        "knowledge.extract.entity_resolve",
        topic=topic,
        domain_json=json.dumps(domain, ensure_ascii=False),
        aligned_json=json.dumps(schema_aligned, ensure_ascii=False),
        document_text=base_doc,
    )
    entity_resolve_raw = (llm.invoke([HumanMessage(content=entity_resolve_prompt)]).content or "").strip()
    entity_resolve = _parse_json_object(entity_resolve_raw) or _fallback_entity_resolve(schema_aligned)
    graph_pre = _apply_entity_resolution(schema_aligned, entity_resolve)
    graph_pre_normalized = _normalize_graph_result(graph_pre)

    graph_prompt = get_prompt(
        "knowledge.extract.graph",
        topic=topic,
        domain_json=json.dumps(domain, ensure_ascii=False),
        ontology_json=json.dumps(ontology, ensure_ascii=False),
        summary_json=json.dumps(summary, ensure_ascii=False),
        document_text=base_doc,
        points_json=json.dumps(points_items, ensure_ascii=False),
        candidates_json=json.dumps(graph_candidates, ensure_ascii=False),
        aligned_json=json.dumps(schema_aligned, ensure_ascii=False),
        resolved_json=json.dumps(graph_pre_normalized, ensure_ascii=False),
    )
    graph_raw = (llm.invoke([HumanMessage(content=graph_prompt)]).content or "").strip()
    graph_parsed = _parse_json_object(graph_raw) or graph_pre_normalized or _fallback_graph(points_items)
    graph_normalized = _normalize_graph_result(graph_parsed)
    graph, graph_metrics = _apply_ontology_constraints(graph_normalized, ontology)
    graph_metrics["schema_proposals"] = len(schema_proposals)
    graph_metrics["canonical_entity_merge_count"] = int(graph_pre.get("merged_aliases") or 0)
    graph_metrics["entity_count"] = len(graph.get("nodes") if isinstance(graph.get("nodes"), list) else [])
    graph_metrics["edge_count"] = len(graph.get("edges") if isinstance(graph.get("edges"), list) else [])

    return {
        "summary": summary,
        "structure": structure,
        "key_points": points,
        "domain": domain,
        "ontology": ontology,
        "graph_candidates": graph_candidates,
        "graph_schema_aligned": schema_aligned,
        "graph_entity_resolved": graph_pre_normalized,
        "schema_proposals": schema_proposals,
        "graph": graph,
        "graph_raw": graph_parsed,
        "graph_metrics": graph_metrics,
    }
