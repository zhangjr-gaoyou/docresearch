"""Research step execution agent: executes a single step with prior result and optional doc content."""
import json
import threading
from typing import Any, Callable, Dict, Optional

from app.services.research.exceptions import ResearchJobCancelled

from langchain_core.messages import HumanMessage

from app.core.settings import settings
from app.services.llm_factory import get_chat_openai
from app.services.prompt_registry import get_prompt

MAX_SINGLE_CHUNK = 8000
MAX_TOTAL_CONTEXT = 12000


def _raise_if_cancelled(cancel_event: Optional[threading.Event]) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise ResearchJobCancelled()


def _get_llm(temperature: float = 0.3):
    """Create LLM client for DashScope (Qwen)."""
    return get_chat_openai(temperature=temperature)


def _extract_finish_reason(response: Any) -> str:
    md = getattr(response, "response_metadata", None) or {}
    ak = getattr(response, "additional_kwargs", None) or {}
    reason = md.get("finish_reason") or ak.get("finish_reason") or md.get("stop_reason")
    return str(reason or "")


def _is_truncated_finish_reason(reason: str) -> bool:
    return reason.strip().lower() in {"length", "max_tokens", "token_limit"}


def _report_truncation(
    *,
    slot: str,
    finish_reason: str,
    prompt_chars: int,
    output_chars: int,
    on_log: Optional[Callable[[str], None]],
    on_diag: Optional[Callable[[Dict[str, Any]], None]],
    chunk_index: Optional[int] = None,
    chunk_total: Optional[int] = None,
) -> None:
    msg = (
        f"模型输出疑似被截断（slot={slot}, finish_reason={finish_reason or 'unknown'}, "
        f"prompt_chars={prompt_chars}, output_chars={output_chars}）"
    )
    if on_log:
        on_log(msg)
    if on_diag:
        evt: Dict[str, Any] = {
            "kind": "tool",
            "name": "llm_output_truncated",
            "level": "error",
            "detail": json.dumps(
                {
                    "slot": slot,
                    "finish_reason": finish_reason or "unknown",
                    "prompt_chars": prompt_chars,
                    "output_chars": output_chars,
                },
                ensure_ascii=False,
            ),
        }
        if chunk_index is not None:
            evt["chunk_index"] = chunk_index
        if chunk_total is not None:
            evt["chunk_total"] = chunk_total
        on_diag(evt)


def _validate_step_output(step_content: str, output: str) -> Optional[str]:
    """Return error message when output is structurally invalid."""
    if not output or not output.strip():
        return "输出为空"
    # If step explicitly asks for table output, require markdown-table-like structure.
    asks_table = ("表格" in step_content) or ("|---" in step_content)
    if asks_table:
        if "|" not in output or "|---" not in output:
            return "步骤要求表格输出，但结果不含有效 Markdown 表格结构"
    # If step explicitly asks JSON output, require parseable JSON.
    asks_json = ("json" in step_content.lower()) or ("JSON" in step_content)
    if asks_json:
        txt = output.strip()
        if "```" in txt:
            parts = txt.split("```")
            if len(parts) >= 2:
                txt = parts[1]
                if txt.startswith("json"):
                    txt = txt[4:]
                txt = txt.strip()
        try:
            json.loads(txt)
        except Exception:
            return "步骤要求 JSON 输出，但结果不是合法 JSON"
    return None


