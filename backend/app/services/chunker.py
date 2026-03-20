"""Text chunking for embedding."""
from dataclasses import dataclass
from typing import Optional

from app.core.settings import settings


@dataclass
class Chunk:
    """Text chunk with metadata."""
    content: str
    index: int
    document_id: str
    metadata: Optional[dict] = None


def chunk_text(
    text: str,
    document_id: str,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
) -> list[Chunk]:
    """Split text into overlapping chunks."""
    size = chunk_size or settings.CHUNK_SIZE
    overlap = chunk_overlap or settings.CHUNK_OVERLAP

    chunks: list[Chunk] = []
    start = 0
    index = 0

    while start < len(text):
        end = start + size
        chunk_text_slice = text[start:end]

        # Try to break at sentence or newline
        if end < len(text):
            last_newline = chunk_text_slice.rfind("\n")
            last_period = chunk_text_slice.rfind("。")
            last_dot = chunk_text_slice.rfind(".")
            break_point = max(last_newline, last_period, last_dot)
            if break_point > size // 2:
                end = start + break_point + 1
                chunk_text_slice = text[start:end]

        content = chunk_text_slice.strip()
        if content:
            chunks.append(
                Chunk(
                    content=content,
                    index=index,
                    document_id=document_id,
                    metadata={"start": start, "end": end},
                )
            )
            index += 1

        start = end - overlap
        if start >= len(text):
            break

    return chunks
