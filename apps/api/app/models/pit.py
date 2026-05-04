from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CHAR, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.project import Project


class Pit(Base):
    __tablename__ = "pits"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    introduced_episode_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("episodes.id"), nullable=False)
    resolved_episode_id: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey("episodes.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="open", comment="open|resolved|abandoned")
    trigger_hint: Mapped[str | None] = mapped_column(Text, nullable=True, comment="Trigger condition text")
    created_at: Mapped[datetime] = mapped_column(DateTime(6), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(6), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="pits")
