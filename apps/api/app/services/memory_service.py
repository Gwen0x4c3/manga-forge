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

ARC_BLOCK_SIZE = 10
_SUMMARY_COMPRESS_THRESHOLD = 6500
_SUMMARY_COMPRESS_TARGET = 3600


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


def _condense_sentence(text: str, max_len: int = 130) -> str:
    cleaned = " ".join((text or "").strip().splitlines())
    if len(cleaned) <= max_len:
        return cleaned
    # Cut cleanly at sentence boundary if possible
    for sep in ("。", "！", "？", "；", ". ", "! ", "? "):
        idx = cleaned.rfind(sep, 0, max_len)
        if idx >= max_len // 2:
            return cleaned[: idx + len(sep)].strip()
    return cleaned[: max_len - 1].rstrip() + "…"


def _synthesize_arc_summary(
    arc_items: list[tuple[str, dict]],
    max_chars: int = 520,
) -> str:
    """Deterministically synthesize a 10-episode arc digest without repeated LLM re-compression loss."""
    if not arc_items:
        return ""

    highlights: list[str] = []
    # 1. Major turning points / cliffhangers across the arc
    for ep_label, content in arc_items:
        events = content.get("events") or []
        major = [
            ev.get("description", "").strip()
            for ev in events
            if isinstance(ev, dict)
            and ev.get("significance") in ("turning_point", "major", "cliffhanger")
            and ev.get("description")
        ]
        if major:
            highlights.append(f"[第{ep_label}话] " + _condense_sentence(major[0], 95))
        elif content.get("summary"):
            highlights.append(f"[第{ep_label}话] " + _condense_sentence(str(content["summary"]), 85))

    # 2. Persistent state transitions across the arc
    arc_states: dict[str, str] = {}
    for _ep_label, content in arc_items:
        for sc in content.get("state_changes") or []:
            if isinstance(sc, dict) and sc.get("character") and sc.get("after"):
                key = f"{sc['character']}.{sc.get('attribute') or '状态'}"
                arc_states[key] = _condense_sentence(str(sc["after"]), 45)

    body = "；".join(highlights)
    if arc_states:
        state_tail = "｜状态演进：" + "，".join(f"{k}→{v}" for k, v in list(arc_states.items())[-5:])
    else:
        state_tail = ""

    if len(body) + len(state_tail) <= max_chars:
        return body + state_tail

    budget = max(160, max_chars - len(state_tail))
    # Evenly sample across the 10-episode block so beginning, middle, and end of the arc all survive
    if len(highlights) > 4:
        step = max(1, len(highlights) // 5)
        sampled = [highlights[0]]
        for idx in range(step, len(highlights) - 1, step):
            if highlights[idx] not in sampled:
                sampled.append(highlights[idx])
        if highlights[-1] not in sampled:
            sampled.append(highlights[-1])
        body = "；".join(sampled)
    return _condense_sentence(body, budget) + state_tail


def build_hierarchical_history(
    ep_summaries: list[tuple[Episode, dict]],
    cached_arcs: list[dict] | None = None,
    include_recent_tail: int = 0,
) -> tuple[str, list[dict]]:
    """Build multi-scale story history (immutable 10-episode Arc Summaries + recent tail)
    so 60~150+ episode series keep Chapter 1~10 intact without repeated compression decay."""
    if not ep_summaries:
        return "", list(cached_arcs or [])

    cache_by_key = {
        str(a.get("key")): a
        for a in (cached_arcs or [])
        if isinstance(a, dict) and a.get("key") and a.get("summary")
    }

    older_pairs = ep_summaries[:-include_recent_tail] if include_recent_tail > 0 else ep_summaries
    tail_pairs = ep_summaries[-include_recent_tail:] if include_recent_tail > 0 else []

    arc_records: list[dict] = []
    rendered_sections: list[str] = []

    for i in range(0, len(older_pairs), ARC_BLOCK_SIZE):
        chunk = older_pairs[i : i + ARC_BLOCK_SIZE]
        start_lbl = str(chunk[0][0].label or chunk[0][0].number)
        end_lbl = str(chunk[-1][0].label or chunk[-1][0].number)
        is_sealed = len(chunk) == ARC_BLOCK_SIZE
        ep_sig = ",".join(ep.id for ep, _ in chunk)
        arc_key = f"{start_lbl}-{end_lbl}:{len(chunk)}"

        if is_sealed and arc_key in cache_by_key and cache_by_key[arc_key].get("ep_sig") == ep_sig:
            record = cache_by_key[arc_key]
        else:
            arc_items = [(str(ep.label or ep.number), c) for ep, c in chunk]
            per_arc_budget = 520 if len(older_pairs) <= 80 else 360
            digest = _synthesize_arc_summary(arc_items, max_chars=per_arc_budget)
            record = {
                "key": arc_key,
                "start_episode": start_lbl,
                "end_episode": end_lbl,
                "count": len(chunk),
                "sealed": is_sealed,
                "ep_sig": ep_sig,
                "summary": digest,
            }
        if is_sealed:
            arc_records.append(record)
        header = f"【第{start_lbl}~{end_lbl}话篇章纪要】" if len(chunk) > 1 else f"【第{start_lbl}话纪要】"
        rendered_sections.append(f"{header}{record['summary']}")

    if tail_pairs:
        for ep, content in tail_pairs:
            lbl = ep.label or str(ep.number)
            summ = (content.get("summary") or "").strip()
            if summ:
                rendered_sections.append(f"第{lbl}话：{_condense_sentence(summ, 360)}")

    return "\n".join(rendered_sections), arc_records


async def append_episode_summary(
    db: AsyncSession,
    project_id: str,
    episode_number,
    summary: str,
) -> str | None:
    """Update rolling project summary using hierarchical arc blocks when chapter count grows large."""
    result = await db.execute(select(Project).where(Project.id == project_id).limit(1))
    project = result.scalar_one_or_none()
    if not project or not summary.strip():
        return project.long_summary if project else None

    # Check if we have structured episode summaries on the default/head branch to build clean arc blocks
    eps = list(
        (
            await db.execute(
                select(Episode).where(Episode.project_id == project_id).order_by(Episode.number.asc())
            )
        )
        .scalars()
        .all()
    )
    # Deduplicate by episode number preferring latest updated on default progression
    by_num: dict[Decimal, Episode] = {}
    for ep in eps:
        by_num[ep.number] = ep
    ordered_eps = [by_num[k] for k in sorted(by_num.keys())]
    mem_map = await _load_latest_memories_map(db, [ep.id for ep in ordered_eps], "summary")
    ep_summaries = [(ep, mem_map[ep.id]) for ep in ordered_eps if ep.id in mem_map]

    canon = dict(project.canon_rules or {})
    bible = dict(canon.get("story_bible") or {})
    cached_arcs = bible.get("arc_summaries") or []

    if len(ep_summaries) > ARC_BLOCK_SIZE + 2:
        hierarchical_text, updated_arcs = build_hierarchical_history(
            ep_summaries,
            cached_arcs=cached_arcs,
            include_recent_tail=5,
        )
        bible["arc_summaries"] = updated_arcs
        canon["story_bible"] = bible
        project.canon_rules = canon
        project.long_summary = hierarchical_text
        await db.commit()
        await db.refresh(project)
        return project.long_summary

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
        compressed = await _compress_long_summary(text)
        if compressed:
            text = compressed

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
            max_tokens=settings.OPENAI_MAX_TOKENS,
            max_retries=1,
        )
        compressed = result.summary.strip()
        return compressed if len(compressed) >= 50 else None
    except Exception:
        logger.warning("Long summary compression failed, keeping hierarchical summary", exc_info=True)
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


