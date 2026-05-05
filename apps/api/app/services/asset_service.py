from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm import get_embeddings
from app.models.asset import Asset
from app.models.asset_image import AssetImage
from app.schemas.asset import AssetClusterGroup, AssetClusterItem, AssetClusterResponse, AssetCreate, AssetMergeRequest, AssetUpdate


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _build_asset_text(asset: Asset) -> str:
    parts = [asset.name]
    if asset.description:
        parts.append(asset.description)
    if asset.tags:
        visual_tags = asset.tags.get("visual_tags", [])
        if visual_tags:
            parts.append(" ".join(str(t) for t in visual_tags))
    return " ".join(parts)


async def list_assets(
    db: AsyncSession, project_id: str, asset_type: str | None = None, page: int = 1, page_size: int = 50
):
    query = select(Asset).where(Asset.project_id == project_id)
    count_query = select(func.count()).select_from(Asset).where(Asset.project_id == project_id)
    if asset_type:
        query = query.where(Asset.type == asset_type)
        count_query = count_query.where(Asset.type == asset_type)
    total = (await db.execute(count_query)).scalar() or 0
    query = query.order_by(Asset.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return result.scalars().all(), total


async def create_asset(db: AsyncSession, project_id: str, data: AssetCreate) -> Asset:
    asset = Asset(project_id=project_id, **data.model_dump())
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return asset


async def get_asset(db: AsyncSession, asset_id: str) -> Asset | None:
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    return result.scalar_one_or_none()


async def update_asset(db: AsyncSession, asset: Asset, data: AssetUpdate) -> Asset:
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(asset, key, value)
    await db.commit()
    await db.refresh(asset)
    return asset


async def delete_asset(db: AsyncSession, asset: Asset) -> None:
    await db.delete(asset)
    await db.commit()


async def vectorize_asset(db: AsyncSession, asset: Asset) -> None:
    text = _build_asset_text(asset)
    if not text.strip():
        return
    embeddings = await get_embeddings([text])
    asset.embedding = embeddings[0]
    await db.commit()


async def find_similar_assets(
    db: AsyncSession, project_id: str, asset_id: str, top_k: int = 5
) -> list[AssetClusterItem]:
    asset = await get_asset(db, asset_id)
    if not asset or not asset.embedding:
        return []
    query = select(Asset).where(
        Asset.project_id == project_id,
        Asset.id != asset_id,
        Asset.embedding.isnot(None),
    )
    result = await db.execute(query)
    candidates = result.scalars().all()
    scored = []
    for candidate in candidates:
        sim = _cosine_similarity(asset.embedding, candidate.embedding)
        scored.append(
            AssetClusterItem(
                asset_id=candidate.id,
                name=candidate.name,
                asset_type=candidate.type,
                similarity=round(sim, 4),
            )
        )
    scored.sort(key=lambda x: x.similarity, reverse=True)
    return scored[:top_k]


async def cluster_assets(
    db: AsyncSession,
    project_id: str,
    asset_type: str | None = None,
    similarity_threshold: float = 0.85,
) -> AssetClusterResponse:
    query = select(Asset).where(Asset.project_id == project_id)
    if asset_type:
        query = query.where(Asset.type == asset_type)
    result = await db.execute(query)
    assets = list(result.scalars().all())

    need_vectorize = [a for a in assets if a.embedding is None]
    if need_vectorize:
        texts = [_build_asset_text(a) for a in need_vectorize]
        valid = [(a, t) for a, t in zip(need_vectorize, texts) if t.strip()]
        if valid:
            batch_texts = [t for _, t in valid]
            embeddings = await get_embeddings(batch_texts)
            for (asset, _), emb in zip(valid, embeddings):
                asset.embedding = emb
            await db.commit()

    assets_with_emb = [a for a in assets if a.embedding is not None]
    total_assets = len(assets)

    visited: set[str] = set()
    clusters: list[AssetClusterGroup] = []

    for i, asset_a in enumerate(assets_with_emb):
        if asset_a.id in visited:
            continue
        group_items = [
            AssetClusterItem(
                asset_id=asset_a.id,
                name=asset_a.name,
                asset_type=asset_a.type,
                similarity=1.0,
            )
        ]
        visited.add(asset_a.id)
        for j, asset_b in enumerate(assets_with_emb):
            if j <= i or asset_b.id in visited:
                continue
            sim = _cosine_similarity(asset_a.embedding, asset_b.embedding)
            if sim >= similarity_threshold:
                group_items.append(
                    AssetClusterItem(
                        asset_id=asset_b.id,
                        name=asset_b.name,
                        asset_type=asset_b.type,
                        similarity=round(sim, 4),
                    )
                )
                visited.add(asset_b.id)

        if len(group_items) > 1:
            clusters.append(
                AssetClusterGroup(
                    representative_name=asset_a.name,
                    asset_type=asset_a.type,
                    items=group_items,
                )
            )

    unclustered = total_assets - sum(len(c.items) for c in clusters)
    return AssetClusterResponse(
        clusters=clusters,
        total_assets=total_assets,
        unclustered=unclustered,
    )


async def merge_assets(
    db: AsyncSession, project_id: str, data: AssetMergeRequest
) -> Asset:
    source_assets = []
    for sid in data.source_asset_ids:
        result = await db.execute(
            select(Asset).where(Asset.id == sid, Asset.project_id == project_id)
        )
        asset = result.scalar_one_or_none()
        if not asset:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"Asset {sid} not found")
        source_assets.append(asset)

    merged_description = data.target_description
    if not merged_description:
        descriptions = [a.description for a in source_assets if a.description]
        merged_description = " | ".join(descriptions) if descriptions else None

    merged_tags: dict = {}
    for a in source_assets:
        if a.tags:
            for k, v in a.tags.items():
                if k in merged_tags:
                    existing = merged_tags[k] if isinstance(merged_tags[k], list) else [merged_tags[k]]
                    new_vals = v if isinstance(v, list) else [v]
                    merged_tags[k] = list(dict.fromkeys(existing + new_vals))
                else:
                    merged_tags[k] = v

    merged_snippets: dict = {}
    for a in source_assets:
        if a.prompt_snippets:
            for lang, text in a.prompt_snippets.items():
                if lang not in merged_snippets:
                    merged_snippets[lang] = text
                else:
                    merged_snippets[lang] = merged_snippets[lang] + " " + text

    merged_episode_ids: dict = {}
    for a in source_assets:
        if a.episode_ids:
            for key, val in a.episode_ids.items():
                if key not in merged_episode_ids:
                    merged_episode_ids[key] = val

    merged_embedding = source_assets[0].embedding

    merged_asset = Asset(
        id=str(uuid.uuid4()),
        project_id=project_id,
        type=source_assets[0].type,
        name=data.target_name,
        description=merged_description,
        tags=merged_tags if merged_tags else None,
        prompt_snippets=merged_snippets if merged_snippets else None,
        embedding=merged_embedding,
        episode_ids=merged_episode_ids if merged_episode_ids else None,
    )
    db.add(merged_asset)

    for a in source_assets:
        a.parent_asset_id = merged_asset.id

    img_result = await db.execute(
        select(AssetImage).where(AssetImage.asset_id.in_(data.source_asset_ids))
    )
    images = img_result.scalars().all()
    for img in images:
        new_img = AssetImage(
            id=str(uuid.uuid4()),
            asset_id=merged_asset.id,
            kind=img.kind,
            image_path=img.image_path,
            meta=img.meta,
        )
        db.add(new_img)

    await db.commit()
    await db.refresh(merged_asset)
    return merged_asset
