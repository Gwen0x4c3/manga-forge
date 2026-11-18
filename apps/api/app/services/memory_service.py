from __future__ import annotations

import json
import logging
import re
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm import embeddings_configured, get_embeddings
from app.core.vector_store import vector_store
from app.models.asset import Asset
from app.models.episode import Episode
from app.models.episode_memory import EpisodeMemory
from app.models.pit import Pit
from app.models.project import Project

logger = logging.getLogger(__name__)

_LANGUAGE_LABELS = {
    "zh": "简体中文 (Simplified Chinese)",
    "ja": "日本語 (Japanese)",
    "en": "English",
}


async def get_canon_rules(db: AsyncSession, project_id: str) -> dict | None:
    result = await db.execute(select(Project).where(Project.id == project_id).limit(1))
    project = result.scalar_one_or_none()
    if not project:
        return None
    return project.canon_rules or {}


async def update_canon_rules(db: AsyncSession, project_id: str, canon_rules: dict) -> dict | None:
    result = await db.execute(select(Project).where(Project.id == project_id).limit(1))
    project = result.scalar_one_or_none()
    if not project:
        return None
    existing = dict(project.canon_rules or {})
    updated = dict(canon_rules or {})
    # Preserve auto-maintained story_bible unless caller explicitly supplied a replacement
    if "story_bible" not in updated and "story_bible" in existing:
        updated["story_bible"] = existing["story_bible"]
    project.canon_rules = updated
    await db.commit()
    await db.refresh(project)
    return project.canon_rules


async def get_long_summary(db: AsyncSession, project_id: str) -> str | None:
    result = await db.execute(select(Project).where(Project.id == project_id).limit(1))
    project = result.scalar_one_or_none()
    if not project:
        return None
    return project.long_summary or ""


async def update_long_summary(db: AsyncSession, project_id: str, summary: str) -> str | None:
    result = await db.execute(select(Project).where(Project.id == project_id).limit(1))
    project = result.scalar_one_or_none()
    if not project:
        return None
    project.long_summary = summary
    await db.commit()
    await db.refresh(project)
    return project.long_summary


_SUMMARY_COMPRESS_THRESHOLD = 6000
_SUMMARY_COMPRESS_TARGET = 3200
_SUMMARY_TRUNCATE_KEEP = 4200


async def append_episode_summary(
    db: AsyncSession,
    project_id: str,
    episode_number,
    summary: str,
) -> str | None:
    """Idempotently append or update an episode's line in long_summary, compressing when over budget."""
    result = await db.execute(select(Project).where(Project.id == project_id).limit(1))
    project = result.scalar_one_or_none()
    if not project or not summary.strip():
        return project.long_summary if project else None

    entry = " ".join(summary.strip().splitlines())
    prefix = f"第{episode_number}话："
    new_line = f"{prefix}{entry}"
    existing_text = (project.long_summary or "").strip()

    if not existing_text:
        text = new_line
    else:
        lines = existing_text.splitlines()
        replaced = False
        for i, ln in enumerate(lines):
            if ln.strip().startswith(prefix):
                lines[i] = new_line
                replaced = True
                break
        if not replaced:
            lines.append(new_line)
        text = "\n".join(lines)

    if len(text) > _SUMMARY_COMPRESS_THRESHOLD:
        text = await _compress_long_summary(text) or text[-_SUMMARY_TRUNCATE_KEEP:]

    project.long_summary = text
    await db.commit()
    await db.refresh(project)
    return project.long_summary


async def _compress_long_summary(text: str) -> str | None:
    from pydantic import BaseModel

    from app.config import settings
    from app.core.llm import get_llm_client

    system = (
        "You are a manga story archivist. Compress the episode-by-episode story "
        "history into a structured, high-density rolling summary.\n"
        "Preserve in strict priority order:\n"
        "1. Overarching main plotline, core mystery, and current arc progress\n"
        "2. Character relationships and persistent state changes (injuries, items held, secrets known)\n"
        "3. Key items, locations, and worldbuilding rules\n"
        "4. ALL unresolved foreshadowing threads\n"
        "Write in the same language as the input. "
        f"Keep it under {_SUMMARY_COMPRESS_TARGET} characters."
    )
    try:
        client = get_llm_client()

        class Compressed(BaseModel):
            summary: str

        result = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
            response_model=Compressed,
            max_retries=1,
        )
        compressed = result.summary.strip()
        return compressed if len(compressed) >= 50 else None
    except Exception:
        logger.warning("Long summary compression failed, truncating instead", exc_info=True)
        return None


