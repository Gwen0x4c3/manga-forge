from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.episode import Episode
from app.models.episode_memory import EpisodeMemory
from app.models.generated_image import GeneratedImage
from app.models.generation_run import GenerationRun
from app.models.pit import Pit
from app.models.project import Project

logger = logging.getLogger(__name__)

async def create_generation_run(
    db: AsyncSession,
    episode_id: str,
    stage: str,
    backend: str | None = None,
    model: str | None = None,
    params: dict | None = None,
    prompt: str | None = None,
    retrieved_context: dict | None = None,
) -> GenerationRun:
    run = GenerationRun(
        id=str(uuid.uuid4()),
        episode_id=episode_id,
        stage=stage,
        backend=backend,
        model=model,
        params=params,
        prompt=prompt,
        retrieved_context=retrieved_context,
        status="queued",
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def has_active_run(db: AsyncSession, episode_id: str, stage: str) -> bool:
    result = await db.execute(
        select(GenerationRun).where(
            GenerationRun.episode_id == episode_id,
            GenerationRun.stage == stage,
            GenerationRun.status.in_(["queued", "running"]),
        )
    )
    return result.scalar_one_or_none() is not None


async def update_generation_run(
    db: AsyncSession,
    run_id: str,
    status: str,
    error: str | None = None,
    commit_message: str | None = None,
) -> GenerationRun | None:
    result = await db.execute(select(GenerationRun).where(GenerationRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        return None
    run.status = status
    run.error = error
    if commit_message is not None:
        run.commit_message = commit_message
    if status in ("succeeded", "failed"):
        run.finished_at = datetime.now()
    await db.commit()
    await db.refresh(run)
    return run


async def save_episode_understanding(
    db: AsyncSession,
    episode_id: str,
    understanding: dict,
) -> EpisodeMemory:
    """Store the full understanding dict as the episode's summary memory.

    The recent-window reader expects content.summary / content.state_changes.
    """
    memory = EpisodeMemory(episode_id=episode_id, type="summary", content=understanding)
    db.add(memory)
    await db.commit()
    return memory


async def save_storyboard(
    db: AsyncSession,
    episode_id: str,
    storyboard: dict,
) -> EpisodeMemory:
    memory = EpisodeMemory(
        id=str(uuid.uuid4()),
        episode_id=episode_id,
        type="storyboard_json",
        content=storyboard,
    )
    db.add(memory)
    await db.commit()
    await db.refresh(memory)
    return memory


async def update_episode_status(
    db: AsyncSession,
    episode_id: str,
    status: str,
) -> Episode | None:
    result = await db.execute(select(Episode).where(Episode.id == episode_id))
    episode = result.scalar_one_or_none()
    if not episode:
        return None
    episode.status = status
    await db.commit()
    await db.refresh(episode)
    return episode


async def update_project_long_summary(
    db: AsyncSession,
    project_id: str,
    new_episode_summary: str,
) -> str | None:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        return None
    existing = project.long_summary or ""
    if existing:
        project.long_summary = existing + "\n\n" + new_episode_summary
    else:
        project.long_summary = new_episode_summary
    await db.commit()
    await db.refresh(project)
    return project.long_summary


async def save_generated_image(
    db: AsyncSession,
    generation_run_id: str,
    episode_id: str,
    panel_id: str | None,
    image_path: str,
    meta: dict | None = None,
) -> GeneratedImage:
    image = GeneratedImage(
        id=str(uuid.uuid4()),
        generation_run_id=generation_run_id,
        episode_id=episode_id,
        panel_id=panel_id,
        image_path=image_path,
        meta=meta,
    )
    db.add(image)
    await db.commit()
    await db.refresh(image)
    return image


async def get_generated_images(
    db: AsyncSession,
    episode_id: str,
) -> list[GeneratedImage]:
    result = await db.execute(
        select(GeneratedImage).where(GeneratedImage.episode_id == episode_id)
    )
    return list(result.scalars().all())


async def get_layout_result(
    db: AsyncSession,
    episode_id: str,
) -> EpisodeMemory | None:
    result = await db.execute(
        select(EpisodeMemory).where(
            EpisodeMemory.episode_id == episode_id,
            EpisodeMemory.type == "layout_result",
        ).order_by(EpisodeMemory.created_at.desc())
    )
    return result.scalar_one_or_none()


def _normalize_name(name: str) -> str:
    return "".join(ch.lower() for ch in name if ch.isalnum())


def _names_match(a: str, b: str) -> bool:
    """Same-name heuristic: exact, containment, or high string similarity.
    Catches alias cases like "Alice" vs "Alice Margatroid" without embeddings."""
    na, nb = _normalize_name(a), _normalize_name(b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    from difflib import SequenceMatcher

    return SequenceMatcher(None, na, nb).ratio() >= 0.88


async def record_character_sightings(
    db: AsyncSession,
    project_id: str,
    episode_id: str,
    sightings: list[dict],
) -> None:
    """Cross-episode character tracking: mark linked assets as appearing in this episode."""
    if not sightings:
        return
    asset_ids = {s.get("asset_id") for s in sightings if s.get("asset_id")}
    if not asset_ids:
        return
    result = await db.execute(select(Asset).where(Asset.project_id == project_id, Asset.id.in_(asset_ids)))
    for asset in result.scalars().all():
        # reassign a new dict: in-place mutation of JSON columns is not change-tracked
        asset.episode_ids = {**(asset.episode_ids or {}), episode_id: True}
    await db.commit()


async def auto_discover_assets(
    db: AsyncSession,
    project_id: str,
    episode_id: str,
    new_assets: list[dict],
) -> list[Asset]:
    """Register newly discovered assets, merging into existing ones by name.

    Embeddings are only used for near-duplicate detection when an embedding
    model is configured; name matching works standalone.
    """
    from app.core.llm import embeddings_configured, get_embeddings

    use_embeddings = embeddings_configured()
    existing_result = await db.execute(select(Asset).where(Asset.project_id == project_id))
    existing_assets = list(existing_result.scalars().all())

    assets = []
    for asset_data in new_assets:
        asset_name = asset_data.get("name", "")
        asset_description = asset_data.get("description", "")
        asset_type = asset_data.get("asset_type", "character")
        visual_tags = asset_data.get("visual_tags", [])

        matched_asset = None
        # 1. same-type name match (embedding-free)
        for existing in existing_assets:
            if existing.type == asset_type and _names_match(existing.name, asset_name):
                matched_asset = existing
                break
        # 2. embedding similarity for cross-language name variants
        new_embedding = None
        text_parts = [asset_name, asset_description, " ".join(str(t) for t in visual_tags)]
        new_text = " ".join(p for p in text_parts if p)
        if matched_asset is None and use_embeddings and new_text.strip():
            try:
                embeddings = await get_embeddings([new_text])
                if embeddings:
                    new_embedding = embeddings[0]
                    best_sim, best_asset = 0.0, None
                    for existing in existing_assets:
                        if existing.type == asset_type and existing.embedding:
                            sim = _cosine_similarity(new_embedding, existing.embedding)
                            if sim > best_sim:
                                best_sim, best_asset = sim, existing
                    if best_sim >= 0.9 and best_asset:
                        matched_asset = best_asset
            except Exception:
                logger.warning("Embedding-based asset matching failed, using name matching only", exc_info=True)

        if matched_asset is not None:
            # merge: record appearance, keep the richer description, union visual tags
            # reassign a new dict: in-place mutation of JSON columns is not change-tracked
            matched_asset.episode_ids = {**(matched_asset.episode_ids or {}), episode_id: True}
            if asset_description and len(asset_description) > len(matched_asset.description or ""):
                matched_asset.description = asset_description
            if visual_tags:
                tags = dict(matched_asset.tags or {})
                tags["visual_tags"] = list(dict.fromkeys([*tags.get("visual_tags", []), *visual_tags]))
                matched_asset.tags = tags
            assets.append(matched_asset)
            continue

        asset = Asset(
            id=str(uuid.uuid4()),
            project_id=project_id,
            type=asset_type,
            name=asset_name,
            description=asset_description,
            tags={"visual_tags": visual_tags},
            embedding=new_embedding,
            episode_ids={episode_id: True},
        )
        db.add(asset)
        existing_assets.append(asset)
        assets.append(asset)

    await db.commit()
    return assets


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


async def auto_discover_pits(
    db: AsyncSession,
    project_id: str,
    episode_id: str,
    pit_discoveries: list[dict],
) -> list[Pit]:
    """Register newly discovered foreshadowing/pits, skipping near-duplicates of open pits."""
    from difflib import SequenceMatcher

    open_result = await db.execute(select(Pit).where(Pit.project_id == project_id, Pit.status == "open"))
    open_pits = list(open_result.scalars().all())

    pits: list[Pit] = []
    for pit_data in pit_discoveries:
        description = pit_data.get("description", "")
        if not description.strip():
            continue
        duplicate = next(
            (
                p
                for p in open_pits + pits
                if SequenceMatcher(None, _normalize_name(p.description or ""), _normalize_name(description)).ratio()
                >= 0.85
            ),
            None,
        )
        if duplicate is not None:
            continue
        pit = Pit(
            id=str(uuid.uuid4()),
            project_id=project_id,
            title=description[:255],
            description=description,
            priority={"low": 0, "medium": 5, "high": 10}.get(pit_data.get("priority", "medium"), 5),
            introduced_episode_id=episode_id,
            trigger_hint=pit_data.get("trigger_hint"),
            status="open",
        )
        db.add(pit)
        pits.append(pit)
    await db.commit()
    return pits


async def resolve_pits(
    db: AsyncSession,
    project_id: str,
    episode_id: str,
    pit_ids: list[str],
) -> list[Pit]:
    """Mark pits as resolved by this episode."""
    if not pit_ids:
        return []
    result = await db.execute(
        select(Pit).where(Pit.project_id == project_id, Pit.id.in_(pit_ids), Pit.status == "open")
    )
    resolved = []
    for pit in result.scalars().all():
        pit.status = "resolved"
        pit.resolved_episode_id = episode_id
        resolved.append(pit)
    await db.commit()
    return resolved
