"""Retrieval service: vector search + rerank."""
from typing import List, Optional

from app.services.vector_store import VectorStore
from app.services.rerank import rerank_documents


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