async def _latest_episode_memory(
    db: AsyncSession,
    episode_id: str,
    mem_type: str,
) -> EpisodeMemory | None:
    result = await db.execute(
        select(EpisodeMemory)
        .where(EpisodeMemory.episode_id == episode_id, EpisodeMemory.type == mem_type)
        .order_by(EpisodeMemory.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_branch_history_before(
    db: AsyncSession,
    project_id: str,
    branch_id: str,
    before_number: Decimal,
    fallback_long_summary: str = "",
) -> str:
    """Build compact story history strictly before `before_number` on `branch_id`."""
    eps = (
        (
            await db.execute(
                select(Episode)
                .where(
                    Episode.project_id == project_id,
                    Episode.branch_id == branch_id,
                    Episode.number < before_number,
                )
                .order_by(Episode.number.asc())
            )
        )
        .scalars()
        .all()
    )
    if not eps:
        return ""

    lines: list[str] = []
    for ep in eps:
        mem = await _latest_episode_memory(db, ep.id, "summary")
        if mem and isinstance(mem.content, dict) and mem.content.get("summary"):
            lbl = ep.label or str(ep.number)
            lines.append(f"第{lbl}话：{mem.content['summary']}")
    if lines:
        joined = "\n".join(lines)
        return joined[-2800:]
    return (fallback_long_summary or "")[-2000:]


async def get_recent_window(
    db: AsyncSession,
    project_id: str,
    branch_id: str,
    window_size: int = 5,
    max_episode_number: Decimal | None = None,
) -> list[dict]:
    query = select(Episode).where(Episode.project_id == project_id, Episode.branch_id == branch_id)
    if max_episode_number is not None:
        query = query.where(Episode.number <= max_episode_number)
    # Fetch slightly more candidates in case draft episodes without summary exist
    result = await db.execute(query.order_by(Episode.number.desc()).limit(window_size + 5))
    candidates = list(result.scalars().all())

    understood_items: list[dict] = []
    fallback_items: list[dict] = []
    for ep in candidates:
        memory = await _latest_episode_memory(db, ep.id, "summary")
        entry = {
            "episode_id": ep.id,
            "number": ep.number,
            "label": ep.label,
            "title": ep.title,
            "summary": memory.content if memory else None,
        }
        if memory and isinstance(memory.content, dict) and memory.content.get("summary"):
            understood_items.append(entry)
        else:
            fallback_items.append(entry)
        if len(understood_items) >= window_size:
            break

    chosen = understood_items[:window_size] if understood_items else fallback_items[:window_size]
    chosen.sort(key=lambda x: x["number"])
    return chosen


def _extract_search_tokens(query: str) -> list[str]:
    """Tokenize mixed CJK + Latin queries into meaningful words and CJK bigrams."""
    tokens: list[str] = []
    # 1. Alphanumeric words & CJK chunks split by punctuation/spaces
    chunks = [t for t in re.split(r"[\s,，。、；;:：!！?？（）()\[\]【】\"'“”‘’—…·]+", query) if t]
    for chunk in chunks:
        # Extract ASCII words
        for word in re.findall(r"[a-zA-Z0-9_]{2,}", chunk):
            tokens.append(word.lower())
        # Extract CJK runs: add short runs directly + overlapping 2-grams for longer clauses
        for cjk in re.findall(r"[\u4e00-\u9fff\u3040-\u30ff]{2,}", chunk):
            if len(cjk) <= 4:
                tokens.append(cjk)
            else:
                for i in range(0, len(cjk) - 1, 2):
                    tokens.append(cjk[i : i + 2])
                if len(cjk) >= 3:
                    tokens.append(cjk[-2:])
    # Deduplicate preserving order
    return list(dict.fromkeys(tokens))[:40]


async def search_rag(
    db: AsyncSession,
    project_id: str,
    query: str,
    top_k: int = 5,
    max_episode_number: Decimal | None = None,
    prefer_before_number: Decimal | None = None,
) -> list[dict]:
    """Semantic search over episode memories, falling back to CJK-aware keyword search."""
    if embeddings_configured() and query.strip():
        try:
            query_vectors = await get_embeddings([query[:4000]])
            if query_vectors:
                raw_results = await vector_store.search(
                    query_vector=query_vectors[0],
                    limit=max(top_k * 3, 15),
                    project_id=project_id,
                )
                filtered = []
                for r in raw_results:
                    ep_num = r.get("payload", {}).get("episode_number")
                    if max_episode_number is not None and ep_num is not None:
                        try:
                            if Decimal(str(ep_num)) > max_episode_number:
                                continue
                        except Exception:
                            pass
                    filtered.append(r)
                if filtered:
                    if prefer_before_number is not None:
                        older = [
                            r
                            for r in filtered
                            if Decimal(str(r.get("payload", {}).get("episode_number", 0))) < prefer_before_number
                        ]
                        recent = [r for r in filtered if r not in older]
                        return (older + recent)[:top_k]
                    return filtered[:top_k]
        except Exception:
            logger.warning("Vector RAG search failed, falling back to keyword search", exc_info=True)
    return await _keyword_search(
        db,
        project_id,
        query,
        top_k,
        max_episode_number=max_episode_number,
        prefer_before_number=prefer_before_number,
    )


async def _keyword_search(
    db: AsyncSession,
    project_id: str,
    query: str,
    top_k: int,
    max_episode_number: Decimal | None = None,
    prefer_before_number: Decimal | None = None,
) -> list[dict]:
    terms = _extract_search_tokens(query)
    if not terms:
        return []
    stmt = (
        select(EpisodeMemory, Episode.number)
        .join(Episode, EpisodeMemory.episode_id == Episode.id)
        .where(Episode.project_id == project_id, EpisodeMemory.type.in_(("summary", "events")))
    )
    if max_episode_number is not None:
        stmt = stmt.where(Episode.number <= max_episode_number)
    stmt = stmt.order_by(Episode.number.desc()).limit(250)
    rows = (await db.execute(stmt)).all()

    scored: list[tuple[int, float, Decimal, EpisodeMemory, str]] = []
    seen_episodes: set[tuple[str, str]] = set()

    for memory, number in rows:
        key = (memory.episode_id, memory.type)
        if key in seen_episodes:
            continue
        seen_episodes.add(key)

        fragments: list[tuple[str, str]] = []
        if memory.type == "summary" and isinstance(memory.content, dict):
            summary_str = memory.content.get("summary", "")
            if summary_str:
                fragments.append(("summary", summary_str))
            for ev in memory.content.get("events") or []:
                if isinstance(ev, dict) and ev.get("description"):
                    fragments.append(("event", ev["description"]))
            for sc in memory.content.get("state_changes") or []:
                if isinstance(sc, dict) and sc.get("after"):
                    fragments.append(
                        (
                            "state_change",
                            f"{sc.get('character', '')}: {sc.get('attribute', '')} -> {sc.get('after', '')}",
                        )
                    )
        elif memory.type == "events" and isinstance(memory.content, dict):
            events = memory.content.get("data", [])
            text = " ".join(e.get("description", "") if isinstance(e, dict) else str(e) for e in events)
            if text:
                fragments.append(("events", text))
        else:
            fragments.append((memory.type, json.dumps(memory.content, ensure_ascii=False)))

        is_older_bonus = 1 if (prefer_before_number is not None and number < prefer_before_number) else 0
        for frag_type, text in fragments:
            lower_text = text.lower()
            hits = sum(1 for t in terms if t in lower_text)
            if hits:
                score = round(hits / len(terms), 4)
                scored.append((is_older_bonus, score, number, memory, f"{frag_type}||{text}"))

    scored.sort(key=lambda x: (-x[0], -x[1], -x[2]))

    results = []
    for _, score, number, memory, packed in scored[:top_k]:
        frag_type, _, text = packed.partition("||")
        results.append(
            {
                "id": memory.id,
                "score": score,
                "payload": {
                    "content": text,
                    "episode_id": memory.episode_id,
                    "episode_number": float(number) if isinstance(number, Decimal) else number,
                    "type": frag_type,
                },
            }
        )
    return results


def _split_pit_clues(description: str | None) -> tuple[str, list[str]]:
    if not description:
        return "", []
    base_lines: list[str] = []
    clues: list[str] = []
    for ln in description.splitlines():
        s = ln.strip()
        if s.startswith("[第") and "线索]" in s:
            clues.append(s)
        elif s:
            base_lines.append(s)
    return " ".join(base_lines), clues


async def build_context_for_generation(
    db: AsyncSession,
    project_id: str,
    branch_id: str,
    base_episode_number: Decimal,
) -> dict:
    """Assemble branch-isolated, temporally-bounded, high-density continuity context for LLM script generation."""
    project = (await db.execute(select(Project).where(Project.id == project_id).limit(1))).scalar_one_or_none()

    raw_canon = dict((project.canon_rules or {}) if project else {})
    story_bible = dict(raw_canon.pop("story_bible", None) or {})

    # Fetch ALL branch episodes <= base_episode_number in chronological order
    branch_eps = list(
        (
            await db.execute(
                select(Episode)
                .where(
                    Episode.project_id == project_id,
                    Episode.branch_id == branch_id,
                    Episode.number <= base_episode_number,
                )
                .order_by(Episode.number.asc())
            )
        )
        .scalars()
        .all()
    )
    branch_ep_ids = {ep.id for ep in branch_eps}
    max_branch_ep = (
        await db.execute(
            select(Episode.number)
            .where(Episode.project_id == project_id, Episode.branch_id == branch_id)
            .order_by(Episode.number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    # Load summary & ocr memories for branch episodes <= base_episode_number
    ep_summaries: list[tuple[Episode, dict]] = []
    speech_samples_by_speaker: dict[str, list[str]] = {}
    cumulative_states: dict[str, dict[str, str]] = {}
    latest_main_plot: dict = {}

    for ep in branch_eps:
        mem = await _latest_episode_memory(db, ep.id, "summary")
        if not mem or not isinstance(mem.content, dict):
            continue
        content = mem.content
        ep_summaries.append((ep, content))

        mp = content.get("main_plot") or {}
        if any(mp.values()):
            for k in ("core_conflict", "current_arc", "protagonist_goal", "arc_progress", "next_hook"):
                if mp.get(k):
                    latest_main_plot[k] = mp[k]

        for sc in content.get("state_changes") or []:
            cname = (sc.get("character") or "").strip()
            attr = (sc.get("attribute") or "state").strip()
            after = (sc.get("after") or "").strip()
            if cname and after:
                cumulative_states.setdefault(cname, {})[attr] = after

        for pd in content.get("page_dialogues") or []:
            for ln in pd.get("lines") or []:
                spk = (ln.get("speaker") or "").strip()
                txt = (ln.get("text") or "").strip()
                if spk and txt and ln.get("line_type", "speech") in ("speech", "thought") and len(txt) >= 3:
                    samples = speech_samples_by_speaker.setdefault(spk, [])
                    if txt not in samples:
                        samples.append(txt[:80])

    # Recent window (last 5 understood episodes <= base_episode_number)
    recent_pairs = ep_summaries[-5:]
    recent_min_number = recent_pairs[0][0].number if recent_pairs else base_episode_number

    # Immediate bridge from the base episode (latest understood episode <= base_episode_number)
    previous_bridge = None
    if ep_summaries:
        last_ep, last_content = ep_summaries[-1]
        closing_lines: list[str] = []
        for pd in (last_content.get("page_dialogues") or [])[-2:]:
            for ln in pd.get("lines") or []:
                spk = (ln.get("speaker") or "").strip()
                txt = (ln.get("text") or "").strip()
                if txt:
                    closing_lines.append(f"{spk}: {txt}" if spk else f"[旁白] {txt}")
        all_events = last_content.get("events") or []
        important_events = [e for e in all_events if e.get("significance") in ("major", "turning_point", "cliffhanger")]
        key_events = important_events or all_events[-3:]
        previous_bridge = {
            "episode_number": str(last_ep.label or last_ep.number),
            "title": last_ep.title or "",
            "summary": last_content.get("summary", ""),
            "ending_state": last_content.get("ending_state") or {},
            "key_events": key_events,
            "closing_dialogue": closing_lines[-10:],
        }

    # Branch-accurate long_summary & story_bible
    is_at_project_head = max_branch_ep is None or base_episode_number >= max_branch_ep
    if is_at_project_head and project and project.long_summary:
        effective_long_summary = project.long_summary
    else:
        effective_long_summary = "\n".join(
            f"第{ep.label or ep.number}话：{c.get('summary', '')}" for ep, c in ep_summaries if c.get("summary")
        )[-4000:]

    if latest_main_plot:
        story_bible["main_plot"] = {**(story_bible.get("main_plot") or {}), **latest_main_plot}

    # Filter pits temporally: introduced <= base_episode_number, and NOT resolved <= base_episode_number
    all_pits = list(
        (await db.execute(select(Pit).where(Pit.project_id == project_id).order_by(Pit.priority.desc())))
        .scalars()
        .all()
    )
    ep_num_lookup = {
        row[0]: row[1]
        for row in (await db.execute(select(Episode.id, Episode.number).where(Episode.project_id == project_id))).all()
    }
    active_pits_filtered: list[Pit] = []
    for pit in all_pits:
        if pit.status == "abandoned":
            continue
        intro_num = ep_num_lookup.get(pit.introduced_episode_id)
        if intro_num is not None and intro_num > base_episode_number:
            continue
        if pit.status == "resolved":
            res_num = ep_num_lookup.get(pit.resolved_episode_id) if pit.resolved_episode_id else None
            # If resolved in a LATER episode (> base_episode_number), it was still OPEN at base_episode_number!
            if res_num is None or res_num <= base_episode_number:
                continue
        active_pits_filtered.append(pit)

    # Load and rank assets by branch relevance
    assets = list((await db.execute(select(Asset).where(Asset.project_id == project_id))).scalars().all())
    assets.sort(
        key=lambda a: (
            -sum(1 for eid in (a.episode_ids or {}) if eid in branch_ep_ids),
            -len(a.episode_ids or {}),
        )
    )

    character_dossier: list[dict] = []
    world_assets: list[dict] = []
    style_desc = story_bible.get("art_style") or ""

    for asset in assets:
        tags = asset.tags or {}
        vtags = tags.get("visual_tags") or []
        if asset.type == "style":
            if not style_desc and asset.description:
                style_desc = asset.description
            continue
        if asset.type == "character":
            # Match cumulative state changes & speech samples by character name/aliases
            state_items: dict[str, str] = {}
            samples: list[str] = []
            names_to_check = [asset.name, *(tags.get("aliases") or [])]
            for cname, sdict in cumulative_states.items():
                if any(cname == n or cname in n or n in cname for n in names_to_check if n):
                    state_items.update(sdict)
            for spk, slines in speech_samples_by_speaker.items():
                if any(spk == n or spk in n or n in spk for n in names_to_check if n):
                    for ln in slines:
                        if ln not in samples:
                            samples.append(ln)

            character_dossier.append(
                {
                    "id": asset.id,
                    "name": asset.name,
                    "role": tags.get("role", ""),
                    "description": asset.description or tags.get("latest_appearance", ""),
                    "visual_tags": vtags[:10],
                    "current_state": "; ".join(f"{k}={v}" for k, v in state_items.items()),
                    "speech_style": tags.get("speech_style", ""),
                    "speech_samples": samples[-3:],
                }
            )
        else:
            world_assets.append(
                {
                    "id": asset.id,
                    "type": asset.type,
                    "name": asset.name,
                    "description": asset.description or "",
                    "visual_tags": vtags[:8],
                    "latest_state": tags.get("latest_state", ""),
                }
            )

    # RAG query combining recent summaries + main plot hook + active pits
    rag_query_parts = [c.get("summary", "") for _, c in recent_pairs]
    if story_bible.get("main_plot", {}).get("next_hook"):
        rag_query_parts.append(story_bible["main_plot"]["next_hook"])
    rag_query_parts.extend((pit.description or pit.title) for pit in active_pits_filtered[:8])
    rag_query = " ".join(p for p in rag_query_parts if p)
    rag_memories = (
        await search_rag(
            db,
            project_id,
            rag_query,
            top_k=6,
            max_episode_number=base_episode_number,
            prefer_before_number=recent_min_number,
        )
        if rag_query
        else []
    )

    # Combine user canon rules + auto-discovered world rules cleanly
    canon_for_prompt: dict = {}
    if raw_canon:
        canon_for_prompt.update(raw_canon)
    if story_bible.get("discovered_rules"):
        canon_for_prompt["discovered_world_rules"] = story_bible["discovered_rules"]

    lang = (project.language if project else "zh") or "zh"

    active_pits_payload = []
    for pit in active_pits_filtered[:20]:
        clean_desc, clues = _split_pit_clues(pit.description or pit.title)
        prio_label = "high" if pit.priority >= 8 else ("medium" if pit.priority >= 4 else "low")
        active_pits_payload.append(
            {
                "id": pit.id,
                "title": pit.title,
                "description": clean_desc or pit.title,
                "priority": pit.priority,
                "priority_label": prio_label,
                "trigger_hint": pit.trigger_hint,
                "clues": clues[-4:],
            }
        )

    return {
        "project_title": project.title if project else "",
        "language": lang,
        "language_label": _LANGUAGE_LABELS.get(lang, lang),
        "art_style": style_desc,
        "story_bible": story_bible,
        "canon_rules": json.dumps(canon_for_prompt, ensure_ascii=False, indent=2) if canon_for_prompt else "",
        "long_summary": effective_long_summary or "",
        "previous_bridge": previous_bridge,
        "recent_episodes": [
            {
                "number": float(ep.number) if isinstance(ep.number, Decimal) else ep.number,
                "label": ep.label,
                "title": ep.title,
                "summary": c.get("summary", ""),
                "events": c.get("events", [])[:6],
                "state_changes": c.get("state_changes", []),
            }
            for ep, c in recent_pairs
        ],
        "character_dossier": character_dossier[:20],
        "world_assets": world_assets[:25],
        "rag_memories": [
            {
                "content": m["payload"].get("content", ""),
                "episode_number": m["payload"].get("episode_number"),
                "type": m["payload"].get("type", ""),
            }
            for m in rag_memories
        ],
        "active_pits": active_pits_payload,
        "assets": [
            {
                "id": asset.id,
                "type": asset.type,
                "name": asset.name,
                "description": asset.description or "",
                "visual_tags": (asset.tags or {}).get("visual_tags", []),
            }
            for asset in assets[:40]
        ],
    }


async def vectorize_and_store_episode_memory(
    db: AsyncSession,
    project_id: str,
    episode_id: str,
    episode_number,
    understanding: dict,
) -> None:
    texts = []
    payloads = []
    ep_num_val = float(episode_number) if isinstance(episode_number, Decimal) else episode_number

    summary_text = understanding.get("summary", "")
    if summary_text:
        texts.append(summary_text)
        payloads.append(
            {
                "project_id": project_id,
                "episode_id": episode_id,
                "episode_number": ep_num_val,
                "type": "summary",
                "content": summary_text,
            }
        )

    for event in understanding.get("events", []):
        event_text = event.get("description", "")
        if event_text:
            texts.append(event_text)
            payloads.append(
                {
                    "project_id": project_id,
                    "episode_id": episode_id,
                    "episode_number": ep_num_val,
                    "type": "event",
                    "content": event_text,
                }
            )

    for change in understanding.get("state_changes", []):
        change_text = f"{change.get('character', '')}: {change.get('attribute', '')} -> {change.get('after', '')}"
        if change_text.strip("-> :"):
            texts.append(change_text)
            payloads.append(
                {
                    "project_id": project_id,
                    "episode_id": episode_id,
                    "episode_number": ep_num_val,
                    "type": "state_change",
                    "content": change_text,
                }
            )

    if not texts or not embeddings_configured():
        if not embeddings_configured():
            logger.info("Embedding model not configured — skipping vectorization of episode %s", episode_id)
        return

    try:
        vectors = await get_embeddings(texts)
        if not vectors:
            return
        points = [
            {"id": str(uuid.uuid4()), "vector": vector, "payload": payload}
            for vector, payload in zip(vectors, payloads)
        ]
        await vector_store.upsert_vectors(points)
    except Exception:
        logger.warning("Vectorization storage skipped due to vector store error", exc_info=True)
