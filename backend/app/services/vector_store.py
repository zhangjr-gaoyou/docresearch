"""FAISS vector store for document embeddings."""
import json
import pickle
import uuid
from pathlib import Path
from typing import List, Optional

import faiss
import numpy as np

from app.core.settings import settings
from app.services.embedding import embed_texts
from app.services.chunker import Chunk


class VectorStore:
    """Local FAISS-based vector store with metadata."""

    def __init__(self, collection_id: str):
        self.collection_id = collection_id
        self.index_dir = settings.INDEX_DIR / collection_id
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.index_dir / "index.faiss"
        self.meta_path = self.index_dir / "metadata.pkl"
        self._index: Optional[faiss.IndexFlatL2] = None
        self._metadata: List[dict] = []

    def _load(self):
        """Load index and metadata from disk."""
        if self._index is not None:
            return
        if self.index_path.exists():
            self._index = faiss.read_index(str(self.index_path))
            with open(self.meta_path, "rb") as f:
                self._metadata = pickle.load(f)
        else:
            self._index = None
            self._metadata = []

    def add_chunks(self, chunks: List[Chunk]) -> None:
        """Embed chunks and add to index."""
        if not chunks:
            return

        texts = [c.content for c in chunks]
        vectors = embed_texts(texts)
        vectors_np = np.array(vectors, dtype=np.float32)

        if self._index is None:
            dim = vectors_np.shape[1]
            self._index = faiss.IndexFlatL2(dim)
            self._metadata = []

        self._index.add(vectors_np)
        for i, chunk in enumerate(chunks):
            meta = {
                "content": chunk.content,
                "document_id": chunk.document_id,
                "index": chunk.index,
                "metadata": chunk.metadata or {},
            }
            self._metadata.append(meta)

        self._save()

    def search(self, query: str, top_k: int = 10) -> List[dict]:
        """Search for similar chunks."""
        self._load()
        if self._index is None:
            return []

        query_vectors = embed_texts([query])
        query_np = np.array(query_vectors, dtype=np.float32)
        distances, indices = self._index.search(query_np, min(top_k, self._index.ntotal))

        results = []
        for i, idx in enumerate(indices[0]):
            if idx < 0 or idx >= len(self._metadata):
                continue
            meta = self._metadata[idx].copy()
            meta["score"] = float(1.0 / (1.0 + distances[0][i]))  # Convert distance to similarity
            results.append(meta)

        return results

    def _save(self):
        """Save index and metadata to disk."""
        if self._index is None:
            return
        faiss.write_index(self._index, str(self.index_path))
        with open(self.meta_path, "wb") as f:
            pickle.dump(self._metadata, f)

    @property
    def count(self) -> int:
        """Return number of vectors in index."""
        self._load()
        return self._index.ntotal if self._index else 0

    def delete_needs_reembed(self, document_id: str) -> bool:
        """True if deleting this document would require re-embedding remaining chunks."""
        self._load()
        if not self._metadata:
            return False
        chunks_for_doc = sum(1 for m in self._metadata if m.get("document_id") == document_id)
        other = len(self._metadata) - chunks_for_doc
        return chunks_for_doc > 0 and other > 0

    def delete_by_document_id(self, document_id: str) -> int:
        """Remove all vectors for document_id by rebuilding index from remaining chunks.

        Returns number of removed chunk rows. If no chunks existed for this id, returns 0.
        """
        self._load()
        if self._index is None or not self._metadata:
            return 0

        remaining = [m for m in self._metadata if m.get("document_id") != document_id]
        removed_count = len(self._metadata) - len(remaining)
        if removed_count == 0:
            return 0

        if not remaining:
            self._index = None
            self._metadata = []
            self.index_path.unlink(missing_ok=True)
            self.meta_path.unlink(missing_ok=True)
            return removed_count

        texts = [m["content"] for m in remaining]
        vectors = embed_texts(texts)
        vectors_np = np.array(vectors, dtype=np.float32)
        dim = vectors_np.shape[1]
        new_index = faiss.IndexFlatL2(dim)
        new_index.add(vectors_np)
        self._index = new_index
        self._metadata = remaining
        self._save()
        return removed_count


def get_collection_index_path(collection_id: str) -> Path:
    """Get index directory for a collection."""
    return settings.INDEX_DIR / collection_id
