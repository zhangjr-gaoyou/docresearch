"""Neo4j graph persistence and query for knowledge extraction."""

from __future__ import annotations

from typing import Optional

from app.core.settings import settings

try:
    from neo4j import GraphDatabase
except Exception:  # pragma: no cover - optional at runtime
    GraphDatabase = None


class Neo4jGraphStore:
    def __init__(self):
        self.uri = settings.NEO4J_URI.strip()
        self.user = settings.NEO4J_USER.strip()
        self.password = settings.NEO4J_PASSWORD
        self.database = settings.NEO4J_DATABASE.strip() or "neo4j"

    def enabled(self) -> bool:
        return bool(self.uri and self.user and self.password and GraphDatabase is not None)

    def _driver(self):
        if not self.enabled():
            return None
        return GraphDatabase.driver(self.uri, auth=(self.user, self.password))

    def upsert_graph(
        self,
        *,
        collection_id: str,
        document_id: str,
        nodes: list[dict],
        edges: list[dict],
    ) -> None:
        drv = self._driver()
        if drv is None:
            return
        with drv.session(database=self.database) as sess:
            for n in nodes:
                node_id = str(n.get("id", "")).strip()
                if not node_id:
                    continue
                sess.run(
                    """
                    MERGE (x:KnowledgeNode {id: $id, collection_id: $collection_id})
                    SET x.label = $label,
                        x.type = $type,
                        x.document_id = $document_id
                    """,
                    id=node_id,
                    collection_id=collection_id,
                    label=str(n.get("label", "")),
                    type=str(n.get("type", "")),
                    document_id=document_id,
                )
            for e in edges:
                src = str(e.get("source", "")).strip()
                dst = str(e.get("target", "")).strip()
                if not src or not dst:
                    continue
                rel = str(e.get("relation", "")).strip() or "RELATED_TO"
                sess.run(
                    """
                    MATCH (a:KnowledgeNode {id: $src, collection_id: $collection_id})
                    MATCH (b:KnowledgeNode {id: $dst, collection_id: $collection_id})
                    MERGE (a)-[r:KnowledgeEdge {relation: $relation, document_id: $document_id}]->(b)
                    """,
                    src=src,
                    dst=dst,
                    relation=rel,
                    document_id=document_id,
                    collection_id=collection_id,
                )
        drv.close()

    def read_graph(self, *, collection_id: str, limit: int = 300) -> dict:
        drv = self._driver()
        if drv is None:
            return {"nodes": [], "edges": []}
        with drv.session(database=self.database) as sess:
            nodes_q = sess.run(
                """
                MATCH (n:KnowledgeNode {collection_id: $collection_id})
                RETURN n.id AS id, n.label AS label, n.type AS type, n.document_id AS document_id
                LIMIT $limit
                """,
                collection_id=collection_id,
                limit=limit,
            )
            nodes = [dict(r) for r in nodes_q]
            edges_q = sess.run(
                """
                MATCH (a:KnowledgeNode {collection_id: $collection_id})-[r:KnowledgeEdge]->(b:KnowledgeNode {collection_id: $collection_id})
                RETURN a.id AS source, b.id AS target, r.relation AS relation, r.document_id AS document_id
                LIMIT $limit
                """,
                collection_id=collection_id,
                limit=limit,
            )
            edges = [dict(r) for r in edges_q]
        drv.close()
        return {"nodes": nodes, "edges": edges}
