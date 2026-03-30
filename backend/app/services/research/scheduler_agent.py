"""Research scheduler agent: document x step loop, routing LLM, step execution, merge final."""
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from app.services.research.exceptions import ResearchJobCancelled


def _raise_if_cancelled(cancel_event: Optional[threading.Event]) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise ResearchJobCancelled()

from langchain_core.messages import HumanMessage

from app.core.settings import settings
from app.services.llm_factory import get_chat_openai, get_merge_chat_openai
from app.services.prompt_registry import get_prompt
from app.services.research.tools import (
    list_collection_document_files,
    read_collection_document_text,
    read_step_result_markdown,
    write_step_result_markdown,
)
from app.services.research.step_execution_agent import execute_step


def _get_llm(temperature: float = 0.3):
    """Create LLM client for DashScope (Qwen), with timeout/retries from settings."""
    return get_chat_openai(temperature=temperature)


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


def _truncate_merge_body(text: str, max_len: int) -> str:
    """Truncate one document body for pairwise merge or single-doc overflow."""
    if len(text) <= max_len:
        return text
    omitted = len(text) - max_len
    return text[:max_len] + f"\n\n…（已截断，省略后续 {omitted} 字符）"


def _invoke_llm_markdown(llm, prompt: str) -> str:
    response = llm.invoke([HumanMessage(content=prompt)])
    return (response.content or "").strip()


def _invoke_llm_markdown_with_reason(llm, prompt: str) -> tuple[str, str]:
    response = llm.invoke([HumanMessage(content=prompt)])
    content = (response.content or "").strip()
    md = getattr(response, "response_metadata", None) or {}
    ak = getattr(response, "additional_kwargs", None) or {}
    reason = md.get("finish_reason") or ak.get("finish_reason") or md.get("stop_reason")
    return content, str(reason or "unknown")


def _estimate_merge_prompt_tokens(prompt: str) -> int:
    """Rough token estimate for merge prompt (no tokenizer dep). Tunable via settings."""
    ratio = settings.MERGE_ESTIMATED_CHARS_PER_TOKEN
    if ratio <= 0:
        ratio = 2.0
    return max(1, int(len(prompt) / ratio))


def _direct_join_merge_markdown(topic: str, last_step_outputs: list[tuple[str, str]]) -> str:
    """Concatenate each document's last-step markdown without LLM."""
    lines = [
        "# 研究报告（直接合并）",
        "",
        f"**研究主题**：{topic}",
        "",
        "> 合并最终报告提示词估算 token 超过阈值，未调用大模型；以下为各文档最后一步输出原文拼接。",
        "",
    ]
    for i, (name, content) in enumerate(last_step_outputs, 1):
        lines.append(f"## 文档 {i}：{name}")
        lines.append("")
        lines.append(content.strip())
        lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines).strip()