def _invoke_step_with_retry(
    llm,
    prompt: str,
    slot: str,
    step_content: str,
    on_log: Optional[Callable[[str], None]],
    on_diag: Optional[Callable[[Dict[str, Any]], None]],
    chunk_index: Optional[int] = None,
    chunk_total: Optional[int] = None,
) -> str:
    retries = max(0, int(settings.STEP_OUTPUT_VALIDATE_RETRIES))
    current_prompt = prompt
    last_content = ""
    for attempt in range(retries + 1):
        response = llm.invoke([HumanMessage(content=current_prompt)])
        content = (response.content or "").strip()
        last_content = content
        finish_reason = _extract_finish_reason(response)
        err = _validate_step_output(step_content, content)
        if _is_truncated_finish_reason(finish_reason):
            _report_truncation(
                slot=slot,
                finish_reason=finish_reason,
                prompt_chars=len(current_prompt),
                output_chars=len(content),
                on_log=on_log,
                on_diag=on_diag,
                chunk_index=chunk_index,
                chunk_total=chunk_total,
            )
            err = err or "模型输出因达到最大生成长度被截断"
        if not err:
            return content
        if attempt >= retries:
            if on_log:
                on_log(f"步骤输出校验失败（已达重试上限）：{err}")
            if on_diag:
                on_diag(
                    {
                        "kind": "tool",
                        "name": "step_output_validation_failed",
                        "level": "error",
                        "detail": json.dumps(
                            {"slot": slot, "attempt": attempt + 1, "error": err},
                            ensure_ascii=False,
                        ),
                        "chunk_index": chunk_index,
                        "chunk_total": chunk_total,
                    }
                )
            return content
        if on_log:
            on_log(f"步骤输出结构校验失败，准备重试（{attempt + 1}/{retries}）：{err}")
        if on_diag:
            on_diag(
                {
                    "kind": "tool",
                    "name": "step_output_validation_retry",
                    "level": "warning",
                    "detail": json.dumps(
                        {"slot": slot, "attempt": attempt + 1, "error": err},
                        ensure_ascii=False,
                    ),
                    "chunk_index": chunk_index,
                    "chunk_total": chunk_total,
                }
            )
        extra = ""
        if "截断" in err:
            extra = "输出可能被长度限制截断：请输出完整结果；可精简单元格文字但须保留全部数据行，并保证 Markdown 表格完整闭合。"
        current_prompt = (
            current_prompt
            + "\n\n【输出纠正要求】\n"
            + f"上一版输出存在问题：{err}。\n"
            + extra
            + "请严格按当前步骤要求，仅输出符合格式的结果，不要添加额外解释。"
        )


def _should_use_map_reduce_for_main_prompt(prompt: str) -> bool:
    return len(prompt) > int(settings.STEP_MAIN_PROMPT_MAX_CHARS)


