from __future__ import annotations

import logging
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PointStruct,
    Range,
    VectorParams,
)

from app.config import settings

logger = logging.getLogger(__name__)


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

    async def ensure_collection(self, collection_name: str | None = None, vector_size: int = 1536) -> None:
        name = collection_name or settings.QDRANT_COLLECTION
        collections = await self.client.get_collections()
        existing = [c.name for c in collections.collections]
        if name not in existing:
            await self.client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )
            return

        # Verify dimension matches; if an embedding model changed dimensions, recreate cleanly.
        try:
            info = await self.client.get_collection(name)
            params = getattr(getattr(info, "config", None), "params", None)
            vectors_cfg = getattr(params, "vectors", None)
            existing_size = getattr(vectors_cfg, "size", None)
            if existing_size and existing_size != vector_size:
                logger.warning(
                    "Qdrant collection '%s' vector size mismatch (%s != %s); recreating collection",
                    name,
                    existing_size,
                    vector_size,
                )
                await self.client.delete_collection(name)
                await self.client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
                )
        except Exception:
            logger.debug("Could not inspect Qdrant collection dimension", exc_info=True)

    async def upsert_vectors(
        self,
        points: list[dict[str, Any]],
        collection_name: str | None = None,
    ) -> None:
        if not points:
            return
        name = collection_name or settings.QDRANT_COLLECTION
        dim = len(points[0]["vector"])
        await self.ensure_collection(name, vector_size=dim)
        qdrant_points = [
            PointStruct(
                id=p["id"],
                vector=p["vector"],
                payload=p.get("payload", {}),
            )
            for p in points
        ]
        await self.client.upsert(collection_name=name, points=qdrant_points)

    async def search(
        self,
        query_vector: list[float],
        limit: int = 5,
        project_id: str | None = None,
        collection_name: str | None = None,
        episode_ids: list[str] | None = None,
        max_episode_number: float | None = None,
    ) -> list[dict[str, Any]]:
        name = collection_name or settings.QDRANT_COLLECTION
        collections = await self.client.get_collections()
        if name not in [c.name for c in collections.collections]:
            return []
        must_conditions = []
        if project_id:
            must_conditions.append(FieldCondition(key="project_id", match=MatchValue(value=project_id)))
        if episode_ids is not None:
            if not episode_ids:
                return []
            must_conditions.append(FieldCondition(key="episode_id", match=MatchAny(any=list(episode_ids))))
        if max_episode_number is not None:
            must_conditions.append(FieldCondition(key="episode_number", range=Range(lte=float(max_episode_number))))
        query_filter = Filter(must=must_conditions) if must_conditions else None
        results = await self.client.query_points(
            collection_name=name,
            query=query_vector,
            limit=limit,
            query_filter=query_filter,
        )
        return [{"id": str(p.id), "score": p.score, "payload": p.payload} for p in results.points]

    async def delete_by_episode(self, episode_id: str, collection_name: str | None = None) -> None:
        name = collection_name or settings.QDRANT_COLLECTION
        try:
            collections = await self.client.get_collections()
            if name not in [c.name for c in collections.collections]:
                return
            await self.client.delete(
                collection_name=name,
                points_selector=Filter(must=[FieldCondition(key="episode_id", match=MatchValue(value=episode_id))]),
            )
        except Exception:
            logger.debug("Skipping Qdrant delete_by_episode (store unavailable)", exc_info=True)

    async def delete_by_project(self, project_id: str, collection_name: str | None = None) -> None:
        name = collection_name or settings.QDRANT_COLLECTION
        try:
            await self.client.delete(
                collection_name=name,
                points_selector=Filter(must=[FieldCondition(key="project_id", match=MatchValue(value=project_id))]),
            )
        except Exception:
            logger.debug("Skipping Qdrant delete_by_project (store unavailable)", exc_info=True)


vector_store = QdrantVectorStore()
