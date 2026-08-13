from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, false, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base

if TYPE_CHECKING:
    from app.database.models import Chat, Repo


class ChatRepo(Base):
    __tablename__ = "chat_repo"
    chat_id: Mapped[int] = mapped_column(
        ForeignKey("chat.id", ondelete="CASCADE"),
        primary_key=True,
    )
    repo_id: Mapped[int] = mapped_column(
        ForeignKey("repo.id", ondelete="CASCADE"),
        primary_key=True,
    )
    chat: Mapped[Chat] = relationship("Chat", back_populates="chat_repos", lazy="raise")
    repo: Mapped[Repo] = relationship("Repo", back_populates="chat_repos", lazy="raise")
    process_pre_releases: Mapped[bool] = mapped_column(
        default=True,
        server_default=true(),
    )
    starred: Mapped[bool] = mapped_column(default=False, server_default=false())
