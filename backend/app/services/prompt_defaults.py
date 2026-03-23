"""Built-in prompt templates and slot metadata."""

BUILTIN_PROMPTS = {
    "research.plan_generation": """你是一个专业的研究助手。请针对以下研究主题，制定一个详细的研究计划。
研究主题：{topic}
{doc_list_str}

【重要：文档边界】
- 后续执行研究时，分析必须严格基于文档集中已上传文档的正文内容。
- 请制定「仅通过阅读、提取、归纳上述文档即可推进」的步骤；不要依赖文档外常识来充当事实依据。
- 若某问题在文档中可能无法覆盖，步骤中应明确写「若文档未涉及则标注文档未提及，不得编造」类要求。

要求：
1. 将研究计划分解为5-8个具体可执行的步骤
2. 每个步骤应该清晰、可操作
3. 步骤之间应有逻辑顺序
4. 步骤应可结合文档集内容执行，且符合上文「文档边界」
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

【重要：仅基于上文材料】
- 合并时只可使用上述「各文档分析结果」中已出现的信息进行归纳与组织。
- 不得引入上述文本中未出现的具体事实、数据、人名、日期或外部知识；禁止编造。
- 若某结论在材料中找不到依据，应明确写「文档未提及」或不予断言，不可臆测补全。

输出合并后的完整Markdown报告，按研究主题组织，结构清晰，综合各文档观点，避免简单罗列。""",
    "research.scheduler.merge_pair": """请将以下两份研究分析片段（各来自不同文档的最后步骤输出）合并为一份连贯的 Markdown 报告。

研究主题：{topic}

### 文档 A：{label_a}
{content_a}

### 文档 B：{label_b}
{content_b}

【重要：仅基于上文】
- 只使用上述两段中已出现的信息进行归纳、去重与结构化；不得引入外部知识或编造事实。
- 保留表格、列表等 Markdown 结构；若两段有重复观点，合并为一条表述。

输出合并后的完整 Markdown。""",
    "research.step_execution.main": """你是一个文档分析专家。请根据以下研究主题和当前研究步骤，执行本步骤并输出结构化的 Markdown 结果。

研究主题：{topic}

当前步骤（步骤 {step_index}）：{step_content}
{prior_section}
{doc_section}

【重要：仅基于所给材料】
- 你的依据只能是：本提示中的「研究主题」、上一步骤结果（若有）、以及「引用的文档内容」或「未引用全文」说明所对应范围内已给出的正文。
- 凡具体事实、数据、观点须能在上述材料中找到对应或合理归纳；材料未出现的内容不得当作事实陈述，应写「文档未提及」或说明无法从文档得出。
- 禁止使用文档外的常识、网络知识或推测来填补空白；禁止编造。

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

【重要：仅基于本片段与上文】
- 只根据上述「文档片段」及本提示中已给出的上一步骤摘要（若有）进行提取或归纳。
- 片段中未出现的内容不得当作本片段的结论；若无法从本片段判断，注明「本片段未提及」。
- 禁止编造、禁止使用片段外的外部知识充当本片段依据。

输出该片段的 Markdown 分析结果。""",
    "research.step_execution.map_merge": """请将以下多个片段的分析结果合并为一份完整的 Markdown 报告。

研究主题：{topic}
当前步骤：{step_content}

各片段结果：
---
{partial_results}
---

【重要：仅基于各片段结果】
- 合并时只可使用「各片段结果」中已出现的内容，不得新增具体事实或引用文档外信息。
- 若某点在各片段中均未支持，写「文档未提及」或删除该断言，禁止编造。

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
    "research.scheduler.merge_pair": {
        "name": "合并最终报告-两两合并",
        "placeholders": ["topic", "label_a", "content_a", "label_b", "content_b"],
    },
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
