from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.llm import get_embeddings
from app.models.asset import Asset
from app.models.asset_image import AssetImage
from app.schemas.asset import (
    AssetClusterGroup,
    AssetClusterItem,
    AssetClusterResponse,
    AssetCreate,
    AssetMergeRequest,
    AssetUpdate,
)

ASSET_IMAGE_KINDS = ("reference", "thumbnail", "turnaround", "lora_dataset")
_PREVIEW_PRIORITY = ("reference", "turnaround", "thumbnail", "lora_dataset")


def _attach_preview_fields(asset: Asset) -> Asset:
    imgs = list(asset.__dict__.get("images") or [])
    asset.image_count = len(imgs)  # type: ignore[attr-defined]
    if imgs:
        best = min(
            imgs,
            key=lambda i: _PREVIEW_PRIORITY.index(i.kind) if i.kind in _PREVIEW_PRIORITY else 99,
        )
        asset.preview_image_path = best.image_path  # type: ignore[attr-defined]
    else:
        asset.preview_image_path = None  # type: ignore[attr-defined]
    return asset


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
    query = select(Asset).options(selectinload(Asset.images)).where(Asset.project_id == project_id)
    count_query = select(func.count()).select_from(Asset).where(Asset.project_id == project_id)
    if asset_type:
        query = query.where(Asset.type == asset_type)
        count_query = count_query.where(Asset.type == asset_type)
    total = (await db.execute(count_query)).scalar() or 0
    query = query.order_by(Asset.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = [_attach_preview_fields(a) for a in result.scalars().all()]
    return items, total


async def create_asset(db: AsyncSession, project_id: str, data: AssetCreate) -> Asset:
    asset = Asset(project_id=project_id, **data.model_dump())
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    asset.image_count = 0  # type: ignore[attr-defined]
    asset.preview_image_path = None  # type: ignore[attr-defined]
    return asset


async def get_asset(db: AsyncSession, asset_id: str) -> Asset | None:
    result = await db.execute(select(Asset).options(selectinload(Asset.images)).where(Asset.id == asset_id).limit(1))
    asset = result.scalar_one_or_none()
    return _attach_preview_fields(asset) if asset else None


async def update_asset(db: AsyncSession, asset: Asset, data: AssetUpdate) -> Asset:
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(asset, key, value)
    await db.commit()
    refreshed = await get_asset(db, asset.id)
    return refreshed or asset


async def delete_asset(db: AsyncSession, asset: Asset) -> None:
    await db.delete(asset)
    await db.commit()


async def vectorize_asset(db: AsyncSession, asset: Asset) -> None:
    text = _build_asset_text(asset)
    if not text.strip():
        return
    embeddings = await get_embeddings([text])
    if not embeddings:
        return
    asset.embedding = embeddings[0]
    await db.commit()


async def find_similar_assets(
    db: AsyncSession, project_id: str, asset_id: str, top_k: int = 5
) -> list[AssetClusterItem]:
    asset = await get_asset(db, asset_id)
    if not asset:
        return []
    query = select(Asset).where(
        Asset.project_id == project_id,
        Asset.id != asset_id,
    )
    result = await db.execute(query)
    candidates = list(result.scalars().all())

    if asset.embedding:
        scored = []
        for candidate in candidates:
            if not candidate.embedding or len(candidate.embedding) != len(asset.embedding):
                continue
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
        if scored:
            return scored[:top_k]

    # Embedding-free fallback: string + tag overlap similarity
    from difflib import SequenceMatcher

    base_text = _build_asset_text(asset).lower()
    fallback_scored = []
    for candidate in candidates:
        cand_text = _build_asset_text(candidate).lower()
        sim = SequenceMatcher(None, base_text, cand_text).ratio()
        if candidate.type == asset.type:
            sim = min(1.0, sim + 0.1)
        fallback_scored.append(
            AssetClusterItem(
                asset_id=candidate.id,
                name=candidate.name,
                asset_type=candidate.type,
                similarity=round(sim, 4),
            )
        )
    fallback_scored.sort(key=lambda x: x.similarity, reverse=True)
    return fallback_scored[:top_k]


async def cluster_assets(
    db: AsyncSession,
    project_id: str,
    asset_type: str | None = None,
    similarity_threshold: float = 0.85,
) -> AssetClusterResponse:
    from difflib import SequenceMatcher

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
            if embeddings:
                for (asset, _), emb in zip(valid, embeddings):
                    asset.embedding = emb
                await db.commit()

    total_assets = len(assets)
    visited: set[str] = set()
    clusters: list[AssetClusterGroup] = []

    for i, asset_a in enumerate(assets):
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
        for j, asset_b in enumerate(assets):
            if j <= i or asset_b.id in visited or asset_b.type != asset_a.type:
                continue
            if asset_a.embedding and asset_b.embedding and len(asset_a.embedding) == len(asset_b.embedding):
                sim = _cosine_similarity(asset_a.embedding, asset_b.embedding)
            else:
                # Embedding-free name/alias similarity
                sim = SequenceMatcher(None, asset_a.name.lower(), asset_b.name.lower()).ratio()
                if asset_a.name.lower() in asset_b.name.lower() or asset_b.name.lower() in asset_a.name.lower():
                    sim = max(sim, 0.88)
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


async def merge_assets(db: AsyncSession, project_id: str, data: AssetMergeRequest) -> Asset:
    source_assets = []
    for sid in data.source_asset_ids:
        result = await db.execute(select(Asset).where(Asset.id == sid, Asset.project_id == project_id).limit(1))
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
    aliases = [a.name for a in source_assets if a.name != data.target_name]
    for a in source_assets:
        if a.tags:
            for k, v in a.tags.items():
                if k in merged_tags:
                    existing = merged_tags[k] if isinstance(merged_tags[k], list) else [merged_tags[k]]
                    new_vals = v if isinstance(v, list) else [v]
                    merged_tags[k] = list(dict.fromkeys(existing + new_vals))
                else:
                    merged_tags[k] = v
    if aliases:
        merged_tags["aliases"] = list(dict.fromkeys([*(merged_tags.get("aliases") or []), *aliases]))

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
    await db.flush()

    img_result = await db.execute(select(AssetImage).where(AssetImage.asset_id.in_(data.source_asset_ids)))
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

    # Remove duplicate source assets so asset gallery stays clean
    for a in source_assets:
        await db.delete(a)

    await db.commit()
    refreshed = await get_asset(db, merged_asset.id)
    return refreshed or merged_asset


async def list_asset_images(db: AsyncSession, asset_id: str) -> list[AssetImage]:
    result = await db.execute(
        select(AssetImage).where(AssetImage.asset_id == asset_id).order_by(AssetImage.created_at.asc())
    )
    return list(result.scalars().all())


async def upload_asset_image(
    db: AsyncSession,
    asset: Asset,
    data: bytes,
    filename: str,
    kind: str = "reference",
    content_type: str = "image/png",
) -> AssetImage:
    from app.config import settings
    from app.services import storage_service

    if kind not in ASSET_IMAGE_KINDS:
        raise ValueError(f"kind must be one of {ASSET_IMAGE_KINDS}")
    object_key = storage_service.generate_object_key(f"assets/{asset.id}", filename)
    storage_service.upload_file(settings.MINIO_BUCKET, object_key, data, content_type=content_type)
    image = AssetImage(
        id=str(uuid.uuid4()),
        asset_id=asset.id,
        kind=kind,
        image_path=object_key,
    )
    db.add(image)
    await db.commit()
    await db.refresh(image)
    return image


async def get_asset_image(db: AsyncSession, image_id: str) -> AssetImage | None:
    return await db.get(AssetImage, image_id)


async def delete_asset_image(db: AsyncSession, image: AssetImage) -> None:
    from app.services import storage_service

    await db.delete(image)
    await db.commit()
    try:
        from app.config import settings

        storage_service.get_minio_client().remove_object(settings.MINIO_BUCKET, image.image_path)
    except Exception:
        pass


async def crop_asset_image_from_page(
    db: AsyncSession,
    asset: Asset,
    episode_id: str,
    page_index: int,
    bbox: list[float],
    kind: str = "reference",
) -> AssetImage:
    """Crop a normalized [x1, y1, x2, y2] region from an EpisodePage and attach it to an Asset."""
    import io

    from PIL import Image

    from app.config import settings
    from app.models.episode_page import EpisodePage
    from app.services import storage_service

    if kind not in ASSET_IMAGE_KINDS:
        raise ValueError(f"kind must be one of {ASSET_IMAGE_KINDS}")
    if len(bbox) != 4:
        raise ValueError("bbox must contain 4 normalized coordinates [x1, y1, x2, y2]")

    x1, y1, x2, y2 = [max(0.0, min(1.0, float(v))) for v in bbox]
    if x2 <= x1 + 0.01 or y2 <= y1 + 0.01:
        raise ValueError("Crop rectangle is too small")

    page = (
        await db.execute(
            select(EpisodePage)
            .where(EpisodePage.episode_id == episode_id, EpisodePage.page_index == page_index)
            .limit(1)
        )
    ).scalar_one_or_none()
    if not page:
        raise LookupError(f"Page index {page_index} not found for episode {episode_id}")

    raw = storage_service.get_object_bytes(settings.MINIO_BUCKET, page.image_path)
    if not raw:
        raise LookupError("Original page image not found in storage")

    img = Image.open(io.BytesIO(raw)).convert("RGB")
    w, h = img.size
    left, top = int(round(x1 * w)), int(round(y1 * h))
    right, bottom = max(left + 8, int(round(x2 * w))), max(top + 8, int(round(y2 * h)))
    cropped = img.crop((left, top, min(w, right), min(h, bottom)))

    buf = io.BytesIO()
    cropped.save(buf, format="PNG")
    crop_bytes = buf.getvalue()

    object_key = storage_service.generate_object_key(f"assets/{asset.id}", f"crop_p{page_index}.png")
    storage_service.upload_file(settings.MINIO_BUCKET, object_key, crop_bytes, content_type="image/png")
    image = AssetImage(
        id=str(uuid.uuid4()),
        asset_id=asset.id,
        kind=kind,
        image_path=object_key,
        meta={
            "source_episode_id": episode_id,
            "page_index": page_index,
            "bbox": [round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)],
            "cropped_manually": True,
        },
    )
    db.add(image)
    asset.episode_ids = {**(asset.episode_ids or {}), episode_id: True}
    await db.commit()
    await db.refresh(image)
    return image