def _merge_final_reports(
    topic: str,
    last_step_outputs: list[tuple[str, str]],
    logs: list,
    cancel_event: Optional[threading.Event],
) -> str:
    """
    Run final merge: single merge_final call when prompt fits; else pairwise merge rounds.
    If estimated merge prompt tokens exceed MERGE_SKIP_LLM_OVER_ESTIMATED_TOKENS, skip LLM and join texts.
    Raises RuntimeError with logged message on LLM failure.
    """
    per_lens = [len(c) for _, c in last_step_outputs]
    total_body = sum(per_lens)
    _add_log(
        logs,
        f"合并输入统计：文档数 {len(last_step_outputs)}，各文档最后步骤长度 {per_lens}，正文合计约 {total_body} 字符",
        level="info",
    )

    doc_results = chr(10).join(f"### 文档：{name}\n{content}" for name, content in last_step_outputs)
    merge_prompt = get_prompt("research.scheduler.merge_final", topic=topic, doc_results=doc_results)
    est_tokens = _estimate_merge_prompt_tokens(merge_prompt)
    skip_cap = settings.MERGE_SKIP_LLM_OVER_ESTIMATED_TOKENS
    strategy = (settings.MERGE_STRATEGY or "pairwise").strip().lower()
    if strategy == "auto" and est_tokens > skip_cap:
        _add_log(
            logs,
            f"合并策略：auto->direct_join，估算提示词约 {est_tokens} tokens（> {skip_cap}），跳过模型，直接拼接各文档最后步骤（merge_prompt={len(merge_prompt)} chars, finish_reason=n/a）",
            level="warning",
        )
        final_md = _direct_join_merge_markdown(topic, last_step_outputs)
        _add_log(
            logs,
            "合并完成（直接拼接，未调用大模型）",
            agent="scheduler_merge",
            response_preview=_truncate(final_md),
        )
        return final_md

    if strategy == "direct_join":
        _add_log(
            logs,
            f"合并策略：direct_join（固定策略），merge_prompt={len(merge_prompt)} chars, est_tokens={est_tokens}, finish_reason=n/a",
            level="info",
        )
        final_md = _direct_join_merge_markdown(topic, last_step_outputs)
        _add_log(
            logs,
            "合并完成（直接拼接，未调用大模型）",
            agent="scheduler_merge",
            response_preview=_truncate(final_md),
        )
        return final_md

    merge_llm = get_merge_chat_openai(temperature=settings.FINAL_MERGE_TEMPERATURE)
    threshold = settings.MERGE_MAX_SINGLE_PROMPT_CHARS
    pair_cap = settings.MERGE_PAIR_MAX_CHARS_EACH

    def _single_merge_logged(prompt: str, strategy_note: str) -> str:
        _add_log(logs, strategy_note, level="info")
        _add_log(
            logs,
            "合并阶段 · 发送提示词",
            level="info",
            prompt_slot="research.scheduler.merge_final",
            prompt_preview=_preview_merge_prompt(prompt),
        )
        _raise_if_cancelled(cancel_event)
        try:
            merged, reason = _invoke_llm_markdown_with_reason(merge_llm, prompt)
            _add_log(
                logs,
                f"合并调用结果：strategy=single, prompt_chars={len(prompt)}, finish_reason={reason}",
                level="info",
                agent="scheduler_merge",
            )
            return merged
        except Exception as e:
            _add_log(logs, f"合并阶段失败（单次合并）：{e}", level="error")
            raise RuntimeError(f"合并阶段失败: {e}") from e

    if strategy == "single":
        final_md = _single_merge_logged(
            merge_prompt,
            f"合并策略：single（固定策略），prompt_chars={len(merge_prompt)}，阈值参数={threshold}",
        )
        _add_log(
            logs,
            "合并智能体返回",
            agent="scheduler_merge",
            response_preview=_truncate(final_md),
        )
        return final_md

    if strategy == "auto" and len(merge_prompt) <= threshold:
        final_md = _single_merge_logged(
            merge_prompt,
            f"合并策略：auto->single（提示词 {len(merge_prompt)} 字符 ≤ 阈值 {threshold}）",
        )
        _add_log(
            logs,
            "合并智能体返回",
            agent="scheduler_merge",
            response_preview=_truncate(final_md),
        )
        return final_md

    if strategy == "auto" and len(last_step_outputs) == 1:
        name, body = last_step_outputs[0]
        budget = max(threshold - 8000, 10000)
        tb = _truncate_merge_body(body, budget)
        doc_results_t = f"### 文档：{name}\n{tb}"
        merge_prompt_t = get_prompt("research.scheduler.merge_final", topic=topic, doc_results=doc_results_t)
        final_md = _single_merge_logged(
            merge_prompt_t,
            f"合并策略：仅单文档且提示词超长，已截断正文至约 {len(tb)} 字符后单次合并（原约 {len(body)} 字符）",
        )
        _add_log(
            logs,
            "合并智能体返回",
            agent="scheduler_merge",
            response_preview=_truncate(final_md),
        )
        return final_md

    _add_log(
        logs,
        (
            f"合并策略：{'pairwise(固定)' if strategy == 'pairwise' else 'auto->pairwise'}"
            f"（merge_prompt={len(merge_prompt)} chars, threshold={threshold}, pair_cap={pair_cap}）"
        ),
        level="info",
    )
    parts: list[tuple[str, str]] = list(last_step_outputs)
    round_num = 0
    try:
        while len(parts) > 1:
            round_num += 1
            (la, ca), (lb, cb) = parts[0], parts[1]
            ca_t = _truncate_merge_body(ca, pair_cap)
            cb_t = _truncate_merge_body(cb, pair_cap)
            pair_prompt = get_prompt(
                "research.scheduler.merge_pair",
                topic=topic,
                label_a=la,
                content_a=ca_t,
                label_b=lb,
                content_b=cb_t,
            )
            _add_log(
                logs,
                f"分轮合并 第{round_num}轮：「{la}」+「{lb}」（单侧最多 {pair_cap} 字符，本轮提示词约 {len(pair_prompt)} 字符）",
                level="info",
                prompt_slot="research.scheduler.merge_pair",
                prompt_preview=_preview_merge_prompt(pair_prompt),
            )
            _raise_if_cancelled(cancel_event)
            merged, reason = _invoke_llm_markdown_with_reason(merge_llm, pair_prompt)
            _add_log(
                logs,
                f"合并调用结果：strategy=pairwise, round={round_num}, prompt_chars={len(pair_prompt)}, finish_reason={reason}",
                level="info",
                agent="scheduler_merge",
            )
            merged_label = f"{la}+{lb}"
            parts = [(merged_label, merged)] + parts[2:]
        final_md = parts[0][1]
    except RuntimeError:
        raise
    except Exception as e:
        _add_log(logs, f"合并阶段失败（分轮两两合并）：{e}", level="error")
        raise RuntimeError(f"合并阶段失败: {e}") from e

    if round_num == 0:
        _add_log(
            logs,
            "合并阶段：仅单份文档，未调用合并模型；最终报告为该文档最后一步输出（写入 final.md）",
            level="info",
        )
    else:
        _add_log(
            logs,
            "合并智能体返回",
            agent="scheduler_merge",
            response_preview=_truncate(final_md),
        )
    return final_md


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
    llm = _get_llm(temperature=settings.ROUTE_TEMPERATURE)
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
    md = getattr(response, "response_metadata", None) or {}
    ak = getattr(response, "additional_kwargs", None) or {}
    finish_reason = str(md.get("finish_reason") or ak.get("finish_reason") or md.get("stop_reason") or "unknown")
    text = response.content.strip()
    if logs:
        _add_log(
            logs,
            f"路由智能体返回（prompt_chars={len(prompt)}, finish_reason={finish_reason}）",
            agent="scheduler_route",
            response_preview=_truncate(text),
        )
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

            if step_idx == 0:
                need_doc, reason = True, "首步强制引用原始文档"
                _add_log(
                    logs,
                    "首步策略：跳过路由模型，强制引用原文",
                    level="info",
                    document=doc_label,
                    step_index=step_idx + 1,
                    step_total=len(steps),
                    need_collection_document=True,
                )
            else:
                need_doc, reason = _route_need_collection_document(
                    topic=topic,
                    step_content=step_content,
                    step_index=step_idx,
                    total_steps=len(steps),
                    doc_label=doc_label,
                    is_first_step=False,
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
                        level=str(evt.get("level", "info")),
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
    final_md = _merge_final_reports(topic, last_step_outputs, logs, cancel_event)
    _add_log(logs, f"合并完成，最终报告 {len(final_md)} 字符", level="info")

    final_path = job_output_dir / "final.md"
    final_path.write_text(final_md, encoding="utf-8")
    _add_log(logs, "最终报告已保存到 final.md", level="info")

    return final_md, str(job_output_dir.resolve())
