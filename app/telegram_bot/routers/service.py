import json
import logging
import re
import urllib.parse
from collections.abc import Awaitable, Callable
from typing import cast

import httpx
import requirements
from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Document, InputRichMessage, LinkPreviewOptions, Message
from github import Github, GithubException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app._version import __version__
from app.database.models import Chat, ChatRepo, Release, Repo
from app.repo_engine import format_release_message
from app.services.subscriprion_service import add_repo

logger = logging.getLogger(__name__)
router = Router()


@router.message(CommandStart())
async def start_command(message: Message):
    await message.answer(
        "Send a message containing repo for subscribing in one of the following formats: owner/repo, https://github.com/owner/repo",
    )


@router.message(Command("about"))
async def about_command(message: Message):
    await message.answer(
        f"release-bot - a telegram bot for GitHub releases v{__version__}\n"
        "Source code available at https://github.com/nickb686/release-bot",
    )


@router.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "For subscribe to a new GitHub releases send a message containing owner and name of repo (owner/repo), GitHub/PyPI/npm URL or upload requirements.txt or package.json file.\n\n"
        "Available commands:\n"
        "/start - show welcome message\n"
        "/about - information about this bot\n"
        "/help - brief usage info\n"
        "/list - show your subscriptions\n"
        "/editlist - show and edit your subscriptions\n"
        "/delete - (in reply to release note message) unsubscribe from repo\n"
        "/delete owner/repo - unsubscribe from specified repo\n"
        "/prerelease - (in reply to release note message) unsubscribe from pre-releases of specified repo\n"
        "/prerelease owner/repo - unsubscribe from pre-releases of specified repo\n"
        "/starred username - subscribe to user's starred repos\n"
        "/starred - unsubscribe from user's starred repos\n"
        "/settings - change output format\n"
        "/stats - basic server statistics",
    )


@router.message(F.text.startswith("/"))
async def unknown_command(message: Message, bot: Bot) -> None:
    if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        text = cast("str", message.text).lower()
        bot_name = str((await bot.get_me()).username).lower()
        if len(text) > 2 and "@" in text[1:] and f"@{bot_name}" not in text:
            return

    await message.answer(
        "Sorry, I don't understand. Please pick one of the valid options.",
    )
    await start_command(message)


MAX_UPLOADED_FILE_SIZE = 1024 * 10  # 10kB
direct_pattern = re.compile(".+/.+")
github_link_pattern = re.compile("https://github.com/([^/]+/[^/]+)/?")
pypi_link_pattern = re.compile("https://pypi.org/project/(.+)/")
npm_link_pattern = re.compile("https://www.npmjs.com/package/(.+)")


@router.message(Command("stats"))
async def stats_command(message: Message, session: AsyncSession) -> None:
    """Send a message when the command /stats is issued."""
    release_count = await session.scalar(select(func.count()).select_from(Release))
    repo_count = await session.scalar(select(func.count()).select_from(Repo))
    user_count = await session.scalar(select(func.count()).select_from(Chat))
    subscription_count = await session.scalar(
        select(func.count()).select_from(ChatRepo),
    )

    text = (
        f"I have to update {release_count} releases for {repo_count} repos via "
        f"{subscription_count} subscriptions added by {user_count} users."
    )

    await message.answer(text)


@router.message(Command("test"))
async def test_command(
    message: Message,
    command: CommandObject,
    chat: Chat,
    github_obj: Github,
    bot: Bot,
) -> None:
    """Send a message when the command /test is issued."""
    if not command.args or len(command.args.split()) != 1:
        await message.answer("Specify a GitHub release URL")
        return

    github_release_url = command.args.split()[0]
    path_parts = urllib.parse.urlparse(github_release_url).path.strip("/").split("/")
    if len(path_parts) < 5 or path_parts[2] != "releases" or path_parts[3] != "tag":
        await message.answer("Wrong GitHub release URL")
        return

    repo = github_obj.get_repo(f"{path_parts[0]}/{path_parts[1]}")
    release = repo.get_release(path_parts[4])

    release.updated = False  # pyrefly: ignore [missing-attribute]

    await bot.send_rich_message(
        chat_id=chat.id, rich_message=InputRichMessage(markdown=release.body)
    )

    text, parse_mode, entities = format_release_message(
        chat.release_note_format,
        repo,
        release,
    )

    await bot.send_message(
        chat.id,
        text,
        parse_mode=parse_mode,
        entities=entities,
        link_preview_options=LinkPreviewOptions(
            url=repo.html_url,
            prefer_small_media=True,
        ),
    )


def _first_github_repo(urls: dict, keys: list[str]) -> str | None:
    for key in keys:
        url = urls.get(key)
        if url and (match := github_link_pattern.search(url)):
            return match.group(1)
    return None


