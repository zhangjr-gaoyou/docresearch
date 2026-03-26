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
        err = _validate_step_output(step_content, content)
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
        current_prompt = (
            current_prompt
            + "\n\n【输出纠正要求】\n"
            + f"上一版输出存在结构问题：{err}。\n"
            + "请严格按当前步骤要求，仅输出符合格式的结果，不要添加额外解释。"
        )


def _should_use_map_reduce_for_main_prompt(prompt: str) -> bool:
    return len(prompt) > int(settings.STEP_MAIN_PROMPT_MAX_CHARS)


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
                        "slot": "research.step_execution.main",
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
    partial_results_str = chr(10).join(partial_results)
    merge_prompt = get_prompt(
        "research.step_execution.map_merge",
        topic=topic,
        step_content=step_content,
        partial_results=partial_results_str,
    )
    if on_diag:
        head = 4000
        prev = merge_prompt if len(merge_prompt) <= head + 400 else merge_prompt[:head] + f"\n\n…（map_merge 提示词总长 {len(merge_prompt)} 字符，含各片段合并正文，已省略）"
        on_diag(
            {
                "kind": "llm_prompt",
                "slot": "research.step_execution.map_merge",
                "text": prev,
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
