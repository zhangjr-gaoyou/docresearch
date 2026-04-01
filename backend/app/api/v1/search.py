"""Search API."""
from fastapi import APIRouter, HTTPException

from app.models.schemas import SearchRequest, SearchResponse, SearchResultItem, RerankRequest, RerankResponse, RerankResultItem
from app.services.vector_store import VectorStore
from app.services.retrieval import search_and_rerank, summarize_vector_results
from app.services.rerank import rerank_documents
from app.services.collection_store import get_collection

router = APIRouter()


@router.post("", response_model=SearchResponse)
def search_endpoint(body: SearchRequest):
    """Vector search with optional rerank."""
    if not get_collection(body.collection_id):
        raise HTTPException(status_code=404, detail="Collection not found")

    results = search_and_rerank(
        collection_id=body.collection_id,
        query=body.query,
        top_k=body.top_k,
    )

    summary = summarize_vector_results(body.query, results) if results else ""

    return SearchResponse(
        results=[
            SearchResultItem(
                content=r["content"],
                score=r["score"],
                document_id=r["document_id"],
                metadata=r.get("metadata"),
            )
            for r in results
        ],
        llm_summary=summary or None,
    )


@router.post("/rerank", response_model=RerankResponse)
def rerank_endpoint(body: RerankRequest):
    """Rerank a list of documents by query."""
    if not body.documents:
        return RerankResponse(results=[])

    reranked = rerank_documents(
        query=body.query,
        documents=body.documents,
        top_n=body.top_n,
    )

    return RerankResponse(
        results=[
            RerankResultItem(content=content, score=score, index=idx)
            for content, score, idx in reranked
        ]
    )
