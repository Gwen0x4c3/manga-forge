from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.branch import Branch
from app.models.episode import Episode
from app.models.episode_memory import EpisodeMemory
from app.models.pit import Pit
from app.models.project import Project
from app.schemas.branch import (
    AssetDiffItem,
    BranchCreate,
    DiffRequest,
    DiffResponse,
    EpisodeDiffItem,
    ForkRequest,
    MergeRequest,
    MergeResponse,
    PitDiffItem,
)


async def list_branches(db: AsyncSession, project_id: str) -> list[Branch]:
    result = await db.execute(select(Branch).where(Branch.project_id == project_id))
    return result.scalars().all()


async def create_branch(db: AsyncSession, project_id: str, data: BranchCreate) -> Branch:
    branch = Branch(project_id=project_id, **data.model_dump())
    db.add(branch)
    await db.commit()
    await db.refresh(branch)
    return branch


async def get_branch(db: AsyncSession, branch_id: str) -> Branch | None:
    result = await db.execute(select(Branch).where(Branch.id == branch_id))
    return result.scalar_one_or_none()


async def delete_branch(db: AsyncSession, branch: Branch) -> None:
    await db.delete(branch)
    await db.commit()


async def get_branch_episode_count(db: AsyncSession, branch_id: str) -> int:
    result = await db.execute(
        select(func.count()).select_from(Episode).where(Episode.branch_id == branch_id)
    )
    return result.scalar() or 0


async def get_branch_latest_episode_number(db: AsyncSession, branch_id: str) -> Decimal | None:
    result = await db.execute(
        select(func.max(Episode.number)).where(Episode.branch_id == branch_id)
    )
    return result.scalar()


async def fork_from_episode(db: AsyncSession, project_id: str, data: ForkRequest) -> Branch:
    episode_result = await db.execute(
        select(Episode).where(Episode.id == data.episode_id, Episode.project_id == project_id)
    )
    episode = episode_result.scalar_one_or_none()
    if not episode:
        raise ValueError("Source episode not found")

    branch = Branch(
        project_id=project_id,
        name=data.branch_name,
        description=data.description,
        is_default=False,
        base_branch_id=episode.branch_id,
        base_episode_id=episode.id,
    )
    db.add(branch)
    await db.flush()

    source_episodes_result = await db.execute(
        select(Episode).where(
            Episode.branch_id == episode.branch_id,
            Episode.number <= episode.number,
        ).order_by(Episode.number.asc())
    )
    source_episodes = source_episodes_result.scalars().all()

    for src_ep in source_episodes:
        new_ep = Episode(
            project_id=project_id,
            branch_id=branch.id,
            number=src_ep.number,
            label=src_ep.label,
            title=src_ep.title,
            source=src_ep.source,
            status=src_ep.status,
            category=src_ep.category,
            parent_episode_id=src_ep.parent_episode_id,
        )
        db.add(new_ep)
        await db.flush()

        mem_result = await db.execute(
            select(EpisodeMemory).where(EpisodeMemory.episode_id == src_ep.id)
        )
        memories = mem_result.scalars().all()
        for mem in memories:
            new_mem = EpisodeMemory(
                episode_id=new_ep.id,
                type=mem.type,
                content=mem.content,
            )
            db.add(new_mem)

    await db.commit()
    await db.refresh(branch)
    return branch


async def diff_branches(db: AsyncSession, project_id: str, data: DiffRequest) -> DiffResponse:
    source_branch = await get_branch(db, data.source_branch_id)
    target_branch = await get_branch(db, data.target_branch_id)
    if not source_branch or not target_branch:
        raise ValueError("Source or target branch not found")

    episode_diffs = await _diff_episodes(
        db, project_id, data.source_branch_id, data.target_branch_id, data.episode_number
    )
    asset_diffs = await _diff_assets(db, project_id, data.source_branch_id, data.target_branch_id)
    pit_diffs = await _diff_pits(db, project_id, data.source_branch_id, data.target_branch_id)
    canon_diff = await _diff_canon(db, project_id)

    return DiffResponse(
        episodes=episode_diffs,
        assets=asset_diffs,
        pits=pit_diffs,
        canon_diff=canon_diff,
    )


