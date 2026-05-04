from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CHAR, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.episode import Episode
    from app.models.project import Project


class Branch(Base):
    __tablename__ = "branches"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    base_branch_id: Mapped[str | None] = mapped_column(CHAR(36), nullable=True, comment="Fork source branch")
    base_episode_id: Mapped[str | None] = mapped_column(CHAR(36), nullable=True, comment="Episode from which forked")
    created_at: Mapped[datetime] = mapped_column(DateTime(6), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(6), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="branches")
    episodes: Mapped[list["Episode"]] = relationship(back_populates="branch", cascade="all, delete-orphan")
