from sqlalchemy import ForeignKey, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import Base


class ChatRepo(Base):
    __tablename__ = "chat_repo"
    chat_id: Mapped[int] = mapped_column(
        ForeignKey("chat.id", ondelete="CASCADE"),
        primary_key=True,
    )
    repo_id: Mapped[int] = mapped_column(
        ForeignKey("repo.id", ondelete="CASCADE"), primary_key=True
    )
    process_pre_releases: Mapped[bool] = mapped_column(
        default=True, server_default=true()
    )
    starred: Mapped[bool] = mapped_column(default=False, server_default=false())
