from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.database.models import Chat, Release

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base


class Repo(Base):
    __tablename__ = "repo"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(String)
    link: Mapped[str] = mapped_column(String)
    archived: Mapped[bool | None] = mapped_column(Boolean)
    blocked: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    chats: Mapped[list[Chat]] = relationship(
        "Chat", secondary="chat_repo", back_populates="repos"
    )
    releases: Mapped[list[Release]] = relationship(
        "Release", back_populates="repos", cascade="all, delete-orphan"
    )

    def is_orphan(self):
        # TODO: Use SQL COUNT instead Python len
        return len(self.chats) == 0

    def get_latest_release(self):
        return self.releases[-1] if self.releases else None
