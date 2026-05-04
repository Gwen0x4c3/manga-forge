from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CHAR, JSON, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.episode import Episode


class EpisodeMemory(Base):
    __tablename__ = "episode_memories"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    episode_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="summary|events|state_snapshot|ocr_dump|script_outline|storyboard_json|diff_report",
    )
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(6), nullable=False, server_default=func.now())

    episode: Mapped["Episode"] = relationship(back_populates="memories")
