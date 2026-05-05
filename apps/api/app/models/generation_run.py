from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CHAR, JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.episode import Episode
    from app.models.generated_image import GeneratedImage


class GenerationRun(Base):
    __tablename__ = "generation_runs"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    episode_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False)
    stage: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="understand|script|render|layout|inpaint|train_lora"
    )
    backend: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="openai|local-qwen|comfyui")
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="temperature, seeds, steps, sampler...")
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieved_context: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="RAG hit fragments")
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="queued", comment="queued|running|succeeded|failed"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    commit_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(6), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(6), nullable=True)

    episode: Mapped["Episode"] = relationship(back_populates="generation_runs")
    generated_images: Mapped[list["GeneratedImage"]] = relationship(
        back_populates="generation_run", cascade="all, delete-orphan"
    )
