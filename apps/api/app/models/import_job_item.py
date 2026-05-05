from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CHAR, JSON, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.episode import Episode
    from app.models.import_job import ImportJob


class ImportJobItem(Base):
    __tablename__ = "import_job_items"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("import_jobs.id", ondelete="CASCADE"), nullable=False)
    external_chapter_id: Mapped[str] = mapped_column(String(100), nullable=False)
    chapter_number: Mapped[str] = mapped_column(String(50), nullable=False)
    sort_number: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    volume: Mapped[str | None] = mapped_column(String(50), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    translated_language: Mapped[str] = mapped_column(String(20), nullable=False)
    group_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    group_names: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    page_count: Mapped[int | None] = mapped_column(nullable=True)
    selection_status: Mapped[str] = mapped_column(String(30), nullable=False, default="selected")
    import_status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    episode_id: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey("episodes.id", ondelete="SET NULL"), nullable=True)
    external_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(6), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(6), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    job: Mapped["ImportJob"] = relationship(back_populates="items")
    episode: Mapped["Episode | None"] = relationship()