async def _pypi2github(project_name: str) -> tuple[int, str | None]:
    resp = await httpx.AsyncClient().get(
        url=f"https://pypi.org/pypi/{project_name}/json"
    )
    if resp.status_code != 200:
        return resp.status_code, None

    info = json.loads(resp.content.decode("utf-8"))["info"]

    if info["project_urls"]:
        repo_name = _first_github_repo(
            info["project_urls"],
            ["Source", "Source Code", "Homepage"],
        )
    else:
        repo_name = _first_github_repo({"home_page": info["home_page"]}, ["home_page"])

    return resp.status_code, repo_name


async def _npm2github(package_name: str) -> tuple[int, str | None]:
    package_name_quoted = urllib.parse.quote(package_name, safe="")
    resp = await httpx.AsyncClient().get(
        f"https://api.npms.io/v2/package/{package_name_quoted}"
    )
    if resp.status_code != 200:
        return resp.status_code, None

    links = json.loads(resp.content.decode("utf-8"))["collected"]["metadata"]["links"]
    repo_name = _first_github_repo(links, ["repository", "homepage"])

    return resp.status_code, repo_name


async def _resolve_repo_name_from_link(
    message: Message,
    project: str,
    resolver: Callable[[str], Awaitable[tuple[int, str | None]]],
) -> str | None:
    status, repo_name = await resolver(project)
    if status != 200:
        await message.answer("Error: Invalid repo.")
        return None
    if not repo_name:
        await message.answer(f"Project {project} has not link to GitHub repository.")
        return None
    return repo_name


async def _add_repos_from_packages(
    chat: Chat,
    package_names,
    resolver,
    bot: Bot,
    session: AsyncSession,
    github_client: Github,
) -> None:
    for name in package_names:
        status, repo_name = await resolver(name)
        if status == 200 and repo_name:
            try:
                repo = github_client.get_repo(repo_name)
            except GithubException:
                logger.exception("Github Exception in download_file for %s", name)
                continue

            await add_repo(chat.id, repo, bot, session, True)


@router.message(F.document)
async def download_file(
    message: Message,
    session: AsyncSession,
    bot: Bot,
    github_client: Github,
    chat: Chat,
) -> None:
    """Add GitHub repo from uploaded requirements.txt"""
    document = cast("Document", message.document)

    if document.file_size and document.file_size > MAX_UPLOADED_FILE_SIZE:
        await message.answer("I can't process too big file.")
        return

    if document.file_name == "requirements.txt":
        buffer = await bot.download(document)
        if buffer is None:
            await message.answer("Failed to download the file.")
            return
        decoded_string = buffer.read().decode("utf-8", errors="replace")

        package_names = [req.name for req in requirements.parse(decoded_string)]
        await _add_repos_from_packages(
            chat,
            package_names,
            _pypi2github,
            bot,
            session,
            github_client,
        )

    elif document.file_name == "package.json":
        buffer = await bot.download(document)
        if buffer is None:
            await message.answer("Failed to download the file.")
            return
        decoded_string = buffer.read().decode("utf-8", errors="replace")
        json_data = json.loads(decoded_string)

        package_names = json_data.get("dependencies", {}).keys()
        await _add_repos_from_packages(
            chat,
            package_names,
            _npm2github,
            bot,
            session,
            github_client,
        )

    else:
        await message.answer("I don't know this file format.")


@router.message(F.text)
async def other_message(
    message: Message,
    session: AsyncSession,
    bot: Bot,
    github_obj: Github,
    chat: Chat,
) -> None:
    """Add GitHub repo"""
    text = cast("str", message.text)
    if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        bot_name = cast("str", (await bot.get_me()).username).lower()
        if not text.lower().startswith(f"@{bot_name}"):
            return

    if match := pypi_link_pattern.search(text):
        repo_name = await _resolve_repo_name_from_link(
            message,
            match.group(1),
            _pypi2github,
        )
        if repo_name is None:
            return
    elif match := npm_link_pattern.search(text):
        repo_name = await _resolve_repo_name_from_link(
            message,
            match.group(1),
            _npm2github,
        )
        if repo_name is None:
            return
    elif match := github_link_pattern.search(text):
        repo_name = match.group(1)
    elif direct_pattern.search(text):
        repo_name = text
    else:
        await message.answer("Error: Invalid repo.")
        return

    try:
        repo = github_obj.get_repo(repo_name)
    except GithubException:
        await message.answer("Sorry, I can't find that repo.")
        logger.exception("GithubException for %s in message", repo_name)
        return

    await add_repo(chat.id, repo, bot, session, False)
