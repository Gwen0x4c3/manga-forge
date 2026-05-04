from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CHAR, JSON, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.episode import Episode


class Panel(Base):
    __tablename__ = "panels"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    episode_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False)
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    panel_index: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="{x, y, w, h}")
    image_path: Mapped[str | None] = mapped_column(Text, nullable=True, comment="MinIO object key for crop")
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    episode: Mapped["Episode"] = relationship(back_populates="panels")
