from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import ChatRepo, Release, Repo


async def get_chat_repo(chat_id: int, repo_id: int, session: AsyncSession) -> ChatRepo:
    return (
        await session.execute(
            select(ChatRepo).where(
                ChatRepo.chat_id == chat_id,
                ChatRepo.repo_id == repo_id,
            ),
        )
    ).scalar_one()


async def get_latest_chat_release(
    session: AsyncSession, chat_id: int, repo_id: int
) -> Release | None:
    stmt = (
        select(ChatRepo)
        .options(selectinload(ChatRepo.repo).selectinload(Repo.releases))
        .where(ChatRepo.chat_id == chat_id, ChatRepo.repo_id == repo_id)
    )
    chat_repo = (await session.execute(stmt)).scalar_one()
    if chat_repo.repo.releases:
        if chat_repo.process_pre_releases:
            return chat_repo.repo.releases[-1]
        return await session.scalar(
            select(Release)
            .where(
                Release.repo_id == repo_id,
                Release.pre_release.is_(False),
            )
            .order_by(Release.id.desc())
        )
    return None
