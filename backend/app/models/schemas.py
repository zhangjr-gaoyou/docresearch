"""Pydantic schemas for API request/response."""
from pydantic import BaseModel, Field, HttpUrl
from typing import Optional


# --- Collections ---
class CollectionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


class CollectionResponse(BaseModel):
    id: str
    name: str


class DocumentInfo(BaseModel):
    id: str
    filename: str
    file_type: str


class CollectionCrawlRequest(BaseModel):
    url: HttpUrl


# --- Search ---
class SearchRequest(BaseModel):
    collection_id: str
    query: str
    top_k: int = Field(default=10, ge=1, le=100)


class SearchResultItem(BaseModel):
    content: str
    score: float
    document_id: str
    metadata: Optional[dict] = None


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    llm_summary: Optional[str] = None


class RerankRequest(BaseModel):
    query: str
    documents: list[str]
    top_n: Optional[int] = None


class RerankResultItem(BaseModel):
    content: str
    score: float
    index: int


class RerankResponse(BaseModel):
    results: list[RerankResultItem]


# --- Research ---
class ResearchProjectCreateRequest(BaseModel):
    collection_id: str
    title: str = Field(..., min_length=1, max_length=200)
    topic: str = Field(..., min_length=1, max_length=2000)


class ResearchPlanGenerateRequest(BaseModel):
    collection_id: str
    topic: str
    plan_id: Optional[str] = None


class ResearchStep(BaseModel):
    index: int
    content: str
    status: Optional[str] = "pending"  # pending, running, success, failed


class ResearchPlanResponse(BaseModel):
    plan_id: str
    topic: str
    steps: list[ResearchStep]
    markdown: Optional[str] = None
    collection_id: Optional[str] = None
    title: Optional[str] = None


class ResearchPlanUpdateRequest(BaseModel):
    steps: list[ResearchStep]


class ResearchJobCreateRequest(BaseModel):
    collection_id: str
    plan_id: str
    topic: str


class ResearchLogEntry(BaseModel):
    time: str
    message: str
    level: str = "info"  # info, success, error
    document: Optional[str] = None
    document_count: Optional[int] = None
    doc_index: Optional[int] = None
    doc_total: Optional[int] = None
    char_count: Optional[int] = None
    chunk_index: Optional[int] = None
    chunk_total: Optional[int] = None
    step_index: Optional[int] = None
    step_total: Optional[int] = None
    step_count: Optional[int] = None
    need_collection_document: Optional[bool] = None
    output_path: Optional[str] = None
    agent: Optional[str] = None  # scheduler_route, scheduler_merge, step_execution, etc.
    response_preview: Optional[str] = None  # truncated LLM response
    prompt_slot: Optional[str] = None  # e.g. research.scheduler.routing
    prompt_preview: Optional[str] = None  # truncated user/system prompt sent to LLM
    tool_name: Optional[str] = None  # Python-side IO helper name
    tool_detail: Optional[str] = None  # short JSON or text describing tool I/O


class ResearchJobResponse(BaseModel):
    job_id: str
    status: str  # pending, running, completed, failed
    steps: list[ResearchStep]
    result_markdown: Optional[str] = None
    progress: Optional[str] = None
    output_path: Optional[str] = None  # 输出目录路径（Markdown 文件保存位置）
    logs: Optional[list[ResearchLogEntry]] = None  # 执行日志
    started_at: Optional[str] = None  # ISO 时间，列表与详情用
    title: Optional[str] = None  # 研究项目标题（列表展示；无则前端可用 topic）


# --- Knowledge Extraction ---
class KnowledgeJobCreateRequest(BaseModel):
    collection_id: str


class KnowledgeLogEntry(BaseModel):
    time: str
    message: str
    level: str = "info"
    document: Optional[str] = None
    step: Optional[str] = None
    detail: Optional[str] = None


class KnowledgeJobResponse(BaseModel):
    job_id: str
    collection_id: str
    status: str
    progress: Optional[str] = None
    logs: list[KnowledgeLogEntry] = []
    started_at: Optional[str] = None
    updated_at: Optional[str] = None


class KnowledgeResultItem(BaseModel):
    id: str
    collection_id: str
    document_id: str
    document_name: str
    result_type: str  # summary / structure / knowledge_point / graph_node / graph_edge
    title: str
    content: str
    tags: list[str] = []
    extra: Optional[dict] = None
    created_at: str
    updated_at: str


class KnowledgeResultCreateRequest(BaseModel):
    collection_id: str
    document_id: str
    document_name: str
    result_type: str
    title: str
    content: str
    tags: list[str] = []
    extra: Optional[dict] = None


class KnowledgeResultUpdateRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[list[str]] = None
    extra: Optional[dict] = None


class KnowledgeGraphResponse(BaseModel):
    nodes: list[dict]
    edges: list[dict]


class KnowledgeRetrieveRequest(BaseModel):
    collection_id: str
    query: str
    top_k: int = Field(default=8, ge=1, le=30)


class KnowledgeCitationItem(BaseModel):
    layer: str
    document_id: Optional[str] = None
    document_name: Optional[str] = None
    section_path: Optional[str] = None
    score: float = 0.0
    content: str
    metadata: Optional[dict] = None


class KnowledgeRetrieveLogItem(BaseModel):
    time: str
    message: str
    level: str = "info"


class KnowledgeRetrieveResponse(BaseModel):
    answer: str
    route: str
    citations: list[KnowledgeCitationItem]
    retrieved_chunks: list[dict]
    logs: list[KnowledgeRetrieveLogItem] = []


# --- Prompts ---
class PromptCreateRequest(BaseModel):
    slot_key: str
    title: str = Field(..., min_length=1, max_length=200)
    content: str


class PromptUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    content: Optional[str] = None


class PromptResponse(BaseModel):
    id: str
    slot_key: str
    title: str
    content: str
    published: bool
    created_at: str
    updated_at: str


class SlotMetaResponse(BaseModel):
    slot_key: str
    name: str
    placeholders: list[str]
