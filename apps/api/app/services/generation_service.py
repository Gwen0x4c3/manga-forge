from __future__ import annotations

import logging
import uuid
from datetime import datetime
from difflib import SequenceMatcher

from sqlalchemy import delete, select
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
    commit_message: str | None = None,
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
        commit_message=commit_message,
        status="queued",
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def has_active_run(db: AsyncSession, episode_id: str, stage: str) -> bool:
    result = await db.execute(
        select(GenerationRun)
        .where(
            GenerationRun.episode_id == episode_id,
            GenerationRun.stage == stage,
            GenerationRun.status.in_(["queued", "running"]),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def update_generation_run(
    db: AsyncSession,
    run_id: str,
    status: str,
    error: str | None = None,
    commit_message: str | None = None,
) -> GenerationRun | None:
    result = await db.execute(select(GenerationRun).where(GenerationRun.id == run_id).limit(1))
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
    """Store the full understanding dict as the episode's summary memory (replacing prior summary)."""
    await db.execute(
        delete(EpisodeMemory).where(
            EpisodeMemory.episode_id == episode_id,
            EpisodeMemory.type == "summary",
        )
    )
    memory = EpisodeMemory(id=str(uuid.uuid4()), episode_id=episode_id, type="summary", content=understanding)
    db.add(memory)
    await db.commit()
    return memory


async def save_storyboard(
    db: AsyncSession,
    episode_id: str,
    storyboard: dict,
) -> EpisodeMemory:
    """Save or replace the latest storyboard_json memory for an episode."""
    await db.execute(
        delete(EpisodeMemory).where(
            EpisodeMemory.episode_id == episode_id,
            EpisodeMemory.type == "storyboard_json",
        )
    )
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


async def get_latest_storyboard(
    db: AsyncSession,
    episode_id: str,
) -> EpisodeMemory | None:
    result = await db.execute(
        select(EpisodeMemory)
        .where(
            EpisodeMemory.episode_id == episode_id,
            EpisodeMemory.type == "storyboard_json",
        )
        .order_by(EpisodeMemory.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def update_episode_status(
    db: AsyncSession,
    episode_id: str,
    status: str,
) -> Episode | None:
    result = await db.execute(select(Episode).where(Episode.id == episode_id).limit(1))
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
    result = await db.execute(select(Project).where(Project.id == project_id).limit(1))
    project = result.scalar_one_or_none()
    if not project:
        return None
    existing = project.long_summary or ""
    project.long_summary = f"{existing}\n\n{new_episode_summary}" if existing else new_episode_summary
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
    keep_history: bool = True,
) -> GeneratedImage:
    if panel_id:
        existing_rows = (
            (
                await db.execute(
                    select(GeneratedImage).where(
                        GeneratedImage.episode_id == episode_id,
                        GeneratedImage.panel_id == panel_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        if keep_history:
            for row in existing_rows:
                row_meta = dict(row.meta or {})
                row_meta["selected"] = False
                row.meta = row_meta
        else:
            await db.execute(
                delete(GeneratedImage).where(
                    GeneratedImage.episode_id == episode_id,
                    GeneratedImage.panel_id == panel_id,
                )
            )
    final_meta = {**(meta or {}), "selected": True}
    image = GeneratedImage(
        id=str(uuid.uuid4()),
        generation_run_id=generation_run_id,
        episode_id=episode_id,
        panel_id=panel_id,
        image_path=image_path,
        meta=final_meta,
    )
    db.add(image)
    await db.commit()
    await db.refresh(image)
    return image


async def select_generated_image(
    db: AsyncSession,
    episode_id: str,
    panel_id: str,
    image_id: str,
) -> GeneratedImage | None:
    rows = (
        (
            await db.execute(
                select(GeneratedImage).where(
                    GeneratedImage.episode_id == episode_id,
                    GeneratedImage.panel_id == panel_id,
                )
            )
        )
        .scalars()
        .all()
    )
    target: GeneratedImage | None = None
    for row in rows:
        m = dict(row.meta or {})
        if row.id == image_id:
            m["selected"] = True
            target = row
        else:
            m["selected"] = False
        row.meta = m
    if not target:
        return None
    await db.commit()
    await db.refresh(target)
    return target


async def get_generated_images(
    db: AsyncSession,
    episode_id: str,
    include_candidates: bool = False,
) -> list[GeneratedImage]:
    result = await db.execute(
        select(GeneratedImage).where(GeneratedImage.episode_id == episode_id).order_by(GeneratedImage.created_at.asc())
    )
    rows = list(result.scalars().all())
    if include_candidates:
        return rows
    # Pick the explicitly selected candidate per panel_id, falling back to latest
    by_panel: dict[str, GeneratedImage] = {}
    unnamed: list[GeneratedImage] = []
    for row in rows:
        if row.panel_id:
            prev = by_panel.get(row.panel_id)
            row_selected = bool((row.meta or {}).get("selected"))
            prev_selected = bool((prev.meta or {}).get("selected")) if prev else False
            if prev is None or row_selected or not prev_selected:
                by_panel[row.panel_id] = row
        else:
            unnamed.append(row)
    return list(by_panel.values()) + unnamed


async def get_layout_result(
    db: AsyncSession,
    episode_id: str,
) -> EpisodeMemory | None:
    result = await db.execute(
        select(EpisodeMemory)
        .where(
            EpisodeMemory.episode_id == episode_id,
            EpisodeMemory.type == "layout_result",
        )
        .order_by(EpisodeMemory.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _normalize_name(name: str) -> str:
    return "".join(ch.lower() for ch in name if ch.isalnum())


_RELATIONAL_MARKERS = ("的", "の", "'s", "’s", " of ")


def _is_relational_phrase(raw: str) -> bool:
    low = (raw or "").strip().lower()
    return any(m in low for m in _RELATIONAL_MARKERS)


def _names_match(a: str, b: str, *, allow_containment: bool = True) -> bool:
    """Same-name heuristic: exact, safe containment (never on possessive/relational phrases like
    '敬一的小学同学'), or high string similarity."""
    na, nb = _normalize_name(a), _normalize_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if _is_relational_phrase(a) or _is_relational_phrase(b):
        return False
    shorter, longer = min(len(na), len(nb)), max(len(na), len(nb))
    if allow_containment and shorter >= 2 and (shorter / longer) >= 0.5 and (na in nb or nb in na):
        return True
    return SequenceMatcher(None, na, nb).ratio() >= 0.90


def _asset_matches_name(asset: Asset, candidate_name: str, candidate_aliases: list[str] | None = None) -> bool:
    known_primary = (asset.name or "").strip()
    known_aliases = [str(x).strip() for x in ((asset.tags or {}).get("aliases") or []) if str(x).strip()]
    cand_primary = (candidate_name or "").strip()
    cand_aliases = [str(x).strip() for x in (candidate_aliases or []) if str(x).strip()]

    # Primary <-> Primary allows safe containment (e.g. '藤宫' <-> '藤宫澄夏', '敬一' <-> '侄子敬一')
    if known_primary and cand_primary and _names_match(known_primary, cand_primary, allow_containment=True):
        return True
    # Primary <-> Alias allows safe containment ONLY if neither is a relational phrase
    for ka in known_aliases:
        if cand_primary and _names_match(ka, cand_primary, allow_containment=True):
            return True
    for ca in cand_aliases:
        if known_primary and _names_match(known_primary, ca, allow_containment=True):
            return True
    # Alias <-> Alias requires strict match (no loose substring containment)
    for ka in known_aliases:
        for ca in cand_aliases:
            if _names_match(ka, ca, allow_containment=False):
                return True
    return False


async def record_character_sightings(
    db: AsyncSession,
    project_id: str,
    episode_id: str,
    sightings: list[dict],
    episode_label: str | None = None,
) -> dict[str, Asset]:
    """Cross-episode character tracking: link sightings to known assets (by asset_id or name/alias),
    record appearance, and enrich speech_style / role / appearance / vital_status metadata.

    Returns mapping of normalized character name -> matched Asset.
    """
    from app.services.memory_service import normalize_vital_status

    if not sightings:
        return {}
    result = await db.execute(select(Asset).where(Asset.project_id == project_id, Asset.type == "character"))
    char_assets = list(result.scalars().all())
    by_id = {a.id: a for a in char_assets}
    matched_by_name: dict[str, Asset] = {}
    claimed_ids: set[str] = {str(s.get("asset_id")) for s in sightings if s.get("asset_id") in by_id}

    for s in sightings:
        aid = s.get("asset_id")
        name = (s.get("name") or "").strip()
        aliases = [str(x).strip() for x in (s.get("aliases") or []) if str(x).strip()]
        asset = by_id.get(aid) if aid else None
        # Only fall back to name matching if asset_id was omitted AND no other character already claimed it
        if asset is None and not aid and name:
            for cand in char_assets:
                if cand.id in claimed_ids:
                    continue
                if _asset_matches_name(cand, name, aliases):
                    asset = cand
                    claimed_ids.add(cand.id)
                    break
        if asset is None:
            continue

        asset.episode_ids = {**(asset.episode_ids or {}), episode_id: True}
        tags = dict(asset.tags or {})
        if aliases:
            existing_aliases = [str(x) for x in tags.get("aliases", [])]
            tags["aliases"] = list(dict.fromkeys([*existing_aliases, *aliases]))
        if s.get("role") and not tags.get("role"):
            tags["role"] = s["role"]
        elif s.get("role") in ("protagonist", "antagonist"):
            tags["role"] = s["role"]
        if s.get("speech_style"):
            tags["speech_style"] = str(s["speech_style"])[:300]
        if s.get("appearance"):
            tags["latest_appearance"] = str(s["appearance"])[:400]
            if not asset.description:
                asset.description = str(s["appearance"])
        vs = normalize_vital_status(s.get("vital_status"))
        if vs:
            if vs != tags.get("vital_status") and episode_label:
                tags["vital_status_episode"] = str(episode_label)
            tags["vital_status"] = vs
        asset.tags = tags
        if name:
            matched_by_name[_normalize_name(name)] = asset

    await db.commit()
    return matched_by_name


async def sync_character_vital_statuses(
    db: AsyncSession,
    project_id: str,
    episode_label: str,
    state_changes: list[dict],
) -> None:
    """Apply vital_status transitions (death, sealing, missing, injury, revival) from state_changes
    directly onto matching character Assets so their tags always reflect the latest iterative state."""
    from app.services.memory_service import infer_vital_status

    if not state_changes:
        return
    result = await db.execute(select(Asset).where(Asset.project_id == project_id, Asset.type == "character"))
    char_assets = list(result.scalars().all())
    changed = False

    for sc in state_changes:
        if not isinstance(sc, dict):
            continue
        cname = str(sc.get("character") or "").strip()
        attr = str(sc.get("attribute") or "").strip()
        after = str(sc.get("after") or "").strip()
        reason = str(sc.get("reason") or "").strip()
        inferred = infer_vital_status(attr, after)
        if not cname or not inferred:
            continue
        asset = next((a for a in char_assets if _asset_matches_name(a, cname)), None)
        if not asset:
            continue
        tags = dict(asset.tags or {})
        tags["vital_status"] = inferred
        tags["vital_status_episode"] = str(episode_label)
        tags["vital_status_note"] = (f"{after}（{reason}）" if reason else after)[:240]
        asset.tags = tags
        changed = True

    if changed:
        await db.commit()


async def record_asset_sightings(
    db: AsyncSession,
    project_id: str,
    episode_id: str,
    asset_sightings: list[dict],
) -> None:
    """Cross-episode tracking for non-character assets (items, locations, outfits)."""
    if not asset_sightings:
        return
    result = await db.execute(select(Asset).where(Asset.project_id == project_id, Asset.type != "character"))
    other_assets = list(result.scalars().all())
    by_id = {a.id: a for a in other_assets}

    for s in asset_sightings:
        aid = s.get("asset_id")
        name = (s.get("name") or "").strip()
        asset = by_id.get(aid) if aid else None
        if asset is None and name:
            for cand in other_assets:
                if _asset_matches_name(cand, name):
                    asset = cand
                    break
        if asset is None:
            continue
        asset.episode_ids = {**(asset.episode_ids or {}), episode_id: True}
        if s.get("state_note"):
            tags = dict(asset.tags or {})
            tags["latest_state"] = str(s["state_note"])[:300]
            asset.tags = tags

    await db.commit()


async def auto_discover_assets(
    db: AsyncSession,
    project_id: str,
    episode_id: str,
    new_assets: list[dict],
) -> list[tuple[Asset, dict]]:
    """Register newly discovered assets, merging into existing ones by name/alias/embedding.

    Returns (Asset, raw_asset_dict) pairs so callers can attach auto-cropped thumbnails.
    """
    from app.core.llm import embeddings_configured, get_embeddings

    use_embeddings = embeddings_configured()
    existing_result = await db.execute(select(Asset).where(Asset.project_id == project_id))
    existing_assets = list(existing_result.scalars().all())

    discovered: list[tuple[Asset, dict]] = []
    claimed_existing_ids: set[str] = set()
    for asset_data in new_assets:
        asset_name = (asset_data.get("name") or "").strip()
        if not asset_name:
            continue
        asset_description = (asset_data.get("description") or "").strip()
        asset_type = asset_data.get("asset_type") or "character"
        if asset_type not in ("character", "outfit", "location", "item", "style"):
            asset_type = "item"
        visual_tags = [str(t) for t in (asset_data.get("visual_tags") or []) if str(t).strip()]
        aliases = [str(a) for a in (asset_data.get("aliases") or []) if str(a).strip()]

        matched_asset = None
        for existing in existing_assets:
            if existing.type == asset_type and existing.id not in claimed_existing_ids:
                if _asset_matches_name(existing, asset_name, aliases):
                    matched_asset = existing
                    claimed_existing_ids.add(existing.id)
                    break

        new_embedding = None
        text_parts = [asset_name, asset_description, " ".join(visual_tags)]
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
                    if best_sim >= 0.90 and best_asset:
                        matched_asset = best_asset
            except Exception:
                logger.warning("Embedding-based asset matching failed, using name matching only", exc_info=True)

        if matched_asset is not None:
            matched_asset.episode_ids = {**(matched_asset.episode_ids or {}), episode_id: True}
            if asset_description and len(asset_description) > len(matched_asset.description or ""):
                matched_asset.description = asset_description
            tags = dict(matched_asset.tags or {})
            if visual_tags:
                tags["visual_tags"] = list(dict.fromkeys([*tags.get("visual_tags", []), *visual_tags]))
            if aliases:
                tags["aliases"] = list(dict.fromkeys([*tags.get("aliases", []), *aliases]))
            if asset_data.get("owner_or_context"):
                tags["context"] = str(asset_data["owner_or_context"])[:200]
            if asset_data.get("speech_style"):
                tags["speech_style"] = str(asset_data["speech_style"])[:300]
            if asset_data.get("role"):
                tags["role"] = str(asset_data["role"])
            matched_asset.tags = tags
            discovered.append((matched_asset, asset_data))
            continue

        tags_payload: dict = {"visual_tags": visual_tags}
        if aliases:
            tags_payload["aliases"] = aliases
        if asset_data.get("owner_or_context"):
            tags_payload["context"] = str(asset_data["owner_or_context"])[:200]
        if asset_data.get("speech_style"):
            tags_payload["speech_style"] = str(asset_data["speech_style"])[:300]
        if asset_data.get("role"):
            tags_payload["role"] = str(asset_data["role"])

        asset = Asset(
            id=str(uuid.uuid4()),
            project_id=project_id,
            type=asset_type,
            name=asset_name,
            description=asset_description,
            tags=tags_payload,
            embedding=new_embedding,
            episode_ids={episode_id: True},
        )
        db.add(asset)
        existing_assets.append(asset)
        discovered.append((asset, asset_data))

    await db.commit()
    return discovered


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
    open_result = await db.execute(select(Pit).where(Pit.project_id == project_id, Pit.status == "open"))
    open_pits = list(open_result.scalars().all())

    pits: list[Pit] = []
    for pit_data in pit_discoveries:
        description = (pit_data.get("description") or "").strip()
        title = (pit_data.get("title") or "").strip() or description[:80]
        if not description:
            continue
        norm_desc = _normalize_name(description)
        norm_title = _normalize_name(title)
        duplicate = next(
            (
                p
                for p in open_pits + pits
                if SequenceMatcher(None, _normalize_name(p.description or ""), norm_desc).ratio() >= 0.80
                or (norm_title and SequenceMatcher(None, _normalize_name(p.title or ""), norm_title).ratio() >= 0.85)
            ),
            None,
        )
        if duplicate is not None:
            continue
        pit = Pit(
            id=str(uuid.uuid4()),
            project_id=project_id,
            title=title[:255],
            description=description,
            priority={"low": 2, "medium": 5, "high": 10}.get(str(pit_data.get("priority", "medium")).lower(), 5),
            introduced_episode_id=episode_id,
            trigger_hint=pit_data.get("trigger_hint"),
            status="open",
        )
        db.add(pit)
        pits.append(pit)
    await db.commit()
    return pits


async def advance_pits(
    db: AsyncSession,
    project_id: str,
    episode_label: str,
    pit_progressions: list[dict],
) -> list[Pit]:
    """Append newly discovered clue progressions onto open pits without closing them."""
    if not pit_progressions:
        return []
    pit_ids = [str(p.get("pit_id", "")) for p in pit_progressions if p.get("pit_id")]
    if not pit_ids:
        return []
    result = await db.execute(
        select(Pit).where(Pit.project_id == project_id, Pit.id.in_(pit_ids), Pit.status == "open")
    )
    by_id = {p.id: p for p in result.scalars().all()}
    updated: list[Pit] = []
    for prog in pit_progressions:
        pit = by_id.get(str(prog.get("pit_id", "")))
        clue = (prog.get("clue") or "").strip()
        if not pit or not clue:
            continue
        marker = f"[第{episode_label}话线索] {clue}"
        desc = pit.description or pit.title
        if clue not in desc:
            pit.description = f"{desc}\n{marker}"
            updated.append(pit)
    if updated:
        await db.commit()
    return updated


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
