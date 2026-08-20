import logging

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import LinkPreviewOptions
from github import GithubException, UnknownObjectException
from github.GitRelease import GitRelease
from github.Repository import Repository
from github.Tag import Tag
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import SessionLocal
from app.database.models import Chat, Repo
from app.database.models.chat_repo import ChatRepo
from app.github_obj import github_obj
from app.repo_engine import store_latest_release
from app.services.subscriprion_service import add_starred_repos
from app.telegram_bot.format import format_release_message

logger = logging.getLogger(__name__)


async def _notify_user(
    message: str,
    chat_id: int,
    bot,
    session: AsyncSession,
    **kwargs,
) -> None:
    try:
        await bot.send_message(chat=chat_id, text=message, **kwargs)
    except TelegramForbiddenError:
        logger.info("Bot was blocked by the user")
        await session.execute(delete(Chat).where(Chat.id == chat_id))
        await session.commit()


async def fetch_repo(
    repo_obj: Repo,
    session: AsyncSession,
    bot: Bot,
) -> Repository | None:
    try:
        logger.info("Poll GitHub repo %s", repo_obj.full_name)
        return github_obj.get_repo(repo_obj.id)

    except UnknownObjectException:
        message = f"GitHub repo {repo_obj.full_name} has been deleted"
        logger.info(message)
        for chat_repo in repo_obj.chat_repos:
            await _notify_user(
                message,
                chat_repo.chat.id,
                bot,
                session,
                disable_web_page_preview=True,
            )
        await session.delete(repo_obj)
        await session.commit()

    except GithubException as e:
        if e.status in (403, 451):
            message = f"GitHub repo {repo_obj.full_name} has been blocked"
            logger.info(message)
            for chat_repo in repo_obj.chat_repos:
                await _notify_user(
                    message,
                    chat_repo.chat.id,
                    bot,
                    session,
                    disable_web_page_preview=True,
                )
            repo_obj.blocked = True
            await session.commit()

        else:
            logger.error(
                "GithubException for %s in poll_github: %s",
                repo_obj.full_name,
                e,
            )
    return None


async def poll_github(bot: Bot):
    async with SessionLocal() as session:
        for repo_obj in await session.scalars(
            select(Repo).options(
                selectinload(Repo.chat_repos).joinedload(ChatRepo.chat)
            )
        ):
            # TODO: Filter blocked repos from SQL query
            if repo_obj.blocked or not (
                repo := await fetch_repo(repo_obj, session, bot)
            ):
                continue

            if repo.archived and not repo_obj.archived:
                message = f"GitHub repo <b>{repo_obj.full_name}</b> has been archived"
                logger.info(message)
                for chat_repo in repo_obj.chat_repos:
                    await _notify_user(
                        message, chat_repo.chat.id, bot, session, url=repo_obj.link
                    )
                repo_obj.archived = repo.archived
                await session.commit()

            elif not repo.archived and repo_obj.archived:
                repo_obj.archived = repo.archived
                await session.commit()

            release_or_tag, prerelease = await store_latest_release(
                session,
                repo,
                repo_obj,
            )
            if isinstance(release_or_tag, GitRelease):
                release = release_or_tag
                logger.info("Process new release %s", release.name)

                for chat_repo in repo_obj.chat_repos:
                    message, parse_mode, entities = format_release_message(
                        chat_repo.chat.release_note_format,
                        repo,
                        release,
                    )
                    await _notify_user(
                        message,
                        chat_repo.chat.id,
                        bot,
                        session,
                        parse_mode=parse_mode,
                        entities=entities,
                        link_preview_options=LinkPreviewOptions(
                            url=repo_obj.link,
                            prefer_small_media=True,
                        ),
                    )
            elif isinstance(release_or_tag, Tag):
                tag = release_or_tag
                logger.info("Process new tag %s", tag.name)

                # TODO: Use tag.message as release_body text
                message = (
                    f"<a href='{repo.html_url}'>{repo.full_name}</a>:\n"
                    f"<code>{tag.name}</code>"
                )

                for chat_repo in repo_obj.chat_repos:
                    await _notify_user(
                        message,
                        chat_repo.chat.id,
                        bot,
                        session,
                        parse_mode=ParseMode.HTML,
                        link_preview_options=LinkPreviewOptions(
                            url=repo_obj.link,
                            prefer_small_media=True,
                        ),
                    )
            if isinstance(prerelease, GitRelease):
                release = prerelease
                logger.info("Process new prerelease %s", release.name)

                for chat_repo in repo_obj.chat_repos:
                    if (
                        isinstance(chat_repo, ChatRepo)
                        and not chat_repo.process_pre_releases
                    ):
                        continue

                    message, parse_mode, entities = format_release_message(
                        chat_repo.chat.release_note_format,
                        repo,
                        release,
                    )
                    await _notify_user(
                        message,
                        chat_repo.chat.id,
                        bot,
                        session,
                        entities=entities,
                        link_preview_options=LinkPreviewOptions(
                            url=repo_obj.link,
                            prefer_small_media=True,
                        ),
                    )


async def poll_github_user(bot: Bot):
    async with SessionLocal() as session:
        stmt = (
            select(Chat)
            .options(selectinload(Chat.chat_repos).joinedload(ChatRepo.repo))
            .where(Chat.github_username.is_not(None))
        )
        for chat in await session.scalars(stmt):
            try:
                github_user = github_obj.get_user(chat.github_username)  # pyrefly: ignore [bad-argument-type]
            except GithubException:
                logger.error("Can't found user '%s'", chat.github_username)
                continue

            try:
                await add_starred_repos(chat.id, github_user, bot, session)
            except TelegramForbiddenError:
                logger.info("Bot was blocked by the user")
                await session.delete(chat)
                await session.commit()

            starred_names = {r.full_name for r in github_user.get_starred()}
            for chat_repo in chat.chat_repos:
                try:
                    repo = github_obj.get_repo(chat_repo.repo_id)
                except GithubException as e:
                    if e.status == 451:
                        message = (
                            f"GitHub repo {chat_repo.repo.full_name} has been blocked"
                        )
                        logger.info(message)
                    else:
                        raise
                    continue

                starred = repo.full_name in starred_names
                if isinstance(chat_repo, ChatRepo) and chat_repo.starred != starred:
                    chat_repo.starred = starred
                    await session.flush()
        await session.commit()


async def clear_db():
    async with SessionLocal() as session:
        for repo_obj in await session.scalars(
            select(Repo).options(selectinload(Repo.chat_repos))
        ):
            #  TODO: Use sqlalchemy_utils.auto_delete_orphans
            if repo_obj.is_orphan():
                logger.info("Delete orphaned GitHub repo %s", repo_obj.full_name)
                await session.delete(repo_obj)
        await session.commit()
