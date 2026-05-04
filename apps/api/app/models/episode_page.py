from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CHAR, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.episode import Episode


class EpisodePage(Base):
    __tablename__ = "episode_pages"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    episode_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False)
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    image_path: Mapped[str] = mapped_column(String(500), nullable=False, comment="MinIO object key")
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True, comment="SHA-256 for dedup")
    created_at: Mapped[datetime] = mapped_column(DateTime(6), nullable=False, server_default=func.now())

    episode: Mapped["Episode"] = relationship(back_populates="pages")
