"""Retrieval service: vector search + rerank."""
from typing import List, Optional

from langchain_core.messages import HumanMessage

from app.services.vector_store import VectorStore
from app.services.rerank import rerank_documents
from app.services.llm_factory import get_chat_openai


def search_and_rerank(
    collection_id: str,
    query: str,
    top_k: int = 10,
    rerank_top_n: Optional[int] = None,
) -> List[dict]:
    """
    Search vector store and rerank results.
    Returns list of {content, score, document_id, metadata}.
    """
    store = VectorStore(collection_id)
    raw_results = store.search(query, top_k=top_k * 2)  # Fetch more for reranking

    if not raw_results:
        return []

    documents = [r["content"] for r in raw_results]
    rerank_n = rerank_top_n or min(top_k, len(documents))
    reranked = rerank_documents(query, documents, top_n=rerank_n)

    results = []
    for content, score, orig_idx in reranked:
        meta = raw_results[orig_idx]
        results.append({
            "content": content,
            "score": score,
            "document_id": meta["document_id"],
            "metadata": meta.get("metadata", {}),
        })

    return results


def summarize_vector_results(query: str, results: List[dict], *, snippet_chars: int = 1600, context_chars: int = 10000) -> str:
    """Use LLM to summarize reranked chunks in relation to the user query."""
    if not results:
        return ""
    parts: list[str] = []
    for i, r in enumerate(results[:10], 1):
        text = str(r.get("content", ""))[:snippet_chars]
        parts.append(f"[{i}] {text}")
    ctx = "\n\n".join(parts)[:context_chars]
    prompt = (
        "你是检索助手。根据下面按相关性排序的文档片段，用 2～4 句中文说明这些片段与用户查询的关系；"
        "不要编造片段中不存在的事实；若片段不足以判断请明确说明。\n\n"
        f"用户查询：{query}\n\n文档片段：\n{ctx}"
    )
    try:
        llm = get_chat_openai(temperature=0.2)
        return str(llm.invoke([HumanMessage(content=prompt)]).content or "").strip()
    except Exception:
        return ""
