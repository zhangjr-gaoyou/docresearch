"""Research scheduler agent: document x step loop, routing LLM, step execution, merge final."""
import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from app.services.research.exceptions import ResearchJobCancelled


def _raise_if_cancelled(cancel_event: Optional[threading.Event]) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise ResearchJobCancelled()

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from app.core.settings import settings
from app.services.prompt_registry import get_prompt
from app.services.research.tools import (
    list_collection_document_files,
    read_collection_document_text,
    read_step_result_markdown,
    write_step_result_markdown,
)
from app.services.research.step_execution_agent import execute_step


def _get_llm(temperature: float = 0.3):
    """Create LLM client for DashScope (Qwen)."""
    api_key = settings.DASHSCOPE_API_KEY or os.getenv("DASHSCOPE_API_KEY", "")
    return ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        temperature=temperature,
    )


MAX_RESPONSE_PREVIEW = 1500
PROMPT_LOG_MAX = 6000
MERGE_PROMPT_HEAD = 2800


def _truncate(text: str, max_len: int = MAX_RESPONSE_PREVIEW) -> str:
    """Truncate text for log preview."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "\n\n…已截断"


def _truncate_prompt(text: str, max_len: int = PROMPT_LOG_MAX) -> str:
    return _truncate(text, max_len)


def _preview_merge_prompt(text: str) -> str:
    """Merge prompt embeds full doc_results; log only head + length note."""
    if len(text) <= MERGE_PROMPT_HEAD + 500:
        return _truncate_prompt(text)
    return (
        text[:MERGE_PROMPT_HEAD]
        + f"\n\n…（合并提示词总长 {len(text)} 字符，内含各文档最后步骤全文，此处省略后续）"
    )


def _add_log(logs: list, message: str, level: str = "info", **extra):
    """Append execution log entry."""
    logs.append({
        "time": datetime.now().strftime("%H:%M:%S"),
        "message": message,
        "level": level,
        **extra,
    })


TOOL_CALL_LOG_PREFIX = "智能体工具调用："


def _add_tool_log(logs: list, message: str, level: str = "info", **extra):
    """Log for agent-side tool I/O; prefixes message so UI shows tool calls clearly."""
    _add_log(logs, f"{TOOL_CALL_LOG_PREFIX}{message}", level=level, **extra)


def _route_need_collection_document(
    topic: str,
    step_content: str,
    step_index: int,
    total_steps: int,
    doc_label: str,
    is_first_step: bool,
    logs: list | None = None,
) -> tuple[bool, str]:
    """
    LLM routing: decide whether this step needs the full collection document.
    Returns (need_document, reason).
    """
    llm = _get_llm(temperature=0.2)
    bias = "第一步通常需要引用文档全文以了解内容；" if is_first_step else ""
    prompt = get_prompt(
        "research.scheduler.routing",
        topic=topic,
        step_content=step_content,
        step_index=step_index + 1,
        total_steps=total_steps,
        doc_label=doc_label,
        bias=bias,
    )
    if logs:
        _add_log(
            logs,
            "路由阶段 · 发送提示词",
            level="info",
            prompt_slot="research.scheduler.routing",
            prompt_preview=_truncate_prompt(prompt),
        )
    response = llm.invoke([HumanMessage(content=prompt)])
    text = response.content.strip()
    if logs:
        _add_log(logs, "路由智能体返回", agent="scheduler_route", response_preview=_truncate(text))
    # Extract JSON (handle markdown code blocks)
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()
    try:
        data = json.loads(text)
        need = bool(data.get("need_collection_document", False))
        reason = str(data.get("reason", ""))
        return need, reason
    except (json.JSONDecodeError, TypeError):
        return is_first_step, "解析失败，默认按首步需要文档"


def run_scheduler(
    collection_id: str,
    plan: dict,
    topic: str,
    job_output_dir: Path,
    logs: list,
    on_progress: Optional[Callable[[str], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    resume: bool = False,
) -> tuple[str, str]:
    """
    Execute document x step loop: routing, step execution, write results, merge final.
    If resume=True, skip steps whose result file already exists (continue after cancel).
    Returns (final_markdown, output_path).
    """
    steps = plan.get("steps", [])
    doc_files = list_collection_document_files(collection_id)
    if not doc_files:
        _add_log(logs, "文档集中无文档", level="error")
        raise ValueError("No documents in collection")

    try:
        _fnames = [p.name for p in doc_files]
        _detail = json.dumps(
            {"collection_id": collection_id, "count": len(_fnames), "filenames": _fnames[:40]},
            ensure_ascii=False,
        )
    except Exception:
        _detail = f'{{"collection_id":"{collection_id}","count":{len(doc_files)}}}'
    _add_tool_log(
        logs,
        "工具：枚举文档集内文件",
        tool_name="list_collection_document_files",
        tool_detail=_detail[:4000],
    )

    _add_log(logs, f"研究步骤共 {len(steps)} 个", level="info")
    _add_log(logs, f"发现 {len(doc_files)} 个文档待分析", level="info", document_count=len(doc_files))
    if resume:
        _add_log(logs, "从已保存进度继续执行：已完成的步骤将跳过模型调用", level="info")

    last_step_outputs = []
    for doc_idx, doc_path in enumerate(doc_files):
        _raise_if_cancelled(cancel_event)
        doc_key = doc_path.stem
        doc_label = doc_path.name
        if on_progress:
            on_progress(f"Processing document {doc_idx + 1}/{len(doc_files)}: {doc_label}")
        _add_log(
            logs,
            f"[{doc_idx + 1}/{len(doc_files)}] 开始处理文档：{doc_label}",
            level="info",
            document=doc_label,
            doc_index=doc_idx + 1,
            doc_total=len(doc_files),
        )

        prev_step_result = ""
        last_written_step_idx = -1
        for step_idx, step in enumerate(steps):
            _raise_if_cancelled(cancel_event)
            step_content = (step.get("content") or "").strip()
            if not step_content:
                continue

            cached = read_step_result_markdown(job_output_dir, doc_key, step_idx)
            if resume and cached is not None:
                _add_tool_log(
                    logs,
                    f"步骤 {step_idx + 1}/{len(steps)} 已有保存结果，跳过执行",
                    level="info",
                    document=doc_label,
                    step_index=step_idx + 1,
                    step_total=len(steps),
                    tool_name="read_step_result_markdown",
                    tool_detail=json.dumps(
                        {"doc_key": doc_key, "step_index": step_idx, "chars": len(cached)},
                        ensure_ascii=False,
                    )[:2000],
                )
                prev_step_result = cached
                last_written_step_idx = step_idx
                continue

            prior_md = prev_step_result
            if step_idx > 0:
                prior = read_step_result_markdown(job_output_dir, doc_key, step_idx - 1)
                prior_md = prior if prior is not None else prev_step_result

            need_doc, reason = _route_need_collection_document(
                topic=topic,
                step_content=step_content,
                step_index=step_idx,
                total_steps=len(steps),
                doc_label=doc_label,
                is_first_step=(step_idx == 0),
                logs=logs,
            )
            _raise_if_cancelled(cancel_event)

            _add_log(
                logs,
                f"步骤 {step_idx + 1}/{len(steps)} 路由：{'引用全文' if need_doc else '不引用'} - {reason}",
                level="info",
                document=doc_label,
                step_index=step_idx + 1,
                step_total=len(steps),
                need_collection_document=need_doc,
            )

            doc_text = ""
            if need_doc:
                try:
                    doc_text = read_collection_document_text(doc_path)
                    _add_tool_log(
                        logs,
                        f"工具：读取文档全文 · {doc_label}（{len(doc_text)} 字符）",
                        level="info",
                        document=doc_label,
                        char_count=len(doc_text),
                        tool_name="read_collection_document_text",
                        tool_detail=json.dumps(
                            {"path": str(doc_path), "chars": len(doc_text)},
                            ensure_ascii=False,
                        )[:2000],
                    )
                except Exception as e:
                    _add_log(logs, f"加载文档失败：{e}", level="error", document=doc_label)

            _raise_if_cancelled(cancel_event)

            def _on_step_log(msg: str):
                _add_log(logs, msg, level="info", document=doc_label, step_index=step_idx + 1)

            def _on_diag(evt: Dict[str, Any]):
                kind = evt.get("kind")
                if kind == "llm_prompt":
                    _add_log(
                        logs,
                        f"步骤执行 · 提示词 [{evt.get('slot', '')}]",
                        level="info",
                        document=doc_label,
                        step_index=step_idx + 1,
                        prompt_slot=str(evt.get("slot", "")),
                        prompt_preview=_truncate_prompt(str(evt.get("text", ""))),
                        chunk_index=evt.get("chunk_index"),
                        chunk_total=evt.get("chunk_total"),
                    )
                elif kind == "tool":
                    _add_tool_log(
                        logs,
                        f"工具：{evt.get('name', '')}",
                        level="info",
                        document=doc_label,
                        step_index=step_idx + 1,
                        tool_name=str(evt.get("name", "")),
                        tool_detail=str(evt.get("detail", ""))[:4000],
                    )

            body = execute_step(
                topic=topic,
                step_content=step_content,
                step_index=step_idx,
                prior_step_markdown=prior_md,
                collection_doc_markdown=doc_text,
                doc_label=doc_label,
                on_log=_on_step_log,
                on_diag=_on_diag,
                cancel_event=cancel_event,
            )

            _add_log(
                logs,
                "步骤执行智能体返回",
                agent="step_execution",
                response_preview=_truncate(body),
                document=doc_label,
                step_index=step_idx + 1,
            )

            out_path = write_step_result_markdown(job_output_dir, doc_key, step_idx, body)
            _add_tool_log(
                logs,
                f"工具：写入步骤结果 · {out_path.relative_to(job_output_dir)}",
                level="info",
                document=doc_label,
                step_index=step_idx + 1,
                output_path=str(out_path),
                tool_name="write_step_result_markdown",
                tool_detail=json.dumps(
                    {
                        "relative": str(out_path.relative_to(job_output_dir)),
                        "chars_written": len(body),
                    },
                    ensure_ascii=False,
                )[:2000],
            )
            prev_step_result = body
            last_written_step_idx = step_idx

        last_md = read_step_result_markdown(job_output_dir, doc_key, last_written_step_idx) if last_written_step_idx >= 0 else None
        if last_md:
            last_step_outputs.append((doc_label, last_md))
        _raise_if_cancelled(cancel_event)

    if not last_step_outputs:
        _add_log(logs, "无有效步骤结果可合并", level="error")
        return "", str(job_output_dir.resolve())

    _add_log(logs, f"正在合并 {len(last_step_outputs)} 个文档的最后步骤结果...", level="info")
    _raise_if_cancelled(cancel_event)
    doc_results = chr(10).join(f"### 文档：{name}\n{content}" for name, content in last_step_outputs)
    merge_prompt = get_prompt("research.scheduler.merge_final", topic=topic, doc_results=doc_results)

    _add_log(
        logs,
        "合并阶段 · 发送提示词",
        level="info",
        prompt_slot="research.scheduler.merge_final",
        prompt_preview=_preview_merge_prompt(merge_prompt),
    )
    llm = _get_llm()
    _raise_if_cancelled(cancel_event)
    response = llm.invoke([HumanMessage(content=merge_prompt)])
    final_md = response.content.strip()
    _add_log(
        logs,
        "合并智能体返回",
        agent="scheduler_merge",
        response_preview=_truncate(final_md),
    )
    _add_log(logs, f"合并完成，最终报告 {len(final_md)} 字符", level="info")

    final_path = job_output_dir / "final.md"
    final_path.write_text(final_md, encoding="utf-8")
    _add_log(logs, "最终报告已保存到 final.md", level="info")

    return final_md, str(job_output_dir.resolve())
