from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Chat, ChatRepo, Release, Repo


async def get_chat_repo(chat: Chat, repo: Repo, session: AsyncSession) -> ChatRepo:
    return (
        await session.execute(
            select(ChatRepo).where(
                ChatRepo.chat_id == chat.id,
                ChatRepo.repo_id == repo.id,
            ),
        )
    ).scalar_one()


async def get_latest_chat_release(session: AsyncSession, chat, repo) -> Release | None:
    if repo.releases:
        chat_repo = await get_chat_repo(chat, repo, session)

        if chat_repo.process_pre_releases:
            return repo.releases[-1]
        return await session.scalar(
            select(Release)
            .where(
                Release.repo_id == repo.id,
                Release.pre_release.is_(False),
            )
            .order_by(Release.id.desc())
        )
    return None
