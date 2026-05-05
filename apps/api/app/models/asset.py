from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CHAR, JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.asset_image import AssetImage
    from app.models.project import Project


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False, comment="character|outfit|location|item|style")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="Prompt snippets, attributes")
    prompt_snippets: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="Multi-language prompt snippets {zh, ja, en}"
    )
    parent_asset_id: Mapped[str | None] = mapped_column(
        CHAR(36), nullable=True, comment="Outfit belongs to character"
    )
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="Embedding vector for clustering")
    episode_ids: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="Episode IDs where this asset appears, for cross-episode tracking"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(6), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(6), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="assets")
    images: Mapped[list["AssetImage"]] = relationship(back_populates="asset", cascade="all, delete-orphan")
