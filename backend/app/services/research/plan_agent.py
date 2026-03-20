"""Research plan generation agent: generates steps from topic + document names."""
import json
import re
import uuid
from typing import Callable, Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from app.core.settings import settings
from app.services.prompt_registry import get_prompt
from app.services.research.tools import (
    get_collection_document_names,
    MAX_DOC_NAMES_IN_PROMPT,
)


def _get_llm(temperature: float = 0.3):
    """Create LLM client for DashScope (Qwen)."""
    import os
    api_key = settings.DASHSCOPE_API_KEY or os.getenv("DASHSCOPE_API_KEY", "")
    return ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        temperature=temperature,
    )


def generate_research_plan(
    collection_id: str,
    topic: str,
    on_log: Optional[Callable[[str], None]] = None,
) -> dict:
    """
    Generate research plan steps using LLM.
    Input: collection_id, topic.
    Injects document names from collection into prompt.
    Returns plan dict (plan_id, topic, steps, markdown, collection_id).
    """
    llm = _get_llm()
    doc_names = get_collection_document_names(collection_id)
    doc_list_str = ""
    if doc_names:
        display_names = [d[1] for d in doc_names[:MAX_DOC_NAMES_IN_PROMPT]]
        doc_list_str = "\n文档集中包含以下文档，制定步骤时可参考：\n" + "\n".join(f"- {n}" for n in display_names)
        if len(doc_names) > MAX_DOC_NAMES_IN_PROMPT:
            doc_list_str += f"\n（共 {len(doc_names)} 个文档，仅列出前 {MAX_DOC_NAMES_IN_PROMPT} 个）"

    prompt = get_prompt("research.plan_generation", topic=topic, doc_list_str=doc_list_str)
    response = llm.invoke([HumanMessage(content=prompt)])
    content = response.content.strip()

    try:
        match = re.search(r'\[[\s\S]*\]', content)
        if match:
            steps_raw = json.loads(match.group())
        else:
            steps_raw = [
                s.strip()
                for s in content.split("\n")
                if s.strip()
                and s.strip().startswith(
                    ("1", "2", "3", "4", "5", "6", "7", "8", "9", "一", "二", "三", "四", "五", "六", "七", "八", "九", "①", "②", "③", "④", "⑤")
                )
            ]
            if not steps_raw:
                steps_raw = [content]
    except json.JSONDecodeError:
        steps_raw = [line.strip() for line in content.split("\n") if line.strip()][:8]

    steps = [
        {"index": i, "content": s if isinstance(s, str) else str(s), "status": "pending"}
        for i, s in enumerate(steps_raw)
    ]
    plan_id = str(uuid.uuid4())
    plan = {
        "plan_id": plan_id,
        "collection_id": collection_id,
        "topic": topic,
        "steps": steps,
        "markdown": f"# 研究计划：{topic}\n\n" + "\n".join(f"{i+1}. {s['content']}" for i, s in enumerate(steps)),
    }
    return plan
