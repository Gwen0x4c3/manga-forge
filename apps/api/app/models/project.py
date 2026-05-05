from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CHAR, JSON, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.asset import Asset
    from app.models.branch import Branch
    from app.models.episode import Episode
    from app.models.import_job import ImportJob
    from app.models.pit import Pit
    from app.models.source_binding import SourceBinding


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="zh")
    canon_rules: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="Hard settings, manually edited")
    long_summary: Mapped[str | None] = mapped_column(Text, nullable=True, comment="Compressed historical summary")
    created_at: Mapped[datetime] = mapped_column(DateTime(6), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(6), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    branches: Mapped[list["Branch"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    episodes: Mapped[list["Episode"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    assets: Mapped[list["Asset"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    pits: Mapped[list["Pit"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    source_bindings: Mapped[list["SourceBinding"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    import_jobs: Mapped[list["ImportJob"]] = relationship(back_populates="project", cascade="all, delete-orphan")
