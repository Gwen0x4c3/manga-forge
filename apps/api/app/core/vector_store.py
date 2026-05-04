from __future__ import annotations

from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams

from app.config import settings


class QdrantVectorStore:
    def __init__(self):
        self._client: AsyncQdrantClient | None = None

    @property
    def client(self) -> AsyncQdrantClient:
        if self._client is None:
            self._client = AsyncQdrantClient(
                url=settings.QDRANT_URL,
                api_key=settings.QDRANT_API_KEY or None,
            )
        return self._client

    async def ensure_collection(self, collection_name: str | None = None) -> None:
        name = collection_name or settings.QDRANT_COLLECTION
        collections = await self.client.get_collections()
        existing = [c.name for c in collections.collections]
        if name not in existing:
            await self.client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=1536, distance=Distance.COSINE),
            )

    async def upsert_vectors(
        self,
        points: list[dict[str, Any]],
        collection_name: str | None = None,
    ) -> None:
        name = collection_name or settings.QDRANT_COLLECTION
        await self.ensure_collection(name)
        qdrant_points = []
        for p in points:
            qdrant_points.append(
                PointStruct(
                    id=p["id"],
                    vector=p["vector"],
                    payload=p.get("payload", {}),
                )
            )
        await self.client.upsert(collection_name=name, points=qdrant_points)

    async def search(
        self,
        query_vector: list[float],
        limit: int = 5,
        project_id: str | None = None,
        collection_name: str | None = None,
    ) -> list[dict[str, Any]]:
        name = collection_name or settings.QDRANT_COLLECTION
        query_filter = None
        if project_id:
            query_filter = Filter(
                must=[FieldCondition(key="project_id", match=MatchValue(value=project_id))]
            )
        results = await self.client.query_points(
            collection_name=name,
            query=query_vector,
            limit=limit,
            query_filter=query_filter,
        )
        return [{"id": str(p.id), "score": p.score, "payload": p.payload} for p in results.points]

    async def delete_by_project(self, project_id: str, collection_name: str | None = None) -> None:
        name = collection_name or settings.QDRANT_COLLECTION
        await self.client.delete(
            collection_name=name,
            points_selector=Filter(
                must=[FieldCondition(key="project_id", match=MatchValue(value=project_id))]
            ),
        )


vector_store = QdrantVectorStore()