async def _load_latest_memories_map(
    db: AsyncSession,
    episode_ids: list[str],
    mem_type: str = "summary",
) -> dict[str, dict]:
    """Batch-load the newest memory content per episode in a single SQL query (no N+1 at 60+ chapters)."""
    if not episode_ids:
        return {}
    rows = (
        (
            await db.execute(
                select(EpisodeMemory)
                .where(EpisodeMemory.episode_id.in_(episode_ids), EpisodeMemory.type == mem_type)
                .order_by(EpisodeMemory.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    out: dict[str, dict] = {}
    for row in rows:
        if row.episode_id not in out and isinstance(row.content, dict):
            out[row.episode_id] = row.content
    return out


async def _collect_lineage_episode_ids(
    db: AsyncSession,
    project_id: str,
    branch_eps: list[Episode],
) -> set[str]:
    """Collect episode IDs on `branch_eps` PLUS any pre-fork ancestor `parent_episode_id`s
    so forked branches seamlessly inherit pre-fork asset sightings, pit origins, and RAG vectors."""
    lineage_ids = {ep.id for ep in branch_eps}
    pending_parents = {ep.parent_episode_id for ep in branch_eps if ep.parent_episode_id} - lineage_ids
    if not pending_parents:
        return lineage_ids

    all_ep_parents = {
        row[0]: row[1]
        for row in (
            await db.execute(select(Episode.id, Episode.parent_episode_id).where(Episode.project_id == project_id))
        ).all()
    }
    while pending_parents:
        pid = pending_parents.pop()
        if not pid or pid in lineage_ids:
            continue
        lineage_ids.add(pid)
        anc = all_ep_parents.get(pid)
        if anc and anc not in lineage_ids:
            pending_parents.add(anc)
    return lineage_ids


async def get_branch_history_before(
    db: AsyncSession,
    project_id: str,
    branch_id: str,
    before_number: Decimal,
    fallback_long_summary: str = "",
) -> str:
    """Build multi-scale story history strictly before `before_number` on `branch_id`
    (sealed 10-episode Arc Summaries from Ep 1 onward + detailed recent 5 chapters)."""
    eps = list(
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

    mem_map = await _load_latest_memories_map(db, [ep.id for ep in eps], "summary")
    ep_summaries = [
        (ep, mem_map[ep.id])
        for ep in eps
        if ep.id in mem_map and mem_map[ep.id].get("summary")
    ]
    if ep_summaries:
        project = (await db.execute(select(Project).where(Project.id == project_id).limit(1))).scalar_one_or_none()
        cached_arcs = (((project.canon_rules or {}).get("story_bible") or {}).get("arc_summaries")) if project else None
        history_text, _ = build_hierarchical_history(
            ep_summaries,
            cached_arcs=cached_arcs,
            include_recent_tail=5,
        )
        return history_text
    return fallback_long_summary or ""


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
    result = await db.execute(query.order_by(Episode.number.desc()).limit(window_size + 5))
    candidates = list(result.scalars().all())
    mem_map = await _load_latest_memories_map(db, [ep.id for ep in candidates], "summary")

    understood_items: list[dict] = []
    fallback_items: list[dict] = []
    for ep in candidates:
        content = mem_map.get(ep.id)
        entry = {
            "episode_id": ep.id,
            "number": ep.number,
            "label": ep.label,
            "title": ep.title,
            "summary": content,
        }
        if content and content.get("summary"):
            understood_items.append(entry)
        else:
            fallback_items.append(entry)
        if len(understood_items) >= window_size:
            break

    chosen = understood_items[:window_size] if understood_items else fallback_items[:window_size]
    chosen.sort(key=lambda x: x["number"])
    return chosen


def _extract_search_tokens(query: str, max_tokens: int = 64) -> list[str]:
    """Tokenize mixed CJK + Latin queries, sampling evenly across clauses when long."""
    tokens: list[str] = []
    chunks = [t for t in re.split(r"[\s,，。、；;:：!！?？（）()\[\]【】\"'“”‘’—…·]+", query) if t]
    for chunk in chunks:
        for word in re.findall(r"[a-zA-Z0-9_-]{2,}", chunk):
            tokens.append(word.lower())
        for cjk in re.findall(r"[\u4e00-\u9fff\u3040-\u30ff]{2,}", chunk):
            if len(cjk) <= 4:
                tokens.append(cjk)
            else:
                for i in range(0, len(cjk) - 1, 2):
                    tokens.append(cjk[i : i + 2])
                if len(cjk) >= 3:
                    tokens.append(cjk[-2:])
    unique = list(dict.fromkeys(tokens))
    if len(unique) <= max_tokens:
        return unique
    # Evenly sample across the entire query instead of cutting off after the first sentence
    step = len(unique) / max_tokens
    return [unique[int(i * step)] for i in range(max_tokens)]


async def search_rag(
    db: AsyncSession,
    project_id: str,
    query: str,
    top_k: int = 5,
    max_episode_number: Decimal | None = None,
    prefer_before_number: Decimal | None = None,
    episode_ids: set[str] | list[str] | None = None,
) -> list[dict]:
    """Branch-aware semantic search over episode memories, falling back to CJK-aware keyword search."""
    ep_id_list = list(episode_ids) if episode_ids is not None else None
    if embeddings_configured() and query.strip():
        try:
            query_vectors = await get_embeddings([query[:4000]])
            if query_vectors:
                raw_results = await vector_store.search(
                    query_vector=query_vectors[0],
                    limit=max(top_k * 3, 18),
                    project_id=project_id,
                    episode_ids=ep_id_list,
                    max_episode_number=float(max_episode_number) if max_episode_number is not None else None,
                )
                filtered = []
                allowed_set = set(ep_id_list) if ep_id_list is not None else None
                for r in raw_results:
                    payload = r.get("payload", {})
                    if allowed_set is not None and payload.get("episode_id") not in allowed_set:
                        continue
                    ep_num = payload.get("episode_number")
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
        episode_ids=ep_id_list,
    )


async def _keyword_search(
    db: AsyncSession,
    project_id: str,
    query: str,
    top_k: int,
    max_episode_number: Decimal | None = None,
    prefer_before_number: Decimal | None = None,
    episode_ids: list[str] | None = None,
) -> list[dict]:
    terms = _extract_search_tokens(query)
    if not terms:
        return []
    if episode_ids is not None and not episode_ids:
        return []

    stmt = (
        select(EpisodeMemory, Episode.number)
        .join(Episode, EpisodeMemory.episode_id == Episode.id)
        .where(Episode.project_id == project_id, EpisodeMemory.type.in_(("summary", "events")))
    )
    if episode_ids is not None:
        stmt = stmt.where(Episode.id.in_(episode_ids))
    if max_episode_number is not None:
        stmt = stmt.where(Episode.number <= max_episode_number)
    stmt = stmt.order_by(Episode.number.desc(), EpisodeMemory.created_at.desc())
    # Only apply row cap when branch episode_ids are unspecified
    if episode_ids is None:
        stmt = stmt.limit(800)
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
            # Weight multi-char matches higher than common 2-char bigrams
            weighted_hits = sum(2.0 if len(t) >= 3 else 1.0 for t in terms if t in lower_text)
            if weighted_hits > 0:
                score = round(weighted_hits / max(len(terms), 1), 4)
                scored.append((is_older_bonus, score, number, memory, f"{frag_type}||{text}"))

    scored.sort(key=lambda x: (-x[0], -x[1], -x[2]))

    results = []
    seen_contents: set[str] = set()
    for _, score, number, memory, packed in scored:
        frag_type, _, text = packed.partition("||")
        sig = f"{number}:{text[:80]}"
        if sig in seen_contents:
            continue
        seen_contents.add(sig)
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
        if len(results) >= top_k:
            break
    return results


async def _multi_query_rag(
    db: AsyncSession,
    project_id: str,
    weighted_queries: list[tuple[float, str]],
    top_k: int,
    max_episode_number: Decimal,
    prefer_before_number: Decimal,
    episode_ids: set[str],
) -> list[dict]:
    """Run focused sub-queries (author instructions, cliffhanger, active pits, cast) and fuse via RRF
    so specific long-range callbacks from 40~100 chapters ago aren't drowned out by recent summaries."""
    valid_queries = [(w, q.strip()) for w, q in weighted_queries if q and q.strip()]
    if not valid_queries or not episode_ids:
        return []

    fused_scores: dict[str, float] = {}
    items_by_sig: dict[str, dict] = {}

    for weight, sub_q in valid_queries:
        hits = await search_rag(
            db,
            project_id,
            sub_q,
            top_k=max(top_k, 6),
            max_episode_number=max_episode_number,
            prefer_before_number=prefer_before_number,
            episode_ids=episode_ids,
        )
        for rank, item in enumerate(hits):
            payload = item.get("payload") or {}
            ep_no = payload.get("episode_number")
            content = str(payload.get("content") or "")
            sig = f"{ep_no}:{content[:90]}"
            is_long_range = (
                ep_no is not None and Decimal(str(ep_no)) < prefer_before_number
            )
            range_mult = 1.35 if is_long_range else 0.55
            rrf = weight * range_mult * (1.0 / (rank + 8.0))
            fused_scores[sig] = fused_scores.get(sig, 0.0) + rrf
            if sig not in items_by_sig:
                items_by_sig[sig] = item

    ranked_sigs = sorted(
        fused_scores.keys(),
        key=lambda s: (
            -fused_scores[s],
            Decimal(str((items_by_sig[s].get("payload") or {}).get("episode_number") or 0)),
        ),
    )
    return [items_by_sig[s] for s in ranked_sigs[:top_k]]


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


def _text_mentions_any(haystack_lower: str, names: list[str]) -> bool:
    if not haystack_lower:
        return False
    for n in names:
        clean = (n or "").strip().lower()
        if len(clean) >= 2 and clean in haystack_lower:
            return True
    return False


async def build_context_for_generation(
    db: AsyncSession,
    project_id: str,
    branch_id: str,
    base_episode_number: Decimal,
    custom_instructions: str | None = None,
) -> dict:
    """Assemble branch-isolated, multi-scale continuity context capable of 60~150+ episodes."""
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
    lineage_ep_ids = await _collect_lineage_episode_ids(db, project_id, branch_eps)

    # Batch-load all summary memories on this branch in ONE query
    mem_map = await _load_latest_memories_map(db, [ep.id for ep in branch_eps], "summary")

    ep_summaries: list[tuple[Episode, dict]] = []
    speech_samples_by_speaker: dict[str, list[str]] = {}
    cumulative_states: dict[str, dict[str, str]] = {}
    latest_main_plot: dict = {}

    for ep in branch_eps:
        content = mem_map.get(ep.id)
        if not content:
            continue
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

    # Collect IDs (including pre-fork parent_episode_id) for recency scoring
    latest_ep_ids: set[str] = set()
    if ep_summaries:
        last_e = ep_summaries[-1][0]
        latest_ep_ids.add(last_e.id)
        if last_e.parent_episode_id:
            latest_ep_ids.add(last_e.parent_episode_id)

    recent_window_ep_ids: set[str] = set()
    for ep, _ in recent_pairs:
        recent_window_ep_ids.add(ep.id)
        if ep.parent_episode_id:
            recent_window_ep_ids.add(ep.parent_episode_id)

    recent_arc_ep_ids: set[str] = set()
    for ep, _ in ep_summaries[-10:]:
        recent_arc_ep_ids.add(ep.id)
        if ep.parent_episode_id:
            recent_arc_ep_ids.add(ep.parent_episode_id)

    # Immediate bridge from the base episode
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
        important_events = [
            e for e in all_events if e.get("significance") in ("major", "turning_point", "cliffhanger")
        ]
        key_events = important_events or all_events[-3:]
        previous_bridge = {
            "episode_number": str(last_ep.label or last_ep.number),
            "title": last_ep.title or "",
            "summary": last_content.get("summary", ""),
            "ending_state": last_content.get("ending_state") or {},
            "key_events": key_events,
            "closing_dialogue": closing_lines[-10:],
        }

    # Build multi-scale long_summary (immutable 10-episode Arc Summaries + pre-window episodes)
    # No more [-4000:] front-truncation or 10x repeated lossy compression!
    cached_arcs = story_bible.get("arc_summaries") or []
    if len(ep_summaries) > 5:
        older_history, arc_records = build_hierarchical_history(
            ep_summaries[:-5],
            cached_arcs=cached_arcs,
            include_recent_tail=0,
        )
        effective_long_summary = older_history
        story_bible["arc_summaries"] = arc_records
    elif ep_summaries:
        effective_long_summary = "\n".join(
            f"第{ep.label or ep.number}话：{c.get('summary', '')}" for ep, c in ep_summaries if c.get("summary")
        )
    else:
        effective_long_summary = (project.long_summary if project else "") or ""

    if latest_main_plot:
        story_bible["main_plot"] = {**(story_bible.get("main_plot") or {}), **latest_main_plot}

    # Filter pits temporally & by branch lineage
    all_pits = list(
        (await db.execute(select(Pit).where(Pit.project_id == project_id).order_by(Pit.priority.desc())))
        .scalars()
        .all()
    )
    ep_num_lookup = {
        row[0]: row[1]
        for row in (await db.execute(select(Episode.id, Episode.number).where(Episode.project_id == project_id))).all()
    }
    active_pits_candidates: list[Pit] = []
    for pit in all_pits:
        if pit.status == "abandoned":
            continue
        if pit.introduced_episode_id and pit.introduced_episode_id not in lineage_ep_ids:
            continue
        intro_num = ep_num_lookup.get(pit.introduced_episode_id)
        if intro_num is not None and intro_num > base_episode_number:
            continue
        if pit.status == "resolved":
            res_in_lineage = pit.resolved_episode_id in lineage_ep_ids if pit.resolved_episode_id else True
            res_num = ep_num_lookup.get(pit.resolved_episode_id) if pit.resolved_episode_id else None
            if res_in_lineage and (res_num is None or res_num <= base_episode_number):
                continue
        active_pits_candidates.append(pit)

    # Focus text for relevance boosting (custom instructions + immediate cliffhanger + main hook)
    bridge_text = json.dumps(previous_bridge.get("ending_state") or {}, ensure_ascii=False) if previous_bridge else ""
    hook_text = (story_bible.get("main_plot") or {}).get("next_hook", "")
    focus_lower = f"{custom_instructions or ''} {bridge_text} {hook_text}".lower()

    def _pit_score(p: Pit) -> tuple[float, float]:
        desc_l = f"{p.title or ''} {p.description or ''} {p.trigger_hint or ''}".lower()
        mention_hit = 1.0 if (custom_instructions and any(
            tok in desc_l for tok in _extract_search_tokens(custom_instructions, 20)
        )) else 0.0
        intro_ep = float(ep_num_lookup.get(p.introduced_episode_id) or 0)
        is_recent_pit = 1.0 if (float(base_episode_number) - intro_ep) <= 8.0 else 0.0
        _, clues = _split_pit_clues(p.description)
        clue_bonus = min(len(clues), 4) * 1.5
        score = p.priority * 3.0 + mention_hit * 50.0 + is_recent_pit * 12.0 + clue_bonus
        return (-score, -intro_ep)

    active_pits_candidates.sort(key=_pit_score)
    # Reserve slots so both foundational high-priority mysteries AND recent arc hooks survive at 60+ chapters
    active_pits_filtered = active_pits_candidates[:20]

    pit_focus_lower = " ".join((p.description or p.title or "") for p in active_pits_filtered[:8]).lower()
    combined_focus_lower = f"{focus_lower} {pit_focus_lower}"

    # Score & rank assets by (Mention in instructions/bridge/pits + Recency in current arc + Core Cast Frequency)
    assets = list((await db.execute(select(Asset).where(Asset.project_id == project_id))).scalars().all())

    def _asset_relevance_score(a: Asset) -> tuple[float, int]:
        tags = a.tags or {}
        names = [a.name, *(tags.get("aliases") or [])]
        ep_keys = set((a.episode_ids or {}).keys())
        branch_hits = len(ep_keys & lineage_ep_ids)
        score = float(min(branch_hits, 35) * 6)
        if ep_keys & latest_ep_ids:
            score += 260.0
        elif ep_keys & recent_window_ep_ids:
            score += 140.0
        elif ep_keys & recent_arc_ep_ids:
            score += 65.0
        if _text_mentions_any(focus_lower, names):
            score += 1000.0
        elif _text_mentions_any(combined_focus_lower, names):
            score += 320.0
        return (-score, -branch_hits)

    assets.sort(key=_asset_relevance_score)

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

    # Multi-Query Focused Long-Range Recall (replaces single 3500-char diluted soup query)
    cliffhanger_q = ""
    if previous_bridge:
        es = previous_bridge.get("ending_state") or {}
        cliffhanger_q = f"{es.get('cliffhanger', '')} {es.get('location', '')} {hook_text}".strip()
    pits_q = " ".join((p.title or p.description or "")[:120] for p in active_pits_filtered[:4])
    cast_q = " ".join(c["name"] for c in character_dossier[:6])

    rag_memories = await _multi_query_rag(
        db=db,
        project_id=project_id,
        weighted_queries=[
            (2.2, custom_instructions or ""),
            (1.5, cliffhanger_q),
            (1.3, pits_q),
            (0.9, cast_q),
        ],
        top_k=8,
        max_episode_number=base_episode_number,
        prefer_before_number=recent_min_number,
        episode_ids=lineage_ep_ids,
    )

    # Combine user canon rules + tiered core/recent world rules
    canon_for_prompt: dict = {}
    if raw_canon:
        canon_for_prompt.update(raw_canon)
    core_rules = story_bible.get("core_rules") or []
    disc_rules = story_bible.get("discovered_rules") or []
    merged_rules = list(dict.fromkeys([*core_rules, *disc_rules]))
    if merged_rules:
        canon_for_prompt["discovered_world_rules"] = merged_rules

    lang = (project.language if project else "zh") or "zh"

    active_pits_payload = []
    for pit in active_pits_filtered:
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
        await vector_store.delete_by_episode(episode_id)
        points = [
            {"id": str(uuid.uuid4()), "vector": vector, "payload": payload}
            for vector, payload in zip(vectors, payloads)
        ]
        await vector_store.upsert_vectors(points)
    except Exception:
        logger.warning("Vectorization storage skipped due to vector store error", exc_info=True)


async def build_story_graph(
    db: AsyncSession,
    project_id: str,
    branch_id: str | None = None,
) -> dict | None:
    """Build full visualization dataset for the Story Atlas UI:
    - Character co-occurrence & relationship graph (with cropped avatars, outfits, state timelines)
    - Story Arcs, foundational vs rolling world rules, and Pit swimlane timelines
    - Multiverse Branch DAG with episode covers and fork pointers
    """
    from app.models.asset_image import AssetImage
    from app.models.branch import Branch
    from app.models.episode_page import EpisodePage

    project = (await db.execute(select(Project).where(Project.id == project_id).limit(1))).scalar_one_or_none()
    if not project:
        return None

    branches = list(
        (
            await db.execute(
                select(Branch)
                .where(Branch.project_id == project_id)
                .order_by(Branch.is_default.desc(), Branch.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    active_branch = next((b for b in branches if branch_id and b.id == branch_id), None)
    if active_branch is None and branches:
        active_branch = branches[0]
    active_branch_id = active_branch.id if active_branch else None

    all_eps = list(
        (
            await db.execute(
                select(Episode).where(Episode.project_id == project_id).order_by(Episode.number.asc())
            )
        )
        .scalars()
        .all()
    )
    branch_eps = [ep for ep in all_eps if active_branch_id is None or ep.branch_id == active_branch_id]
    lineage_ep_ids = await _collect_lineage_episode_ids(db, project_id, branch_eps)

    # Batch load summaries, layout results, and first page covers
    all_ep_ids = [ep.id for ep in all_eps]
    summary_map = await _load_latest_memories_map(db, all_ep_ids, "summary")
    layout_map = await _load_latest_memories_map(db, all_ep_ids, "layout_result")

    first_pages_map: dict[str, str] = {}
    if all_ep_ids:
        pg_rows = (
            (
                await db.execute(
                    select(EpisodePage)
                    .where(EpisodePage.episode_id.in_(all_ep_ids))
                    .order_by(EpisodePage.page_index.asc())
                )
            )
            .scalars()
            .all()
        )
        for pg in pg_rows:
            if pg.episode_id not in first_pages_map:
                first_pages_map[pg.episode_id] = pg.image_path

    def _ep_cover(ep_id: str) -> str | None:
        if ep_id in first_pages_map:
            return first_pages_map[ep_id]
        lay = layout_map.get(ep_id) or {}
        pages = lay.get("pages") or []
        if pages and isinstance(pages[0], dict):
            return pages[0].get("image_path")
        return None

    # Load all assets + primary thumbnails in 2 queries
    assets = list((await db.execute(select(Asset).where(Asset.project_id == project_id))).scalars().all())
    asset_ids = [a.id for a in assets]
    ref_priority = ("reference", "turnaround", "thumbnail", "lora_dataset")
    asset_images_by_id: dict[str, list[AssetImage]] = {}
    if asset_ids:
        img_rows = (
            (await db.execute(select(AssetImage).where(AssetImage.asset_id.in_(asset_ids)))).scalars().all()
        )
        for im in img_rows:
            asset_images_by_id.setdefault(im.asset_id, []).append(im)

    def _best_asset_image(aid: str) -> str | None:
        imgs = asset_images_by_id.get(aid) or []
        if not imgs:
            return None
        best = min(imgs, key=lambda i: ref_priority.index(i.kind) if i.kind in ref_priority else 99)
        return best.image_path

    ep_num_by_id = {ep.id: float(ep.number) for ep in all_eps}
    ep_label_by_id = {ep.id: str(ep.label or ep.number) for ep in all_eps}

    # Build character alias resolver for event co-occurrence & state timeline matching
    char_assets = [a for a in assets if a.type == "character"]
    outfit_assets = [a for a in assets if a.type == "outfit"]

    def _match_char_id(raw_name: str) -> str | None:
        q = (raw_name or "").strip().lower()
        if not q:
            return None
        # Pass 1: exact name or alias match across all characters
        for ca in char_assets:
            names = [ca.name, *((ca.tags or {}).get("aliases") or [])]
            for nm in names:
                nl = (nm or "").strip().lower()
                if nl and nl == q:
                    return ca.id
        # Pass 2: substring containment fallback
        for ca in char_assets:
            names = [ca.name, *((ca.tags or {}).get("aliases") or [])]
            for nm in names:
                nl = (nm or "").strip().lower()
                if nl and len(nl) >= 2 and len(q) >= 2 and (nl in q or q in nl):
                    return ca.id
        return None

    char_state_timeline: dict[str, list[dict]] = {c.id: [] for c in char_assets}
    pair_moments: dict[tuple[str, str], list[dict]] = {}
    pair_episodes: dict[tuple[str, str], set[float]] = {}

    ep_summaries_branch: list[tuple[Episode, dict]] = []
    timeline_episodes: list[dict] = []

    for ep in branch_eps:
        content = summary_map.get(ep.id) or {}
        if content:
            ep_summaries_branch.append((ep, content))
        ep_num = float(ep.number)
        ep_lbl = str(ep.label or ep.number)

        events = content.get("events") or []
        major_events = [
            {
                "description": ev.get("description", ""),
                "significance": ev.get("significance", "normal"),
                "location": ev.get("location"),
                "characters": ev.get("characters_involved") or [],
            }
            for ev in events
            if isinstance(ev, dict) and ev.get("description")
        ]

        timeline_episodes.append(
            {
                "id": ep.id,
                "number": ep_num,
                "label": ep_lbl,
                "title": ep.title or f"第 {ep_lbl} 话",
                "source": ep.source,
                "status": ep.status,
                "cover_path": _ep_cover(ep.id),
                "summary": (content.get("summary") or "")[:300],
                "event_count": len(major_events),
                "major_events": major_events[:4],
                "cliffhanger": (content.get("ending_state") or {}).get("cliffhanger", ""),
            }
        )

        # Accumulate character state transitions
        for sc in content.get("state_changes") or []:
            if not isinstance(sc, dict):
                continue
            cid = _match_char_id(str(sc.get("character") or ""))
            if cid:
                char_state_timeline[cid].append(
                    {
                        "episode_number": ep_num,
                        "episode_label": ep_lbl,
                        "attribute": sc.get("attribute") or "status",
                        "before": sc.get("before") or "",
                        "after": sc.get("after") or "",
                        "reason": sc.get("reason") or "",
                    }
                )

        # Accumulate event-level co-occurrence edges
        ep_char_ids_seen: set[str] = set()
        for ev in events:
            if not isinstance(ev, dict):
                continue
            involved_ids = list(
                dict.fromkeys(
                    cid for nm in (ev.get("characters_involved") or []) if (cid := _match_char_id(str(nm))) is not None
                )
            )
            ep_char_ids_seen.update(involved_ids)
            for idx_a in range(len(involved_ids)):
                for idx_b in range(idx_a + 1, len(involved_ids)):
                    a_id, b_id = sorted((involved_ids[idx_a], involved_ids[idx_b]))
                    pair_episodes.setdefault((a_id, b_id), set()).add(ep_num)
                    pair_moments.setdefault((a_id, b_id), []).append(
                        {
                            "episode_number": ep_num,
                            "episode_label": ep_lbl,
                            "description": str(ev.get("description") or "")[:180],
                            "location": ev.get("location") or "",
                            "significance": ev.get("significance") or "normal",
                        }
                    )

        # Also connect characters who co-appear in the same episode's sightings or ending_state
        for c_sight in content.get("characters") or content.get("character_sightings") or []:
            if isinstance(c_sight, dict):
                cid = c_sight.get("asset_id") or _match_char_id(str(c_sight.get("name") or ""))
                if cid and cid in char_state_timeline:
                    ep_char_ids_seen.add(cid)
        for nm in (content.get("ending_state") or {}).get("active_characters") or []:
            cid = _match_char_id(str(nm))
            if cid and cid in char_state_timeline:
                ep_char_ids_seen.add(cid)
        for ca in char_assets:
            if ep.id in (ca.episode_ids or {}):
                ep_char_ids_seen.add(ca.id)
        seen_list = sorted(ep_char_ids_seen)
        for idx_a in range(len(seen_list)):
            for idx_b in range(idx_a + 1, len(seen_list)):
                pair_episodes.setdefault((seen_list[idx_a], seen_list[idx_b]), set()).add(ep_num)

    # Build character nodes
    char_nodes: list[dict] = []
    for ca in char_assets:
        ep_keys = set((ca.episode_ids or {}).keys())
        matched_nums = sorted({ep_num_by_id[eid] for eid in ep_keys if eid in ep_num_by_id})
        tags = ca.tags or {}
        # Match outfits belonging to this character
        char_outfits = []
        for oa in outfit_assets:
            otags = oa.tags or {}
            owner = str(otags.get("owner_or_context") or "")
            if oa.parent_asset_id == ca.id or ca.name in oa.name or ca.name in owner:
                char_outfits.append(
                    {
                        "id": oa.id,
                        "name": oa.name,
                        "description": (oa.description or "")[:160],
                        "image_path": _best_asset_image(oa.id),
                    }
                )

        char_nodes.append(
            {
                "id": ca.id,
                "name": ca.name,
                "role": tags.get("role") or "support",
                "aliases": tags.get("aliases") or [],
                "description": (ca.description or "")[:360],
                "speech_style": tags.get("speech_style") or "",
                "visual_tags": (tags.get("visual_tags") or [])[:10],
                "avatar_path": _best_asset_image(ca.id),
                "appearances": max(len(matched_nums), len(ep_keys)),
                "episode_numbers": matched_nums,
                "state_timeline": char_state_timeline.get(ca.id, []),
                "outfits": char_outfits[:6],
            }
        )
    char_nodes.sort(key=lambda n: (-n["appearances"], n["name"]))

    char_edges: list[dict] = []
    for (a_id, b_id), shared_eps in pair_episodes.items():
        moments = pair_moments.get((a_id, b_id), [])
        char_edges.append(
            {
                "source": a_id,
                "target": b_id,
                "weight": max(len(shared_eps), len(moments)),
                "shared_episodes": sorted(shared_eps),
                "moments": moments[:8],
            }
        )
    char_edges.sort(key=lambda e: -e["weight"])

    # Story Bible & Arc summaries
    story_bible = dict((project.canon_rules or {}).get("story_bible") or {})
    cached_arcs = story_bible.get("arc_summaries") or []
    _, computed_arcs = build_hierarchical_history(ep_summaries_branch, cached_arcs=cached_arcs, include_recent_tail=0)
    # Also include active unsealed arc block so even a 4-6 episode project shows a clear arc block!
    display_arcs = list(computed_arcs)
    covered_count = sum(int(a.get("count") or 0) for a in display_arcs)
    if len(ep_summaries_branch) > covered_count:
        rem = ep_summaries_branch[covered_count:]
        start_lbl = str(rem[0][0].label or rem[0][0].number)
        end_lbl = str(rem[-1][0].label or rem[-1][0].number)
        display_arcs.append(
            {
                "key": f"{start_lbl}-{end_lbl}:{len(rem)}",
                "start_episode": start_lbl,
                "end_episode": end_lbl,
                "count": len(rem),
                "sealed": False,
                "summary": _synthesize_arc_summary([(str(e.label or e.number), c) for e, c in rem], max_chars=480),
            }
        )

    # Pit swimlanes with numeric episode coordinates + parsed clue episode numbers
    pits = list(
        (await db.execute(select(Pit).where(Pit.project_id == project_id).order_by(Pit.priority.desc())))
        .scalars()
        .all()
    )
    pit_swimlanes: list[dict] = []
    for pit in pits:
        if pit.introduced_episode_id and lineage_ep_ids and pit.introduced_episode_id not in lineage_ep_ids:
            # Keep project-level manual pits (introduced_episode_id is None) and lineage pits
            if pit.introduced_episode_id in ep_num_by_id:
                continue
        clean_desc, raw_clues = _split_pit_clues(pit.description or pit.title)
        parsed_clues: list[dict] = []
        for cl in raw_clues:
            m = re.match(r"\[第([\d.]+)话线索\]\s*(.*)", cl)
            if m:
                parsed_clues.append({"episode_number": float(m.group(1)), "text": m.group(2)})
            else:
                parsed_clues.append({"episode_number": None, "text": cl})
        intro_num = ep_num_by_id.get(pit.introduced_episode_id) if pit.introduced_episode_id else None
        res_num = ep_num_by_id.get(pit.resolved_episode_id) if pit.resolved_episode_id else None
        pit_swimlanes.append(
            {
                "id": pit.id,
                "title": pit.title or clean_desc[:28],
                "description": clean_desc or pit.title,
                "status": pit.status,
                "priority": pit.priority,
                "trigger_hint": pit.trigger_hint,
                "introduced_episode_number": intro_num,
                "introduced_episode_label": (
                    ep_label_by_id.get(pit.introduced_episode_id) if pit.introduced_episode_id else None
                ),
                "resolved_episode_number": res_num,
                "resolved_episode_label": (
                    ep_label_by_id.get(pit.resolved_episode_id) if pit.resolved_episode_id else None
                ),
                "clues": parsed_clues,
            }
        )

    # Branch multiverse DAG
    eps_by_branch: dict[str, list[dict]] = {}
    for ep in all_eps:
        eps_by_branch.setdefault(ep.branch_id, []).append(
            {
                "id": ep.id,
                "number": float(ep.number),
                "label": str(ep.label or ep.number),
                "title": ep.title or f"第 {ep.label or ep.number} 话",
                "source": ep.source,
                "status": ep.status,
                "parent_episode_id": ep.parent_episode_id,
                "cover_path": _ep_cover(ep.id),
            }
        )

    branch_tree = [
        {
            "id": b.id,
            "name": b.name,
            "description": b.description or "",
            "is_default": b.is_default,
            "base_branch_id": b.base_branch_id,
            "base_episode_id": b.base_episode_id,
            "episode_count": len(eps_by_branch.get(b.id, [])),
            "episodes": eps_by_branch.get(b.id, []),
        }
        for b in branches
    ]

    return {
        "project_id": project.id,
        "project_title": project.title,
        "branch_id": active_branch_id,
        "branch_name": active_branch.name if active_branch else "",
        "story_bible": {
            "main_plot": story_bible.get("main_plot") or {},
            "art_style": story_bible.get("art_style") or "",
            "core_rules": story_bible.get("core_rules") or [],
            "discovered_rules": story_bible.get("discovered_rules") or [],
            "last_updated_episode": story_bible.get("last_updated_episode"),
        },
        "character_graph": {
            "nodes": char_nodes,
            "edges": char_edges,
        },
        "timeline": {
            "episodes": timeline_episodes,
            "arcs": display_arcs,
            "pit_swimlanes": pit_swimlanes,
        },
        "branch_tree": branch_tree,
    }


async def ask_story_bible(
    db: AsyncSession,
    project_id: str,
    question: str,
    branch_id: str | None = None,
    max_episode_number: Decimal | None = None,
) -> dict:
    """Grounded Q&A against the manga's Story Bible, multi-scale history, assets, and pits,
    returning an LLM answer with visual episode/page citations."""
    from app.config import settings
    from app.core.llm import get_raw_openai_client
    from app.models.asset_image import AssetImage
    from app.models.branch import Branch
    from app.models.episode_page import EpisodePage

    project = (await db.execute(select(Project).where(Project.id == project_id).limit(1))).scalar_one_or_none()
    if not project:
        raise ValueError("Project not found")

    if not branch_id:
        b = (
            await db.execute(
                select(Branch)
                .where(Branch.project_id == project_id)
                .order_by(Branch.is_default.desc(), Branch.created_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if not b:
            raise ValueError("No branch found for project")
        branch_id = b.id

    if max_episode_number is None:
        max_ep = (
            await db.execute(
                select(Episode.number)
                .where(Episode.project_id == project_id, Episode.branch_id == branch_id)
                .order_by(Episode.number.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        max_episode_number = max_ep if max_ep is not None else Decimal("9999")

    ctx = await build_context_for_generation(
        db,
        project_id,
        branch_id,
        max_episode_number,
        custom_instructions=question,
    )

    # Also run a direct question RAG pass across ALL episodes in this branch (including recent ones!)
    branch_eps = list(
        (
            await db.execute(
                select(Episode)
                .where(
                    Episode.project_id == project_id,
                    Episode.branch_id == branch_id,
                    Episode.number <= max_episode_number,
                )
                .order_by(Episode.number.asc())
            )
        )
        .scalars()
        .all()
    )
    ep_by_id = {ep.id: ep for ep in branch_eps}
    lineage_ids = await _collect_lineage_episode_ids(db, project_id, branch_eps)

    direct_hits = await search_rag(
        db,
        project_id,
        question,
        top_k=8,
        max_episode_number=max_episode_number,
        episode_ids=lineage_ids,
    )

    # Load first page or composed layout image for cited episodes
    cited_ep_ids = list(
        dict.fromkeys(
            str((h.get("payload") or {}).get("episode_id") or "")
            for h in direct_hits
            if (h.get("payload") or {}).get("episode_id")
        )
    )
    layout_map = await _load_latest_memories_map(db, cited_ep_ids, "layout_result")
    cover_by_ep: dict[str, str] = {}
    if cited_ep_ids:
        pgs = (
            (
                await db.execute(
                    select(EpisodePage)
                    .where(EpisodePage.episode_id.in_(cited_ep_ids))
                    .order_by(EpisodePage.page_index.asc())
                )
            )
            .scalars()
            .all()
        )
        for pg in pgs:
            if pg.episode_id not in cover_by_ep:
                cover_by_ep[pg.episode_id] = pg.image_path
    for eid in cited_ep_ids:
        if eid not in cover_by_ep:
            pages = (layout_map.get(eid) or {}).get("pages") or []
            if pages and isinstance(pages[0], dict) and pages[0].get("image_path"):
                cover_by_ep[eid] = pages[0]["image_path"]

    citations: list[dict] = []
    seen_cites: set[str] = set()
    for h in direct_hits:
        pl = h.get("payload") or {}
        eid = str(pl.get("episode_id") or "")
        ep_obj = ep_by_id.get(eid)
        ep_num = pl.get("episode_number")
        excerpt = str(pl.get("content") or "")[:220]
        sig = f"{eid}:{excerpt[:40]}"
        if sig in seen_cites:
            continue
        seen_cites.add(sig)
        citations.append(
            {
                "episode_id": eid,
                "episode_number": ep_num,
                "episode_label": str(ep_obj.label or ep_obj.number) if ep_obj else str(ep_num or ""),
                "title": ep_obj.title if ep_obj else "",
                "type": pl.get("type") or "memory",
                "excerpt": excerpt,
                "page_image_path": cover_by_ep.get(eid),
                "score": h.get("score", 0.0),
            }
        )

    # Match relevant characters mentioned in the question or citations
    q_lower = question.lower()
    matched_chars: list[dict] = []
    char_ids = [c["id"] for c in (ctx.get("character_dossier") or [])[:12]]
    avatar_by_asset: dict[str, str] = {}
    if char_ids:
        aims = (await db.execute(select(AssetImage).where(AssetImage.asset_id.in_(char_ids)))).scalars().all()
        for im in aims:
            if im.asset_id not in avatar_by_asset:
                avatar_by_asset[im.asset_id] = im.image_path
    for c in (ctx.get("character_dossier") or [])[:8]:
        if c["name"].lower() in q_lower or any(c["name"] in ci["excerpt"] for ci in citations[:5]):
            matched_chars.append(
                {
                    "id": c["id"],
                    "name": c["name"],
                    "role": c.get("role", ""),
                    "avatar_path": avatar_by_asset.get(c["id"]),
                }
            )

    # Assemble crisp grounded context for the LLM
    context_sections = [
        f"作品：{ctx.get('project_title', '')}",
        f"主线设定：{json.dumps((ctx.get('story_bible') or {}).get('main_plot') or {}, ensure_ascii=False)}",
        f"世界观法则：{ctx.get('canon_rules', '')[:2500]}",
        f"历史剧情纪要：\n{ctx.get('long_summary', '')[:3200]}",
        "最近章节摘要：\n"
        + "\n".join(
            f"- 第{r.get('label') or r.get('number')}话 ({r.get('title') or ''}): {r.get('summary', '')}"
            for r in (ctx.get("recent_episodes") or [])
        ),
        "核心角色档案：\n"
        + "\n".join(
            f"- {c['name']}: {c.get('description', '')[:160]} | 当前状态: {c.get('current_state', '')}"
            for c in (ctx.get("character_dossier") or [])[:12]
        ),
        "未回收伏笔：\n"
        + "\n".join(
            f"- [{p.get('priority_label')}] {p.get('description', '')[:180]}"
            for p in (ctx.get("active_pits") or [])[:12]
        ),
        "本次精准检索到的相关剧情片段：\n"
        + "\n".join(f"- [第{ci['episode_label']}话 · {ci['type']}] {ci['excerpt']}" for ci in citations[:8]),
    ]

    system_prompt = (
        "You are MangaForge Story Detective — a deeply knowledgeable manga archivist answering questions "
        "strictly based on the ingested manga chapters, Story Bible, character dossiers, and open plot threads.\n"
        "Rules:\n"
        "- Answer concisely and accurately in the same language as the user's question.\n"
        "- Cite exact episode numbers (e.g. 第3话, 第5话) whenever referencing events, quotes, or foreshadowing.\n"
        "- Never hallucinate chapters or facts that are not present in the provided manga context."
    )

    client = get_raw_openai_client()
    resp = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "\n\n".join(context_sections) + f"\n\n用户问题：{question}"},
        ],
        max_tokens=settings.OPENAI_MAX_TOKENS,
    )
    msg = resp.choices[0].message
    answer = (msg.content or "").strip()
    if not answer and getattr(msg, "reasoning_content", None):
        answer = str(msg.reasoning_content).strip()

    return {
        "question": question,
        "answer": answer or "暂未能从已导入的章节记忆中归纳出明确答案。",
        "model": settings.OPENAI_MODEL,
        "citations": citations[:6],
        "matched_characters": matched_chars[:6],
    }
