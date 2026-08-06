import logging

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import LinkPreviewOptions
from github import GithubException, UnknownObjectException
from github.GitRelease import GitRelease
from github.Repository import Repository
from github.Tag import Tag
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal
from app.database.models import Chat, Repo
from app.database.models.chat_repo import ChatRepo
from app.github_obj import github_obj
from app.repo_engine import format_release_message, store_latest_release
from app.telegram_bot import add_starred_repos

logger = logging.getLogger(__name__)


async def _notify_user(
    message: str,
    chat: Chat,
    bot,
    session: AsyncSession,
    **kwargs,
) -> None:
    try:
        await bot.send_message(chat=chat.id, text=message, **kwargs)
    except TelegramForbiddenError:
        logger.info("Bot was blocked by the user")
        await session.delete(chat)
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
        for chat in repo_obj.chats:
            await _notify_user(
                message,
                chat,
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
            for chat in repo_obj.chats:
                await _notify_user(
                    message,
                    chat,
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
        for repo_obj in await session.scalars(select(Repo)):
            # TODO: Filter blocked repos from SQL query
            if repo_obj.blocked or not (
                repo := await fetch_repo(repo_obj, session, bot)
            ):
                continue

            if repo.archived and not repo_obj.archived:
                message = f"GitHub repo <b>{repo_obj.full_name}</b> has been archived"
                logger.info(message)
                for chat in repo_obj.chats:
                    await _notify_user(message, chat, bot, session, url=repo_obj.link)
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

                for chat in repo_obj.chats:
                    message, parse_mode, entities = format_release_message(
                        chat.release_note_format,
                        repo,
                        release,
                    )
                    await _notify_user(
                        message,
                        chat,
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

                for chat in repo_obj.chats:
                    await _notify_user(
                        message,
                        chat,
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

                for chat in repo_obj.chats:
                    chat_repo = session.scalar(
                        select(ChatRepo).where(
                            ChatRepo.chat_id == chat.id,
                            ChatRepo.repo_id == repo_obj.id,
                        ),
                    )
                    if (
                        isinstance(chat_repo, ChatRepo)
                        and not chat_repo.process_pre_releases
                    ):
                        break

                    message, parse_mode, entities = format_release_message(
                        chat.release_note_format,
                        repo,
                        release,
                    )
                    await _notify_user(
                        message,
                        chat,
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
        stmt = select(Chat).where(Chat.github_username.is_not(None))
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

            for repo_obj in chat.repos:
                try:
                    repo = github_obj.get_repo(repo_obj.id)
                except GithubException as e:
                    if e.status == 451:
                        message = f"GitHub repo {repo_obj.full_name} has been blocked"
                        logger.info(message)
                    else:
                        raise
                    continue

                starred = repo in github_user.get_starred()
                chat_repo = session.scalar(
                    select(ChatRepo).where(
                        ChatRepo.chat_id == chat.id,
                        ChatRepo.repo_id == repo_obj.id,
                    ),
                )
                if isinstance(chat_repo, ChatRepo) and chat_repo.starred != starred:
                    chat_repo.starred = starred
                    await session.commit()


async def clear_db():
    async with SessionLocal() as session:
        for repo_obj in await session.scalars(select(Repo)):
            #  TODO: Use sqlalchemy_utils.auto_delete_orphans
            if repo_obj.is_orphan():
                logger.info("Delete orphaned GitHub repo %s", repo_obj.full_name)
                await session.delete(repo_obj)
        await session.commit()
