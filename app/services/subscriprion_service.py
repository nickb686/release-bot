from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import LinkPreviewOptions
from github.AuthenticatedUser import AuthenticatedUser
from github.NamedUser import NamedUser
from github.Repository import Repository
from sqlalchemy import ScalarResult, exists, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.database.models import ChatRepo, Release, Repo
from app.repo_engine import store_latest_release
from config import settings


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


async def is_subscribed(session: AsyncSession, chat_id: int, repo_id: int) -> bool:
    return (
        await session.execute(
            select(
                exists().where(
                    ChatRepo.chat_id == chat_id,
                    ChatRepo.repo_id == repo_id,
                ),
            ),
        )
    ).scalar_one()


async def add_repo(
    chat_id: int,
    github_repo: Repository,
    bot: Bot,
    session: AsyncSession,
    silent: bool = False,
) -> None:
    stmt = select(func.count()).select_from(ChatRepo).where(ChatRepo.chat_id == chat_id)
    repo_count: int = (await session.execute(stmt)).scalar_one()

    if (
        settings.service.MAX_REPOS_PER_CHAT
        and repo_count >= settings.service.MAX_REPOS_PER_CHAT
    ):
        if not silent:
            await bot.send_message(
                chat_id=chat_id,
                text="Maximum number of repos per user reached.",
            )
        return

    repo_obj = await session.scalar(
        select(Repo)
        .options(selectinload(Repo.releases))
        .where(Repo.id == github_repo.id)
    )
    if not repo_obj:
        repo_obj = Repo(
            id=github_repo.id,
            full_name=github_repo.full_name,
            description=github_repo.description,
            link=github_repo.html_url,
            archived=github_repo.archived,
        )

        await store_latest_release(session, github_repo, repo_obj)

        session.add(repo_obj)
        await session.flush()

    if await is_subscribed(session, chat_id, github_repo.id):
        if not silent:
            await bot.send_message(
                chat_id=chat_id,
                text=f"GitHub repo <b>{github_repo.full_name}</b> has already been added.",
                parse_mode=ParseMode.HTML,
                link_preview_options=LinkPreviewOptions(
                    url=github_repo.html_url,
                    prefer_small_media=True,
                ),
            )
    else:
        await session.execute(
            insert(ChatRepo).values(chat_id=chat_id, repo_id=github_repo.id)
        )
        await session.flush()

        if repo_obj.archived:
            text = (
                f"Added GitHub repo: <b>{github_repo.full_name}</b>, but it is archived"
            )
        elif repo_obj.get_latest_release():
            text = f"Added GitHub repo: <b>{github_repo.full_name}</b>"
        else:
            text = f"Added GitHub repo: <b>{github_repo.full_name}</b>, but it has no releases"

        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            link_preview_options=LinkPreviewOptions(
                url=github_repo.html_url,
                prefer_small_media=True,
            ),
        )


async def add_starred_repos(
    chat_id: int,
    github_user: NamedUser | AuthenticatedUser,
    bot: Bot,
    session: AsyncSession,
    silent: bool = True,
) -> None:
    repos = github_user.get_starred()
    stmt = select(func.count()).select_from(ChatRepo).where(ChatRepo.chat_id == chat_id)
    repo_count: int = (await session.execute(stmt)).scalar_one()
    repo_ids = [r.id for r in repos]
    existing_ids = set(
        await session.scalars(select(Repo.id).where(Repo.id.in_(repo_ids)))
    )
    subscribed_ids = set(
        await session.scalars(
            select(ChatRepo.repo_id).where(
                ChatRepo.chat_id == chat_id, ChatRepo.repo_id.in_(repo_ids)
            )
        )
    )
    new_rows = []
    for repo in repos:
        if (
            settings.service.MAX_REPOS_PER_CHAT
            and repo_count + 1 > settings.service.MAX_REPOS_PER_CHAT
        ):
            if not silent:
                await bot.send_message(
                    chat_id=chat_id,
                    text="Maximum number of repos per user reached.",
                )
            return
        if repo.id in subscribed_ids:
            continue
        if repo.id not in existing_ids:
            repo_obj = Repo(
                id=repo.id,
                full_name=repo.full_name,
                description=repo.description,
                link=repo.html_url,
                archived=repo.archived,
            )
            session.add(repo_obj)
            await store_latest_release(session, repo, repo_obj)
            existing_ids.add(repo.id)
        new_rows.append({"chat_id": chat_id, "repo_id": repo.id})
        repo_count += 1
    if new_rows:
        await session.execute(insert(ChatRepo), new_rows)
        await session.flush()
    await session.commit()


async def get_chat_repos_with_repo_by_chat_id(
    session: AsyncSession, chat_id: int
) -> ScalarResult[ChatRepo]:
    return await session.scalars(
        select(ChatRepo)
        .options(joinedload(ChatRepo.repo))
        .where(ChatRepo.chat_id == chat_id)
    )
