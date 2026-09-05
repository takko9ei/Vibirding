"""SQLAlchemy ORM mappings for the current database slice."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Float, Identity, Integer, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base shared by migrations and ORM mappings."""


class ObservationRow(Base):
    """Database representation of the v1-compatible Observation."""

    __tablename__ = "observations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    sequence_no: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=False),
        unique=True,
        nullable=False,
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    place: Mapped[str | None] = mapped_column(Text)
    obs_date: Mapped[str | None] = mapped_column(Text)
    time_of_day: Mapped[str | None] = mapped_column(Text)
    species: Mapped[str | None] = mapped_column(Text)
    count: Mapped[int | None] = mapped_column(Integer)
    behavior: Mapped[str | None] = mapped_column(Text)
    raw_note: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    flags: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
