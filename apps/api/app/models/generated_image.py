from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CHAR, JSON, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.generation_run import GenerationRun


class GeneratedImage(Base):
    __tablename__ = "generated_images"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    generation_run_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("generation_runs.id", ondelete="CASCADE"), nullable=False
    )
    episode_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False)
    panel_id: Mapped[str | None] = mapped_column(CHAR(36), nullable=True)
    image_path: Mapped[str] = mapped_column(String(500), nullable=False, comment="MinIO object key")
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="seed, prompt_hash, size, version")
    created_at: Mapped[datetime] = mapped_column(DateTime(6), nullable=False, server_default=func.now())

    generation_run: Mapped["GenerationRun"] = relationship(back_populates="generated_images")
