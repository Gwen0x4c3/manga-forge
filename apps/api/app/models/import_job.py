from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CHAR, JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.branch import Branch
    from app.models.import_job_item import ImportJobItem
    from app.models.project import Project
    from app.models.source_binding import SourceBinding


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    branch_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    binding_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("source_bindings.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="mangadex")
    job_type: Mapped[str] = mapped_column(String(50), nullable=False, default="discover")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="queued")
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_series_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    progress: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(6), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(6), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(6), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(6), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="import_jobs")
    branch: Mapped["Branch"] = relationship()
    binding: Mapped["SourceBinding | None"] = relationship(back_populates="jobs")
    items: Mapped[list["ImportJobItem"]] = relationship(back_populates="job", cascade="all, delete-orphan")