async def _diff_episodes(
    db: AsyncSession,
    project_id: str,
    source_branch_id: str,
    target_branch_id: str,
    episode_number: Decimal | None = None,
) -> list[EpisodeDiffItem]:
    source_query = select(Episode).where(
        Episode.project_id == project_id,
        Episode.branch_id == source_branch_id,
    )
    target_query = select(Episode).where(
        Episode.project_id == project_id,
        Episode.branch_id == target_branch_id,
    )

    if episode_number is not None:
        source_query = source_query.where(Episode.number == episode_number)
        target_query = target_query.where(Episode.number == episode_number)

    source_result = await db.execute(source_query.order_by(Episode.number.asc()))
    target_result = await db.execute(target_query.order_by(Episode.number.asc()))
    source_episodes = source_result.scalars().all()
    target_episodes = target_result.scalars().all()

    target_map: dict[Decimal, Episode] = {ep.number: ep for ep in target_episodes}
    source_map: dict[Decimal, Episode] = {ep.number: ep for ep in source_episodes}

    all_numbers = sorted(set(list(source_map.keys()) + list(target_map.keys())))

    diffs: list[EpisodeDiffItem] = []
    for num in all_numbers:
        src_ep = source_map.get(num)
        tgt_ep = target_map.get(num)

        src_summary = None
        tgt_summary = None
        if src_ep:
            mem_result = await db.execute(
                select(EpisodeMemory).where(
                    EpisodeMemory.episode_id == src_ep.id,
                    EpisodeMemory.type == "summary",
                )
            )
            mem = mem_result.scalar_one_or_none()
            src_summary = mem.content.get("summary") if mem and isinstance(mem.content, dict) else None

        if tgt_ep:
            mem_result = await db.execute(
                select(EpisodeMemory).where(
                    EpisodeMemory.episode_id == tgt_ep.id,
                    EpisodeMemory.type == "summary",
                )
            )
            mem = mem_result.scalar_one_or_none()
            tgt_summary = mem.content.get("summary") if mem and isinstance(mem.content, dict) else None

        diffs.append(EpisodeDiffItem(
            number=num,
            label=src_ep.label if src_ep else (tgt_ep.label if tgt_ep else ""),
            source_status=src_ep.status if src_ep else None,
            target_status=tgt_ep.status if tgt_ep else None,
            title_source=src_ep.title if src_ep else None,
            title_target=tgt_ep.title if tgt_ep else None,
            summary_source=src_summary,
            summary_target=tgt_summary,
        ))

    return diffs


async def _diff_assets(
    db: AsyncSession,
    project_id: str,
    source_branch_id: str,
    target_branch_id: str,
) -> list[AssetDiffItem]:
    source_ep_result = await db.execute(
        select(Episode.id).where(Episode.branch_id == source_branch_id)
    )
    target_ep_result = await db.execute(
        select(Episode.id).where(Episode.branch_id == target_branch_id)
    )
    source_ep_ids = [row[0] for row in source_ep_result.all()]
    target_ep_ids = [row[0] for row in target_ep_result.all()]

    source_pit_ids: set[str] = set()
    if source_ep_ids:
        source_pit_result = await db.execute(
            select(Pit.id).where(Pit.introduced_episode_id.in_(source_ep_ids))
        )
        source_pit_ids = {row[0] for row in source_pit_result.all()}

    target_pit_ids: set[str] = set()
    if target_ep_ids:
        target_pit_result = await db.execute(
            select(Pit.id).where(Pit.introduced_episode_id.in_(target_ep_ids))
        )
        target_pit_ids = {row[0] for row in target_pit_result.all()}

    all_assets_result = await db.execute(
        select(Asset).where(Asset.project_id == project_id)
    )
    all_assets = all_assets_result.scalars().all()

    diffs: list[AssetDiffItem] = []
    for asset in all_assets:
        in_source = asset.id in source_pit_ids
        in_target = asset.id in target_pit_ids
        diffs.append(AssetDiffItem(
            name=asset.name,
            asset_type=asset.type,
            in_source=in_source,
            in_target=in_target,
            description_source=asset.description if in_source else None,
            description_target=asset.description if in_target else None,
        ))

    return diffs


async def _diff_pits(
    db: AsyncSession,
    project_id: str,
    source_branch_id: str,
    target_branch_id: str,
) -> list[PitDiffItem]:
    source_ep_result = await db.execute(
        select(Episode.id).where(Episode.branch_id == source_branch_id)
    )
    target_ep_result = await db.execute(
        select(Episode.id).where(Episode.branch_id == target_branch_id)
    )
    source_ep_ids = [row[0] for row in source_ep_result.all()]
    target_ep_ids = [row[0] for row in target_ep_result.all()]

    source_pits: list[Pit] = []
    if source_ep_ids:
        source_pits_result = await db.execute(
            select(Pit).where(
                Pit.project_id == project_id,
                Pit.introduced_episode_id.in_(source_ep_ids),
            )
        )
        source_pits = source_pits_result.scalars().all()

    target_pits: list[Pit] = []
    if target_ep_ids:
        target_pits_result = await db.execute(
            select(Pit).where(
                Pit.project_id == project_id,
                Pit.introduced_episode_id.in_(target_ep_ids),
            )
        )
        target_pits = target_pits_result.scalars().all()

    pit_map: dict[str, dict] = {}
    for pit in source_pits:
        pit_map[pit.title] = {"status_source": pit.status, "status_target": None}
    for pit in target_pits:
        if pit.title in pit_map:
            pit_map[pit.title]["status_target"] = pit.status
        else:
            pit_map[pit.title] = {"status_source": None, "status_target": pit.status}

    diffs: list[PitDiffItem] = []
    for title, statuses in pit_map.items():
        diffs.append(PitDiffItem(
            title=title,
            status_source=statuses["status_source"],
            status_target=statuses["status_target"],
        ))

    return diffs


async def _diff_canon(db: AsyncSession, project_id: str) -> dict | None:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project or not project.canon_rules:
        return None
    return {"canon_rules": project.canon_rules}


