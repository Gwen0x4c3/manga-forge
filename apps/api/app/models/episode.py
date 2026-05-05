from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CHAR, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.branch import Branch
    from app.models.episode_external_ref import EpisodeExternalRef
    from app.models.episode_memory import EpisodeMemory
    from app.models.episode_page import EpisodePage
    from app.models.generation_run import GenerationRun
    from app.models.panel import Panel
    from app.models.project import Project


class Episode(Base):
    __tablename__ = "episodes"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    branch_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    number: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, comment="Sort order, system-managed")
    label: Mapped[str] = mapped_column(String(50), nullable=False, default="", comment="Author's original episode number, e.g. '36', '36.5', '番外1'")
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="import_local")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="imported")
    category: Mapped[str] = mapped_column(String(20), nullable=False, default="regular")
    parent_episode_id: Mapped[str | None] = mapped_column(CHAR(36), nullable=True, comment="DAG: fork/continuation")
    created_at: Mapped[datetime] = mapped_column(DateTime(6), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(6), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="episodes")
    branch: Mapped["Branch"] = relationship(back_populates="episodes")
    pages: Mapped[list["EpisodePage"]] = relationship(back_populates="episode", cascade="all, delete-orphan")
    panels: Mapped[list["Panel"]] = relationship(back_populates="episode", cascade="all, delete-orphan")
    memories: Mapped[list["EpisodeMemory"]] = relationship(back_populates="episode", cascade="all, delete-orphan")
    generation_runs: Mapped[list["GenerationRun"]] = relationship(
        back_populates="episode", cascade="all, delete-orphan"
    )
    external_refs: Mapped[list["EpisodeExternalRef"]] = relationship(
        back_populates="episode", cascade="all, delete-orphan"
    )
