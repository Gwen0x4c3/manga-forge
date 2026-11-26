from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class UsageTotals(BaseModel):
    total_calls: int = 0
    llm_calls: int = 0
    embedding_calls: int = 0
    image_calls: int = 0
    failed_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    total_tokens: int = 0
    cache_hit_rate: float = 0.0
    total_images: int = 0
    total_duration_ms: int = 0
    avg_llm_duration_ms: int = 0
    avg_image_duration_ms: int = 0


class UsageByModelItem(BaseModel):
    kind: str
    provider: str
    model: str
    calls: int
    failed_calls: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    total_tokens: int
    cache_hit_rate: float
    image_count: int
    avg_duration_ms: int
    total_duration_ms: int


class UsageByOperationItem(BaseModel):
    operation: str
    kind: str
    calls: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    total_tokens: int
    cache_hit_rate: float
    image_count: int
    avg_duration_ms: int


class UsageDailyItem(BaseModel):
    date: str
    llm_calls: int
    image_calls: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    total_tokens: int
    image_count: int


class UsageSummaryResponse(BaseModel):
    totals: UsageTotals
    by_model: list[UsageByModelItem]
    by_operation: list[UsageByOperationItem]
    daily: list[UsageDailyItem]


class UsageRecordItem(BaseModel):
    id: str
    project_id: str | None = None
    project_title: str | None = None
    episode_id: str | None = None
    episode_label: str | None = None
    generation_run_id: str | None = None
    kind: str
    operation: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    total_tokens: int
    cache_hit_rate: float
    image_count: int
    image_size: str | None = None
    duration_ms: int
    status: str
    error: str | None = None
    meta: dict[str, Any] | None = None
    created_at: datetime


class UsageRecordListResponse(BaseModel):
    items: list[UsageRecordItem]
    total: int
    page: int
    page_size: int
