"""Research step execution agent: executes a single step with prior result and optional doc content."""
import json
import os
import threading
from typing import Any, Callable, Dict, Optional

from app.services.research.exceptions import ResearchJobCancelled

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from app.core.settings import settings
from app.services.prompt_registry import get_prompt

MAX_SINGLE_CHUNK = 8000
MAX_TOTAL_CONTEXT = 12000


def _raise_if_cancelled(cancel_event: Optional[threading.Event]) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise ResearchJobCancelled()


def _get_llm(temperature: float = 0.3):
    """Create LLM client for DashScope (Qwen)."""
    api_key = settings.DASHSCOPE_API_KEY or os.getenv("DASHSCOPE_API_KEY", "")
    return ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        temperature=temperature,
    )


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

    prior_section = ""
    if prior_step_markdown.strip():
        prior_section = f"""
## 上一步骤执行结果

{prior_step_markdown}
"""

    doc_section = ""
    if collection_doc_markdown.strip():
        doc_content = collection_doc_markdown
        raw_len = len(collection_doc_markdown)
        if len(doc_content) > MAX_TOTAL_CONTEXT - len(prior_step_markdown) - 500:
            doc_content = doc_content[: MAX_TOTAL_CONTEXT - len(prior_step_markdown) - 500] + "\n\n（内容已截断）"
            if on_diag:
                on_diag(
                    {
                        "kind": "tool",
                        "name": "truncate_document_for_step_context",
                        "detail": json.dumps(
                            {
                                "raw_chars": raw_len,
                                "max_context": MAX_TOTAL_CONTEXT,
                                "prior_chars": len(prior_step_markdown),
                            },
                            ensure_ascii=False,
                        ),
                    }
                )
        doc_section = f"""
## 引用的文档内容

{doc_content}
"""
    else:
        doc_section = "\n（本步骤未引用文档集文档全文）\n"

    prompt = get_prompt(
        "research.step_execution.main",
        topic=topic,
        step_content=step_content,
        step_index=step_index + 1,
        prior_section=prior_section,
        doc_section=doc_section,
    )

    if len(collection_doc_markdown) > MAX_TOTAL_CONTEXT and collection_doc_markdown.strip():
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
        on_diag({"kind": "llm_prompt", "slot": "research.step_execution.main", "text": prompt})

    _raise_if_cancelled(cancel_event)
    response = llm.invoke([HumanMessage(content=prompt)])
    return response.content.strip()


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
    """Map-reduce for large document in single step."""
    chunks = [
        collection_doc_markdown[i : i + MAX_SINGLE_CHUNK]
        for i in range(0, len(collection_doc_markdown), MAX_SINGLE_CHUNK)
    ]
    if on_log:
        on_log(f"文档较大，拆分为 {len(chunks)} 个片段进行 Map-Reduce")
    if on_diag:
        on_diag(
            {
                "kind": "tool",
                "name": "document_split_for_map_reduce",
                "detail": json.dumps(
                    {
                        "total_chars": len(collection_doc_markdown),
                        "chunk_size": MAX_SINGLE_CHUNK,
                        "num_chunks": len(chunks),
                        "doc_label": doc_label,
                    },
                    ensure_ascii=False,
                ),
            }
        )

    partial_results = []
    for i, chunk in enumerate(chunks):
        _raise_if_cancelled(cancel_event)
        prior_section = f"\n## 上一步骤结果\n{prior_step_markdown}\n" if prior_step_markdown.strip() else ""
        prompt = get_prompt(
            "research.step_execution.map_chunk",
            topic=topic,
            step_content=step_content,
            prior_section=prior_section,
            chunk=chunk,
            chunk_index=i + 1,
            chunk_total=len(chunks),
        )
        if on_diag:
            on_diag(
                {
                    "kind": "llm_prompt",
                    "slot": "research.step_execution.map_chunk",
                    "text": prompt,
                    "chunk_index": i + 1,
                    "chunk_total": len(chunks),
                }
            )
        response = llm.invoke([HumanMessage(content=prompt)])
        partial_results.append(response.content)

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
    response = llm.invoke([HumanMessage(content=merge_prompt)])
    return response.content.strip()
