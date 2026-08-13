from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.database.models import ChatRepo
from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models import Base


class Chat(Base):
    __tablename__ = "chat"

    id: Mapped[int] = mapped_column(primary_key=True)
    lang: Mapped[str] = mapped_column(String(2), default="en")
    github_username: Mapped[str | None] = mapped_column(String)
    release_note_format: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    chat_repos: Mapped[list[ChatRepo]] = relationship(
        "ChatRepo", back_populates="chat", cascade="all, delete-orphan", lazy="raise"
    )
