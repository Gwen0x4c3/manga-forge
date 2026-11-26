from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.episode import Episode
from app.models.project import Project
from app.models.usage_record import UsageRecord
from app.schemas.usage import (
    UsageByModelItem,
    UsageByOperationItem,
    UsageDailyItem,
    UsageRecordItem,
    UsageRecordListResponse,
    UsageSummaryResponse,
    UsageTotals,
)


def _calc_cache_hit_rate(cache_read: int, input_tokens: int) -> float:
    if input_tokens <= 0 or cache_read <= 0:
        return 0.0
    return round(min(100.0, (cache_read / input_tokens) * 100.0), 2)


async def get_usage_summary(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    episode_id: str | None = None,
    days: int | None = None,
) -> UsageSummaryResponse:
    stmt = select(UsageRecord)
    if project_id:
        stmt = stmt.where(UsageRecord.project_id == project_id)
    if episode_id:
        stmt = stmt.where(UsageRecord.episode_id == episode_id)
    if days and days > 0:
        cutoff = datetime.now() - timedelta(days=days)
        stmt = stmt.where(UsageRecord.created_at >= cutoff)

    rows = (await db.execute(stmt.order_by(UsageRecord.created_at.asc()))).scalars().all()

    total_calls = len(rows)
    llm_calls = 0
    embedding_calls = 0
    image_calls = 0
    failed_calls = 0
    input_tokens = 0
    output_tokens = 0
    cache_read_tokens = 0
    cache_write_tokens = 0
    total_tokens = 0
    llm_input_tokens = 0
    llm_cache_read_tokens = 0
    total_images = 0
    total_duration_ms = 0
    llm_duration_ms = 0
    image_duration_ms = 0

    model_acc: dict[tuple[str, str, str], dict] = defaultdict(
        lambda: {
            "calls": 0,
            "failed_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "total_tokens": 0,
            "image_count": 0,
            "total_duration_ms": 0,
        }
    )
    op_acc: dict[tuple[str, str], dict] = defaultdict(
        lambda: {
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "total_tokens": 0,
            "image_count": 0,
            "total_duration_ms": 0,
        }
    )
    daily_acc: dict[str, dict] = defaultdict(
        lambda: {
            "llm_calls": 0,
            "image_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "total_tokens": 0,
            "image_count": 0,
        }
    )

    for r in rows:
        is_failed = r.status != "succeeded"
        if is_failed:
            failed_calls += 1

        if r.kind == "llm":
            llm_calls += 1
            llm_duration_ms += r.duration_ms
            llm_input_tokens += r.input_tokens
            llm_cache_read_tokens += r.cache_read_tokens
        elif r.kind == "embedding":
            embedding_calls += 1
        elif r.kind == "image":
            image_calls += 1
            image_duration_ms += r.duration_ms

        input_tokens += r.input_tokens
        output_tokens += r.output_tokens
        cache_read_tokens += r.cache_read_tokens
        cache_write_tokens += r.cache_write_tokens
        total_tokens += r.total_tokens
        total_images += r.image_count
        total_duration_ms += r.duration_ms

        mk = (r.kind, r.provider, r.model)
        m = model_acc[mk]
        m["calls"] += 1
        if is_failed:
            m["failed_calls"] += 1
        m["input_tokens"] += r.input_tokens
        m["output_tokens"] += r.output_tokens
        m["cache_read_tokens"] += r.cache_read_tokens
        m["cache_write_tokens"] += r.cache_write_tokens
        m["total_tokens"] += r.total_tokens
        m["image_count"] += r.image_count
        m["total_duration_ms"] += r.duration_ms

        ok = (r.operation, r.kind)
        o = op_acc[ok]
        o["calls"] += 1
        o["input_tokens"] += r.input_tokens
        o["output_tokens"] += r.output_tokens
        o["cache_read_tokens"] += r.cache_read_tokens
        o["cache_write_tokens"] += r.cache_write_tokens
        o["total_tokens"] += r.total_tokens
        o["image_count"] += r.image_count
        o["total_duration_ms"] += r.duration_ms

        day_key = r.created_at.strftime("%Y-%m-%d") if r.created_at else "unknown"
        d = daily_acc[day_key]
        if r.kind == "llm":
            d["llm_calls"] += 1
        elif r.kind == "image":
            d["image_calls"] += 1
        d["input_tokens"] += r.input_tokens
        d["output_tokens"] += r.output_tokens
        d["cache_read_tokens"] += r.cache_read_tokens
        d["cache_write_tokens"] += r.cache_write_tokens
        d["total_tokens"] += r.total_tokens
        d["image_count"] += r.image_count

    totals = UsageTotals(
        total_calls=total_calls,
        llm_calls=llm_calls,
        embedding_calls=embedding_calls,
        image_calls=image_calls,
        failed_calls=failed_calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        total_tokens=total_tokens,
        cache_hit_rate=_calc_cache_hit_rate(llm_cache_read_tokens, llm_input_tokens),
        total_images=total_images,
        total_duration_ms=total_duration_ms,
        avg_llm_duration_ms=int(llm_duration_ms / llm_calls) if llm_calls else 0,
        avg_image_duration_ms=int(image_duration_ms / image_calls) if image_calls else 0,
    )

    by_model = [
        UsageByModelItem(
            kind=k,
            provider=prov,
            model=mod,
            calls=v["calls"],
            failed_calls=v["failed_calls"],
            input_tokens=v["input_tokens"],
            output_tokens=v["output_tokens"],
            cache_read_tokens=v["cache_read_tokens"],
            cache_write_tokens=v["cache_write_tokens"],
            total_tokens=v["total_tokens"],
            cache_hit_rate=_calc_cache_hit_rate(v["cache_read_tokens"], v["input_tokens"]),
            image_count=v["image_count"],
            avg_duration_ms=int(v["total_duration_ms"] / v["calls"]) if v["calls"] else 0,
            total_duration_ms=v["total_duration_ms"],
        )
        for (k, prov, mod), v in sorted(
            model_acc.items(),
            key=lambda kv: (kv[1]["total_tokens"], kv[1]["image_count"], kv[1]["calls"]),
            reverse=True,
        )
    ]

    by_operation = [
        UsageByOperationItem(
            operation=op,
            kind=k,
            calls=v["calls"],
            input_tokens=v["input_tokens"],
            output_tokens=v["output_tokens"],
            cache_read_tokens=v["cache_read_tokens"],
            cache_write_tokens=v["cache_write_tokens"],
            total_tokens=v["total_tokens"],
            cache_hit_rate=_calc_cache_hit_rate(v["cache_read_tokens"], v["input_tokens"]),
            image_count=v["image_count"],
            avg_duration_ms=int(v["total_duration_ms"] / v["calls"]) if v["calls"] else 0,
        )
        for (op, k), v in sorted(op_acc.items(), key=lambda kv: kv[1]["calls"], reverse=True)
    ]

    daily = [
        UsageDailyItem(date=day, **vals)
        for day, vals in sorted(daily_acc.items(), key=lambda kv: kv[0])
    ]

    return UsageSummaryResponse(
        totals=totals,
        by_model=by_model,
        by_operation=by_operation,
        daily=daily,
    )