async def merge_branches(db: AsyncSession, project_id: str, data: MergeRequest) -> MergeResponse:
    source_branch = await get_branch(db, data.source_branch_id)
    target_branch = await get_branch(db, data.target_branch_id)
    if not source_branch or not target_branch:
        raise ValueError("Source or target branch not found")

    merged_items: list[str] = []
    skipped_items: list[str] = []
    errors: list[str] = []

    for item in data.items:
        try:
            if item.action == "skip":
                skipped_items.append(item.source_id)
                continue

            if item.item_type == "episode":
                await _merge_episode(db, project_id, data.target_branch_id, item.source_id, merged_items, errors)
            elif item.item_type == "asset":
                await _merge_asset(db, project_id, item.source_id, merged_items, errors)
            elif item.item_type == "pit":
                await _merge_pit(db, project_id, data.target_branch_id, item.source_id, merged_items, errors)
            elif item.item_type == "canon_rule":
                await _merge_canon_rule(db, project_id, item.source_id, merged_items, errors)
        except Exception as e:
            errors.append(f"{item.item_type}:{item.source_id} - {str(e)}")

    await db.commit()
    return MergeResponse(merged_items=merged_items, skipped_items=skipped_items, errors=errors)


async def _merge_episode(
    db: AsyncSession,
    project_id: str,
    target_branch_id: str,
    source_episode_id: str,
    merged_items: list[str],
    errors: list[str],
) -> None:
    result = await db.execute(
        select(Episode).where(Episode.id == source_episode_id, Episode.project_id == project_id)
    )
    source_episode = result.scalar_one_or_none()
    if not source_episode:
        errors.append(f"episode:{source_episode_id} - source episode not found")
        return

    existing_result = await db.execute(
        select(Episode).where(
            Episode.branch_id == target_branch_id,
            Episode.number == source_episode.number,
        )
    )
    existing = existing_result.scalar_one_or_none()

    if existing:
        existing.title = source_episode.title
        existing.status = source_episode.status
        existing.label = source_episode.label
        existing.category = source_episode.category
    else:
        next_num_result = await db.execute(
            select(func.max(Episode.number)).where(
                Episode.project_id == project_id,
                Episode.branch_id == target_branch_id,
            )
        )
        max_num = next_num_result.scalar()
        next_number = Decimal("1") if max_num is None else Decimal(int(max_num) + 1)

        new_episode = Episode(
            project_id=project_id,
            branch_id=target_branch_id,
            number=next_number,
            label=source_episode.label,
            title=source_episode.title,
            source=source_episode.source,
            status=source_episode.status,
            category=source_episode.category,
            parent_episode_id=source_episode.id,
        )
        db.add(new_episode)
        await db.flush()

        mem_result = await db.execute(
            select(EpisodeMemory).where(EpisodeMemory.episode_id == source_episode.id)
        )
        memories = mem_result.scalars().all()
        for mem in memories:
            new_mem = EpisodeMemory(
                episode_id=new_episode.id,
                type=mem.type,
                content=mem.content,
            )
            db.add(new_mem)

    merged_items.append(source_episode_id)


async def _merge_asset(
    db: AsyncSession,
    project_id: str,
    source_asset_id: str,
    merged_items: list[str],
    errors: list[str],
) -> None:
    result = await db.execute(
        select(Asset).where(Asset.id == source_asset_id, Asset.project_id == project_id)
    )
    asset = result.scalar_one_or_none()
    if not asset:
        errors.append(f"asset:{source_asset_id} - asset not found")
        return
    merged_items.append(source_asset_id)


async def _merge_pit(
    db: AsyncSession,
    project_id: str,
    target_branch_id: str,
    source_pit_id: str,
    merged_items: list[str],
    errors: list[str],
) -> None:
    result = await db.execute(
        select(Pit).where(Pit.id == source_pit_id, Pit.project_id == project_id)
    )
    pit = result.scalar_one_or_none()
    if not pit:
        errors.append(f"pit:{source_pit_id} - pit not found")
        return

    source_ep_result = await db.execute(
        select(Episode).where(Episode.id == pit.introduced_episode_id)
    )
    source_ep = source_ep_result.scalar_one_or_none()

    if source_ep:
        target_ep_result = await db.execute(
            select(Episode).where(
                Episode.branch_id == target_branch_id,
                Episode.project_id == project_id,
                Episode.number == source_ep.number,
            )
        )
        matching_ep = target_ep_result.scalar_one_or_none()

        if not matching_ep:
            first_ep_result = await db.execute(
                select(Episode).where(
                    Episode.branch_id == target_branch_id,
                    Episode.project_id == project_id,
                ).order_by(Episode.number.asc()).limit(1)
            )
            matching_ep = first_ep_result.scalar_one_or_none()

        if matching_ep:
            pit.introduced_episode_id = matching_ep.id

    merged_items.append(source_pit_id)


async def _merge_canon_rule(
    db: AsyncSession,
    project_id: str,
    source_id: str,
    merged_items: list[str],
    errors: list[str],
) -> None:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        errors.append(f"canon_rule:{source_id} - project not found")
        return
    merged_items.append(source_id)
