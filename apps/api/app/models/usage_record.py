from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CHAR, JSON, BigInteger, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UsageRecord(Base):
    """Per-invocation telemetry record for every LLM, Embedding, and Image Generation call."""

    __tablename__ = "usage_records"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str | None] = mapped_column(CHAR(36), nullable=True, index=True)
    episode_id: Mapped[str | None] = mapped_column(CHAR(36), nullable=True, index=True)
    generation_run_id: Mapped[str | None] = mapped_column(CHAR(36), nullable=True, index=True)

    kind: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True, comment="llm|embedding|image"
    )
    operation: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="unknown",
        index=True,
        comment="understand|script|consistency_check|story_qa|render_plan|summarize_compress|embedding|image_generate|image_inpaint",
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="openai")
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="unknown", index=True)

    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    image_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    image_size: Mapped[str | None] = mapped_column(String(32), nullable=True)

    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="succeeded", index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(6), nullable=False, server_default=func.now(), index=True
    )
