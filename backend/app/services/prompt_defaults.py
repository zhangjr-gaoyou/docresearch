"""Built-in prompt templates and slot metadata."""

BUILTIN_PROMPTS = {
    "research.plan_generation": """你是一个专业的研究助手。请针对以下研究主题，制定一个详细的研究计划。
研究主题：{topic}
{doc_list_str}

要求：
1. 将研究计划分解为5-8个具体可执行的步骤
2. 每个步骤应该清晰、可操作
3. 步骤之间应有逻辑顺序
4. 步骤应可结合文档集内容执行
5. 输出格式为JSON数组，每个元素是一个步骤的文本描述

只输出JSON数组，不要其他内容。例如：
["步骤1：...", "步骤2：...", "步骤3：..."]
""",
    "research.scheduler.routing": """你是一个研究调度助手。判断当前研究步骤是否需要引用文档集内的文档全文。

研究主题：{topic}
当前步骤（{step_index}/{total_steps}）：{step_content}
文档：{doc_label}
{bias}

请以 JSON 格式回答，仅输出 JSON，不要其他文字：
{{"need_collection_document": true 或 false, "reason": "简短理由"}}
""",
    "research.scheduler.merge_final": """请将以下多份文档的研究分析结果（各文档最后一步）合并为一份完整的研究报告。

研究主题：{topic}

各文档分析结果：
---
{doc_results}
---

输出合并后的完整Markdown报告，按研究主题组织，结构清晰，综合各文档观点，避免简单罗列。""",
    "research.step_execution.main": """你是一个文档分析专家。请根据以下研究主题和当前研究步骤，执行本步骤并输出结构化的 Markdown 结果。

研究主题：{topic}

当前步骤（步骤 {step_index}）：{step_content}
{prior_section}
{doc_section}

要求：
1. 严格按当前步骤的说明执行
2. 输出 Markdown 格式
3. 只输出分析结果，不要其他说明
""",
    "research.step_execution.map_chunk": """分析以下文档片段（第{chunk_index}部分，共{chunk_total}部分），根据研究主题和当前步骤提取信息。

研究主题：{topic}
当前步骤：{step_content}
{prior_section}

文档片段：
---
{chunk}
---

输出该片段的 Markdown 分析结果。""",
    "research.step_execution.map_merge": """请将以下多个片段的分析结果合并为一份完整的 Markdown 报告。

研究主题：{topic}
当前步骤：{step_content}

各片段结果：
---
{partial_results}
---

输出合并后的完整 Markdown，结构清晰，避免重复。""",
    "search.rerank_instruct": "Given a web search query, retrieve relevant passages that answer the query.",
}

SLOT_META = {
    "research.plan_generation": {"name": "研究计划生成", "placeholders": ["topic", "doc_list_str"]},
    "research.scheduler.routing": {
        "name": "调度路由判断",
        "placeholders": ["topic", "step_content", "step_index", "total_steps", "doc_label", "bias"],
    },
    "research.scheduler.merge_final": {"name": "合并最终报告", "placeholders": ["topic", "doc_results"]},
    "research.step_execution.main": {
        "name": "步骤执行主提示",
        "placeholders": ["topic", "step_content", "step_index", "prior_section", "doc_section"],
    },
    "research.step_execution.map_chunk": {
        "name": "步骤执行-分块分析",
        "placeholders": ["topic", "step_content", "prior_section", "chunk", "chunk_index", "chunk_total"],
    },
    "research.step_execution.map_merge": {
        "name": "步骤执行-分块合并",
        "placeholders": ["topic", "step_content", "partial_results"],
    },
    "search.rerank_instruct": {"name": "检索重排指令", "placeholders": []},
}
