from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CHAR, JSON, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.asset import Asset


class AssetImage(Base):
    __tablename__ = "asset_images"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    asset_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(50), nullable=False, comment="reference|thumbnail|turnaround|lora_dataset")
    image_path: Mapped[str] = mapped_column(String(500), nullable=False, comment="MinIO object key")
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="bbox, source episode, etc.")
    created_at: Mapped[datetime] = mapped_column(DateTime(6), nullable=False, server_default=func.now())

    asset: Mapped["Asset"] = relationship(back_populates="images")