def _truncate_map_partial(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    omitted = len(text) - max_len
    return text[:max_len] + f"\n\n…（已截断，省略后续约 {omitted} 字符）"


def _split_markdown_blocks(s: str, max_chunk: int) -> list[str]:
    """Split long markdown near newlines so map_merge inputs stay smaller (avoids one huge completion)."""
    if max_chunk <= 0 or len(s) <= max_chunk:
        return [s]
    parts: list[str] = []
    start = 0
    n = len(s)
    while start < n:
        end = min(n, start + max_chunk)
        if end < n:
            cut = s.rfind("\n", max(0, end - 2500), end)
            if cut > start:
                end = cut
        parts.append(s[start:end].rstrip())
        start = end
    return [p for p in parts if p]


def _map_merge_prompt_length(topic: str, step_content: str, partial_blob: str) -> int:
    return len(
        get_prompt(
            "research.step_execution.map_merge",
            topic=topic,
            step_content=step_content,
            partial_results=partial_blob,
        )
    )


def _tree_reduce_map_partials(
    llm,
    topic: str,
    step_content: str,
    partials: list[str],
    depth: int,
    on_log: Optional[Callable[[str], None]],
    on_diag: Optional[Callable[[Dict[str, Any]], None]],
    cancel_event: Optional[threading.Event],
) -> str:
    """
    Reduce multiple map-phase partial Markdown results using repeated map_merge.
    Avoids a single giant merge prompt (and a single huge completion) when many chunks exist.
    """
    _raise_if_cancelled(cancel_event)
    max_depth = max(1, int(settings.STEP_MAP_MERGE_MAX_DEPTH))
    if depth > max_depth:
        raise RuntimeError(
            f"map_merge 分层合并超过最大深度 {max_depth}，请拆小计划步骤或提高 STEP_MAP_MERGE_MAX_DEPTH"
        )
    if len(partials) == 1:
        return partials[0]
    mid = len(partials) // 2
    left = _tree_reduce_map_partials(
        llm, topic, step_content, partials[:mid], depth + 1, on_log, on_diag, cancel_event
    )
    right = _tree_reduce_map_partials(
        llm, topic, step_content, partials[mid:], depth + 1, on_log, on_diag, cancel_event
    )
    pair_cap = max(4000, int(settings.STEP_MAP_MERGE_PAIR_MAX_CHARS_EACH))
    merge_cap = int(settings.STEP_MAP_MERGE_MAX_PROMPT_CHARS)
    left_t = _truncate_map_partial(left, pair_cap)
    right_t = _truncate_map_partial(right, pair_cap)
    blob = f"{left_t}\n\n---\n\n{right_t}"
    for _ in range(8):
        if _map_merge_prompt_length(topic, step_content, blob) <= merge_cap:
            break
        pair_cap = max(3000, int(pair_cap * 0.72))
        left_t = _truncate_map_partial(left, pair_cap)
        right_t = _truncate_map_partial(right, pair_cap)
        blob = f"{left_t}\n\n---\n\n{right_t}"
    merge_prompt = get_prompt(
        "research.step_execution.map_merge",
        topic=topic,
        step_content=step_content,
        partial_results=blob,
    )
    if on_log:
        on_log(
            f"map_merge 分层合并（深度 {depth}）：左右片段约 {len(left_t)} / {len(right_t)} 字符，"
            f"提示词约 {len(merge_prompt)} 字符"
        )
    if on_diag:
        head = 2800
        prev = (
            merge_prompt
            if len(merge_prompt) <= head + 400
            else merge_prompt[:head] + f"\n\n…（map_merge 分层提示词总长 {len(merge_prompt)} 字符，已省略）"
        )
        on_diag(
            {
                "kind": "llm_prompt",
                "slot": "research.step_execution.map_merge",
                "text": prev,
                "chunk_index": depth + 1,
                "chunk_total": None,
            }
        )
    _raise_if_cancelled(cancel_event)
    return _invoke_step_with_retry(
        llm=llm,
        prompt=merge_prompt,
        slot="research.step_execution.map_merge",
        step_content=step_content,
        on_log=on_log,
        on_diag=on_diag,
    )


def _build_doc_section(
    collection_doc_markdown: str,
    prior_chars: int,
    on_diag: Optional[Callable[[Dict[str, Any]], None]],
    split_source: str = "main",
) -> str:
    if not collection_doc_markdown.strip():
        return "\n（本步骤未引用文档集文档全文）\n"
    doc_content = collection_doc_markdown
    raw_len = len(collection_doc_markdown)
    if len(doc_content) > MAX_TOTAL_CONTEXT - prior_chars - 500:
        doc_content = doc_content[: MAX_TOTAL_CONTEXT - prior_chars - 500] + "\n\n（内容已截断）"
        if on_diag:
            on_diag(
                {
                    "kind": "tool",
                    "name": "truncate_document_for_step_context",
                    "detail": json.dumps(
                        {
                            "raw_chars": raw_len,
                            "max_context": MAX_TOTAL_CONTEXT,
                            "prior_chars": prior_chars,
                            "split_source": split_source,
                        },
                        ensure_ascii=False,
                    ),
                }
            )
    return f"""
## 引用的文档内容

{doc_content}
"""


def _resolve_step_prompt(
    topic: str,
    step_content: str,
    step_index: int,
    prior_step_markdown: str,
    collection_doc_markdown: str,
    on_diag: Optional[Callable[[Dict[str, Any]], None]],
    split_source: str = "main",
) -> tuple[str, str]:
    is_first = step_index == 0
    doc_section = _build_doc_section(
        collection_doc_markdown=collection_doc_markdown,
        prior_chars=len(prior_step_markdown),
        on_diag=on_diag,
        split_source=split_source,
    )
    if is_first:
        slot = "research.step_execution.first_step"
        prompt = get_prompt(
            slot,
            topic=topic,
            step_content=step_content,
            step_index=step_index + 1,
            doc_section=doc_section,
        )
        return slot, prompt

    slot = "research.step_execution.later_step"
    prior_section = ""
    if prior_step_markdown.strip():
        prior_section = f"""
## 上一步骤执行结果

{prior_step_markdown}
"""
    prompt = get_prompt(
        slot,
        topic=topic,
        step_content=step_content,
        step_index=step_index + 1,
        prior_section=prior_section,
        doc_section=doc_section,
    )
    return slot, prompt


def execute_step(
    topic: str,
    step_content: str,
    step_index: int,
    prior_step_markdown: str = "",
    collection_doc_markdown: str = "",
    doc_label: str = "",
    on_log: Optional[Callable[[str], None]] = None,
    on_diag: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> str:
    """
    Execute a single research step.
    Inputs: topic, step text, prior step result, optional collection doc content.
    Returns Markdown string for this step.
    """
    llm = _get_llm()

    slot, prompt = _resolve_step_prompt(
        topic=topic,
        step_content=step_content,
        step_index=step_index,
        prior_step_markdown=prior_step_markdown,
        collection_doc_markdown=collection_doc_markdown,
        on_diag=on_diag,
        split_source="main",
    )

    threshold = int(settings.STEP_MAIN_PROMPT_MAX_CHARS)
    use_map_reduce = _should_use_map_reduce_for_main_prompt(prompt) and collection_doc_markdown.strip()
    if _should_use_map_reduce_for_main_prompt(prompt) and not prior_step_markdown.strip() and on_diag:
        on_diag(
            {
                "kind": "tool",
                "name": "map_reduce_fallback_no_prior",
                "detail": json.dumps(
                    {
                        "slot": slot,
                        "prompt_chars": len(prompt),
                        "threshold": threshold,
                        "decision": "direct",
                        "reason": "prior_step_markdown_empty",
                        "doc_label": doc_label,
                        "step_index": step_index + 1,
                    },
                    ensure_ascii=False,
                ),
            }
        )
    if _should_use_map_reduce_for_main_prompt(prompt) and prior_step_markdown.strip() and not collection_doc_markdown.strip() and on_diag:
        on_diag(
            {
                "kind": "tool",
                "name": "map_reduce_fallback_no_doc",
                "detail": json.dumps(
                    {
                        "slot": slot,
                        "prompt_chars": len(prompt),
                        "threshold": threshold,
                        "decision": "direct",
                        "reason": "collection_doc_markdown_empty",
                        "doc_label": doc_label,
                        "step_index": step_index + 1,
                    },
                    ensure_ascii=False,
                ),
            }
        )
    if on_diag:
        on_diag(
            {
                "kind": "tool",
                "name": "step_prompt_too_long_map_reduce",
                "detail": json.dumps(
                    {
                        "slot": slot,
                        "prompt_chars": len(prompt),
                        "threshold": threshold,
                        "decision": "map_reduce" if use_map_reduce else "direct",
                        "doc_label": doc_label,
                        "step_index": step_index + 1,
                    },
                    ensure_ascii=False,
                ),
            }
        )

    if _should_use_map_reduce_for_main_prompt(prompt) and prior_step_markdown.strip():
        return _execute_step_map_reduce(
            llm=llm,
            topic=topic,
            step_content=step_content,
            step_index=step_index,
            prior_step_markdown=prior_step_markdown,
            collection_doc_markdown=collection_doc_markdown,
            doc_label=doc_label,
            on_log=on_log,
            on_diag=on_diag,
            cancel_event=cancel_event,
        )

    if on_diag:
        on_diag({"kind": "llm_prompt", "slot": slot, "text": prompt})

    _raise_if_cancelled(cancel_event)
    return _invoke_step_with_retry(
        llm=llm,
        prompt=prompt,
        slot=slot,
        step_content=step_content,
        on_log=on_log,
        on_diag=on_diag,
    )


def _execute_step_map_reduce(
    llm,
    topic: str,
    step_content: str,
    step_index: int,
    prior_step_markdown: str,
    collection_doc_markdown: str,
    doc_label: str,
    on_log: Optional[Callable[[str], None]] = None,
    on_diag: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> str:
    """Map-reduce for long step prompt: split prior-step markdown, keep doc context intact."""
    chunks = [
        prior_step_markdown[i : i + MAX_SINGLE_CHUNK]
        for i in range(0, len(prior_step_markdown), MAX_SINGLE_CHUNK)
    ]
    if on_log:
        on_log(f"上一步结果较大，拆分为 {len(chunks)} 个片段进行 Map-Reduce")
    if on_diag:
        on_diag(
            {
                "kind": "tool",
                "name": "prior_step_split_for_map_reduce",
                "detail": json.dumps(
                    {
                        "source": "prior_step_markdown",
                        "prior_total_chars": len(prior_step_markdown),
                        "doc_chars": len(collection_doc_markdown),
                        "chunk_size": MAX_SINGLE_CHUNK,
                        "num_chunks": len(chunks),
                        "doc_label": doc_label,
                        "step_index": step_index + 1,
                    },
                    ensure_ascii=False,
                ),
            }
        )

    partial_results = []
    for i, chunk in enumerate(chunks):
        _raise_if_cancelled(cancel_event)
        chunk_prior = chunk if step_index > 0 else prior_step_markdown
        chunk_slot, prompt = _resolve_step_prompt(
            topic=topic,
            step_content=step_content,
            step_index=step_index,
            prior_step_markdown=chunk_prior,
            collection_doc_markdown=collection_doc_markdown,
            on_diag=on_diag,
            split_source="prior_step_markdown",
        )
        if on_diag:
            on_diag(
                {
                    "kind": "llm_prompt",
                    "slot": chunk_slot,
                    "text": prompt,
                    "chunk_index": i + 1,
                    "chunk_total": len(chunks),
                }
            )
        chunk_out = _invoke_step_with_retry(
            llm=llm,
            prompt=prompt,
            slot=chunk_slot,
            step_content=step_content,
            on_log=on_log,
            on_diag=on_diag,
            chunk_index=i + 1,
            chunk_total=len(chunks),
        )
        partial_results.append(chunk_out)

    _raise_if_cancelled(cancel_event)
    if len(partial_results) == 1:
        return partial_results[0]
    merge_cap = int(settings.STEP_MAP_MERGE_MAX_PROMPT_CHARS)
    max_piece = max(6000, int(settings.STEP_MAP_MERGE_PAIR_MAX_CHARS_EACH))
    expanded: list[str] = []
    for p in partial_results:
        expanded.extend(_split_markdown_blocks(p, max_piece))
    flat = "\n\n---\n\n".join(expanded)
    for _ in range(8):
        if len(expanded) <= 1:
            break
        if _map_merge_prompt_length(topic, step_content, flat) <= merge_cap:
            break
        max_piece = max(4000, int(max_piece * 0.72))
        expanded = []
        for p in partial_results:
            expanded.extend(_split_markdown_blocks(p, max_piece))
        flat = "\n\n---\n\n".join(expanded)
    if len(expanded) == 1:
        return expanded[0]
    if on_diag:
        on_diag(
            {
                "kind": "tool",
                "name": "map_merge_tree_reduce",
                "detail": json.dumps(
                    {
                        "num_partial_chunks_before_split": len(partial_results),
                        "num_partial_chunks_after_split": len(expanded),
                        "flat_join_chars": len(flat),
                        "max_prompt_chars": merge_cap,
                        "pair_max_each": int(settings.STEP_MAP_MERGE_PAIR_MAX_CHARS_EACH),
                        "max_piece_used": max_piece,
                    },
                    ensure_ascii=False,
                ),
            }
        )
    return _tree_reduce_map_partials(
        llm=llm,
        topic=topic,
        step_content=step_content,
        partials=expanded,
        depth=0,
        on_log=on_log,
        on_diag=on_diag,
        cancel_event=cancel_event,
    )