async def list_usage_records(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    episode_id: str | None = None,
    kind: str | None = None,
    model: str | None = None,
    operation: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> UsageRecordListResponse:
    base = select(UsageRecord)
    if project_id:
        base = base.where(UsageRecord.project_id == project_id)
    if episode_id:
        base = base.where(UsageRecord.episode_id == episode_id)
    if kind:
        base = base.where(UsageRecord.kind == kind)
    if model:
        base = base.where(UsageRecord.model == model)
    if operation:
        base = base.where(UsageRecord.operation == operation)
    if status:
        base = base.where(UsageRecord.status == status)

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        await db.execute(
            base.order_by(UsageRecord.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    proj_ids = list({r.project_id for r in rows if r.project_id})
    ep_ids = list({r.episode_id for r in rows if r.episode_id})

    proj_titles: dict[str, str] = {}
    if proj_ids:
        for pid, title in (
            await db.execute(select(Project.id, Project.title).where(Project.id.in_(proj_ids)))
        ).all():
            proj_titles[pid] = title

    ep_labels: dict[str, str] = {}
    if ep_ids:
        for eid, label, num in (
            await db.execute(select(Episode.id, Episode.label, Episode.number).where(Episode.id.in_(ep_ids)))
        ).all():
            ep_labels[eid] = label or str(num)

    items = [
        UsageRecordItem(
            id=r.id,
            project_id=r.project_id,
            project_title=proj_titles.get(r.project_id) if r.project_id else None,
            episode_id=r.episode_id,
            episode_label=ep_labels.get(r.episode_id) if r.episode_id else None,
            generation_run_id=r.generation_run_id,
            kind=r.kind,
            operation=r.operation,
            provider=r.provider,
            model=r.model,
            input_tokens=r.input_tokens,
            output_tokens=r.output_tokens,
            cache_read_tokens=r.cache_read_tokens,
            cache_write_tokens=r.cache_write_tokens,
            total_tokens=r.total_tokens,
            cache_hit_rate=_calc_cache_hit_rate(r.cache_read_tokens, r.input_tokens),
            image_count=r.image_count,
            image_size=r.image_size,
            duration_ms=r.duration_ms,
            status=r.status,
            error=r.error,
            meta=r.meta,
            created_at=r.created_at,
        )
        for r in rows
    ]

    return UsageRecordListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )
