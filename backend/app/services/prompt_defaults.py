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
    "research.step_execution.first_step": """你是一个文档分析专家。请根据以下研究主题和当前研究步骤，执行本步骤并输出结构化的 Markdown 结果。

研究主题：{topic}

当前步骤（步骤 {step_index}）：{step_content}
{doc_section}

【重要：首步规则】
- 这是首个步骤，必须以引用的原始文档内容为主要依据进行提取与结构化分析。
- 不得引入文档外知识，不得编造；无法从文档得出时写“文档未提及”。

要求：
1. 严格按当前步骤的说明执行
2. 输出 Markdown 格式
3. 只输出分析结果，不要其他说明
""",
    "research.step_execution.later_step": """你是一个文档分析专家。请根据以下研究主题和当前研究步骤，执行本步骤并输出结构化的 Markdown 结果。

研究主题：{topic}

当前步骤（步骤 {step_index}）：{step_content}
{prior_section}
{doc_section}

【重要：后续步骤规则】
- 优先基于“上一步骤执行结果”推进当前分析。
- 若已提供引用文档内容，仅作为补充证据使用；未提供则不得臆测补全。
- 不得引入文档外知识，不得编造；无法从材料得出时写“文档未提及”。

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
    "knowledge.extract.summary": """你是知识提取助手。请基于文档内容提取文档概要。

研究主题：{topic}
文档内容：
---
{document_text}
---

输出 JSON：
{{"title":"文档概要","summary":"不超过300字","tags":["标签1","标签2"]}}
仅输出 JSON。""",
    "knowledge.extract.structure": """你是知识提取助手。请提取文档结构（章节、段落说明与段落正文）。

研究主题：{topic}
文档内容：
---
{document_text}
---

输出 JSON：
{{"title":"文档结构","sections":[{{"id":"sec_1","name":"章节名","summary":"章节说明"}}],"paragraph_notes":[{{"name":"段落名","section_ref":"sec_1","summary":"段落说明","content":"段落正文（尽量保留原文关键句，可适度压缩）"}}]}}
要求：
1) sections 必须输出稳定 id（建议 sec_序号）。
2) paragraph_notes 必须输出 section_ref，并引用 sections.id。
3) paragraph_notes 必须输出 content 字段，不可省略。
4) content 优先引用原文段落关键句，避免仅重复 summary。
5) summary 控制在 50-100 字，content 可更长但保持可读。
仅输出 JSON。""",
    "knowledge.extract.key_points": """你是知识提取助手。请抽取需要特别标注的知识点并打标签。

研究主题：{topic}
文档内容：
---
{document_text}
---

输出 JSON：
{{"title":"知识点","points":[{{"point":"知识点内容","tags":["标签A","标签B"]}}]}}
仅输出 JSON。""",
    "knowledge.extract.domain": """你是业务领域识别助手。请根据文档概要与正文，识别该文档对应的业务领域。

研究主题：{topic}
文档概要（JSON）：
{summary_json}

文档内容：
---
{document_text}
---

输出 JSON：
{{"domain":"业务领域名称","description":"简短说明","confidence":0.0}}
仅输出 JSON。""",
    "knowledge.extract.ontology": """你是知识图谱本体设计助手。请基于业务领域生成参考实体类别和标准谓语。

研究主题：{topic}
业务领域（JSON）：
{domain_json}

文档概要（JSON）：
{summary_json}

文档内容：
---
{document_text}
---

输出 JSON：
{{"entity_types":["类型A","类型B"],"predicates":["谓语A","谓语B"],"notes":"可选说明"}}
仅输出 JSON。""",
    "knowledge.extract.graph_candidates": """你是知识图谱候选抽取助手。请先从文档中抽取候选实体与候选关系，输出尽可能完整但不要编造。

研究主题：{topic}
业务领域（JSON）：
{domain_json}

领域本体（JSON）：
{ontology_json}

文档概要（JSON）：
{summary_json}

文档内容：
---
{document_text}
---

已提取知识点（JSON）：
{points_json}

输出 JSON：
{{"title":"知识图谱候选","entities":[{{"id":"e1","label":"实体名","type":"候选类型","confidence":0.0,"source_spans":[{{"text":"证据片段","start":-1,"end":-1}}]}}],"relationships":[{{"source":"e1","target":"e2","relation":"候选谓语","confidence":0.0,"evidence_text":"证据文本","evidence_span":{{"start":-1,"end":-1}}}}]}}
仅输出 JSON。""",
    "knowledge.extract.schema_align": """你是知识图谱 schema 对齐助手。请将候选实体/关系严格对齐到领域本体。

研究主题：{topic}
业务领域（JSON）：
{domain_json}

领域本体（JSON）：
{ontology_json}

候选抽取结果（JSON）：
{candidates_json}

文档内容（用于校验）：
---
{document_text}
---

要求：
1) 节点类型尽量映射到 ontology_json.entity_types，无法映射可用 "Entity" 并给 align_reason。
2) 关系谓语尽量映射到 ontology_json.predicates，无法映射可用 "RELATED_TO" 并给 align_reason。
3) 不可支持或明显错误的关系可丢弃，并在 schema_proposals 中给出可扩展建议。

输出 JSON：
{{"title":"知识图谱对齐","nodes":[{{"id":"e1","label":"实体名","type":"规范类型","original_type":"原类型","align_reason":"matched","confidence":0.0,"aliases":[],"source_spans":[]}}],"edges":[{{"source":"e1","target":"e2","relation":"规范谓语","original_relation":"原谓语","align_reason":"matched","confidence":0.0,"evidence_text":"证据文本","evidence_span":{{"start":-1,"end":-1}}}}],"schema_proposals":[{{"kind":"predicate","name":"候选谓语","reason":"扩展建议原因","confidence":0.0}}]}}
仅输出 JSON。""",
    "knowledge.extract.entity_resolve": """你是知识图谱实体归一助手。请对已对齐实体做同文档别名归一，输出 canonical_map。

研究主题：{topic}
业务领域（JSON）：
{domain_json}

已对齐图谱（JSON）：
{aligned_json}

文档内容（用于校验）：
---
{document_text}
---

输出 JSON：
{{"canonical_map":{{"原实体id":"规范实体id"}},"merged_aliases":0}}
仅输出 JSON。""",
    "knowledge.extract.graph": """你是知识图谱提取助手。请从文档与知识点中抽取图谱节点和关系。

研究主题：{topic}
业务领域（JSON）：
{domain_json}

领域本体（JSON）：
{ontology_json}

文档概要（JSON）：
{summary_json}

文档内容：
---
{document_text}
---

已提取知识点（JSON）：
{points_json}

候选抽取结果（JSON）：
{candidates_json}

schema 对齐结果（JSON）：
{aligned_json}

实体归一结果（JSON）：
{resolved_json}

【本体约束（必须遵守）】
- 节点类型优先使用 ontology_json.entity_types 中的类别；若无法匹配再使用 "Entity"。
- 关系谓语优先使用 ontology_json.predicates 中的谓语；若无法匹配统一映射为 "RELATED_TO"。
- source/target 必须引用 nodes 中已存在的 id，禁止悬空边。
- 仅保留可由文档内容支持的关系，不得编造。

输出 JSON：
{{"title":"知识图谱","nodes":[{{"id":"n1","label":"节点","type":"Entity"}}],"edges":[{{"source":"n1","target":"n2","relation":"关联"}}]}}
仅输出 JSON。""",
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
    "research.step_execution.first_step": {
        "name": "步骤执行-首步提示",
        "placeholders": ["topic", "step_content", "step_index", "doc_section"],
    },
    "research.step_execution.later_step": {
        "name": "步骤执行-后续提示",
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
    "knowledge.extract.summary": {
        "name": "知识提取-文档概要",
        "placeholders": ["topic", "document_text"],
    },
    "knowledge.extract.structure": {
        "name": "知识提取-文档结构",
        "placeholders": ["topic", "document_text"],
    },
    "knowledge.extract.key_points": {
        "name": "知识提取-知识点与标签",
        "placeholders": ["topic", "document_text"],
    },
    "knowledge.extract.domain": {
        "name": "知识提取-业务领域识别",
        "placeholders": ["topic", "summary_json", "document_text"],
    },
    "knowledge.extract.ontology": {
        "name": "知识提取-领域本体生成",
        "placeholders": ["topic", "domain_json", "summary_json", "document_text"],
    },
    "knowledge.extract.graph_candidates": {
        "name": "知识提取-图谱候选抽取",
        "placeholders": ["topic", "domain_json", "ontology_json", "summary_json", "document_text", "points_json"],
    },
    "knowledge.extract.schema_align": {
        "name": "知识提取-schema对齐",
        "placeholders": ["topic", "domain_json", "ontology_json", "candidates_json", "document_text"],
    },
    "knowledge.extract.entity_resolve": {
        "name": "知识提取-实体归一",
        "placeholders": ["topic", "domain_json", "aligned_json", "document_text"],
    },
    "knowledge.extract.graph": {
        "name": "知识提取-知识图谱",
        "placeholders": [
            "topic",
            "domain_json",
            "ontology_json",
            "summary_json",
            "document_text",
            "points_json",
            "candidates_json",
            "aligned_json",
            "resolved_json",
        ],
    },
}
