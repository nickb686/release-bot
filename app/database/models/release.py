from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base

if TYPE_CHECKING:
    from app.database.models import Repo


class Release(Base):
    __tablename__ = "release"

    id: Mapped[int] = mapped_column(primary_key=True)
    release_id: Mapped[int | None] = mapped_column(Integer)
    tag_name: Mapped[str] = mapped_column(String)
    release_date: Mapped[datetime | None] = mapped_column(DateTime)
    link: Mapped[str | None] = mapped_column(String)
    pre_release: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    repo_id: Mapped[int | None] = mapped_column(ForeignKey("repo.id"))
    repos: Mapped[Repo | None] = relationship("Repo", back_populates="releases")
