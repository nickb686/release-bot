import json
import re
import urllib.parse
from typing import Literal, cast

import requirements
import urllib3
from aiogram import Bot, F, Router
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    CallbackQuery,
    Chat,
    Document,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from github import Github, GithubException
from github.AuthenticatedUser import AuthenticatedUser
from github.NamedUser import NamedUser
from github.Repository import Repository
from sqlalchemy import delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app._version import __version__
from app.database.models import ChatRepo, Release, Repo
from app.repo_engine import format_release_message, store_latest_release
from app.services.chat_service import get_or_create_chat
from app.services.subscriprion_service import get_chat_repo, get_latest_chat_release
from config import settings

MAX_UPLOADED_FILE_SIZE = 1024 * 10  # 10kB
router = Router()


@router.message(CommandStart())
async def start_command(message: Message):
    await message.answer(
        "Send a message containing repo for subscribing in one of the following formats: "
        "owner/repo, https://github.com/owner/repo",
    )


@router.message(Command("about"))
async def about_command(message: Message):
    await message.answer(
        f"release-bot - a telegram bot for GitHub releases v{__version__}\n"
        "Source code available at https://github.com/JanisV/release-bot",
    )


@router.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "For subscribe to a new GitHub releases send a message containing owner and name of repo (owner/repo), "
        "GitHub/PyPI/npm URL or upload requirements.txt or package.json file.\n\n"
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


@router.message(Command("list"))
async def list_command(message: Message, session: AsyncSession):
    text = "Your subscriptions:\n"
    chat = await get_or_create_chat(session, message.chat.id)
    for i, repo_obj in enumerate(chat.repos):
        repo_emoji = ""
        if repo_obj.archived:
            repo_emoji += " 📦"
        if repo_obj.blocked:
            repo_emoji += " 🚫"

        chat_repo = get_chat_repo(chat, repo_obj, session)
        if chat_repo.starred:
            repo_emoji += " ⭐"

        text += f"{i + 1}. <b><a href='{repo_obj.link}'>{repo_obj.full_name}</a></b>{repo_emoji}\n"

    await message.answer(
        text,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
        parse_mode=ParseMode.HTML,
    )


direct_pattern = re.compile(".+/.+")


async def is_subscribed(session: AsyncSession, chat_id: int, repo_id: int) -> bool:
    return bool(
        await session.scalar(
            select(
                exists().where(ChatRepo.chat_id == chat_id, ChatRepo.repo_id == repo_id)
            )
        )
    )


async def _resolve_repo_from_command(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    usage_hint: str,
) -> Repo | None:
    if message.reply_to_message and message.reply_to_message.link_preview_options:
        repo_url = message.reply_to_message.link_preview_options.url
        return await session.scalar(select(Repo).where(Repo.link == repo_url))
    args = command.args.split() if command.args else []
    if len(args) != 1 or not direct_pattern.search(args[0]):
        await message.answer(usage_hint)
        return None
    return await session.scalar(select(Repo).where(Repo.full_name == args[0]))


async def _notify_repo(bot: Bot, chat_id: int, text: str, repo_url: str) -> None:
    await bot.send_message(
        chat_id,
        text,
        parse_mode=ParseMode.HTML,
        link_preview_options=LinkPreviewOptions(url=repo_url, prefer_small_media=True),
    )


async def _handle_repo_command(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    bot: Bot,
    usage_hint: str,
    action,  # Callable[[Chat, Repo], str] — мутирует и возвращает текст ответа
) -> None:
    repo_obj = await _resolve_repo_from_command(message, command, session, usage_hint)
    if repo_obj is None:
        return

    chat = await get_or_create_chat(session, message.chat.id)
    if not await is_subscribed(session, chat.id, repo_obj.id):
        await message.answer("Error: Repo not found.")
        return

    reply_message = action(chat, repo_obj)
    await session.flush()
    await _notify_repo(bot, chat.id, reply_message, repo_obj.link)


@router.message(Command("prerelease"))
async def prerelease_command(
    message: Message, command: CommandObject, session: AsyncSession, bot: Bot
) -> None:
    def toggle_prerelease(chat, repo_obj) -> str:
        chat_repo = get_chat_repo(chat, repo_obj, session)
        chat_repo.process_pre_releases = not chat_repo.process_pre_releases
        state = (
            "subscribed to" if chat_repo.process_pre_releases else "unsubscribed from"
        )
        return f"You are {state} repo <b>{repo_obj.full_name}</b> pre-releases."

    await _handle_repo_command(
        message,
        command,
        session,
        bot,
        "Specify a GitHub repo in the following format: /prerelease owner/repo",
        toggle_prerelease,
    )


@router.message(Command("delete"))
async def delete_command(
    message: Message, command: CommandObject, session: AsyncSession, bot: Bot
) -> None:
    def remove_repo(chat, repo_obj) -> str:
        chat.repos.remove(repo_obj)
        return f"Deleted repo: <b>{repo_obj.full_name}</b>"

    await _handle_repo_command(
        message,
        command,
        session,
        bot,
        "Specify a GitHub repo in the following format: /delete owner/repo",
        remove_repo,
    )


class RepoAction(CallbackData, prefix="repo"):
    action: Literal["pre", "delete"]
    page: int
    repo_id: int


class PageAction(CallbackData, prefix="page"):
    action: Literal["next", "prev"]
    page: int


class UserSubAction(CallbackData, prefix="user_sub"):
    action: Literal["subscribe", "add_repos", "unsubscribe"]
    username: str = ""


class ReleaseFormatAction(CallbackData, prefix="rel_fmt"):
    format: Literal["menu", "quote", "pre", "markdown", "html"]


async def get_repo_keyboard(
    chat_id: int, curr_page: int, session: AsyncSession
) -> InlineKeyboardMarkup | None:
    btn_per_line = 4
    lines = (100 - 3) // btn_per_line

    chat = await get_or_create_chat(session, chat_id)
    if len(chat.repos) == 0:
        return None

    builder = InlineKeyboardBuilder()
    page_repos = chat.repos[curr_page * lines : (curr_page + 1) * lines]

    for repo in page_repos:
        repo_name = repo.full_name.split("/")[1]
        latest_release = get_latest_chat_release(session, chat, repo)
        if latest_release:
            repo_current_tag = latest_release.tag_name
            repo_current_tag_url = (
                latest_release.link or f"{repo.link}/releases/tag/{repo_current_tag}"
            )
        else:
            repo_current_tag = "N/A"
            repo_current_tag_url = f"{repo.link}/releases"
        chat_repo = get_chat_repo(chat, repo, session)
        process_pre_releases = "✔️" if chat_repo.process_pre_releases else "❌"
        builder.row(
            InlineKeyboardButton(text=repo_name, url=repo.link),
            InlineKeyboardButton(text=repo_current_tag, url=repo_current_tag_url),
            InlineKeyboardButton(
                text=f"Pre: {process_pre_releases}️️",
                callback_data=RepoAction(
                    action="pre", page=curr_page, repo_id=repo.id
                ).pack(),
            ),
            InlineKeyboardButton(
                text="🗑️",
                callback_data=RepoAction(
                    action="delete", page=curr_page, repo_id=repo.id
                ).pack(),
            ),
        )

    if not page_repos:
        return builder.as_markup()

    has_next = len(chat.repos) > (curr_page + 1) * lines
    has_prev = curr_page > 0

    nav_row = []
    if has_prev:
        nav_row.append(
            InlineKeyboardButton(
                text="⬅️ Prev",
                callback_data=PageAction(action="prev", page=curr_page - 1).pack(),
            )
        )
    nav_row.append(InlineKeyboardButton(text="Cancel", callback_data="cancel"))
    if has_next:
        nav_row.append(
            InlineKeyboardButton(
                text="Next ➡️",
                callback_data=PageAction(action="next", page=curr_page + 1).pack(),
            )
        )
    builder.row(*nav_row)
    return builder.as_markup()


@router.message(Command("editlist"))
async def edit_list_command(message: Message, session: AsyncSession):
    keyboard = await get_repo_keyboard(message.chat.id, 0, session)
    if keyboard:
        await message.answer(
            "Here's all your added repos with their releases:",
            reply_markup=keyboard,
        )
    else:
        await message.answer("You don't have any repos yet.")


async def add_repo(
    chat_id: int, repo: Repository, bot: Bot, session: AsyncSession, silent=False
) -> None:

    chat = await get_or_create_chat(session, chat_id)
    # pyrefly: ignore [bad-assignment]
    repo_count: int = await session.scalar(
        select(func.count()).select_from(ChatRepo).where(ChatRepo.chat_id == chat_id)
    )
    if settings.MAX_REPOS_PER_CHAT and repo_count >= settings.MAX_REPOS_PER_CHAT:
        if not silent:
            await bot.send_message(
                chat_id=chat.id,
                text="Maximum number of repos per user reached.",
            )
        return

    repo_obj = await session.get(Repo, repo.id)
    if not repo_obj:
        repo_obj = Repo(
            id=repo.id,
            full_name=repo.full_name,
            description=repo.description,
            link=repo.html_url,
            archived=repo.archived,
        )

        await store_latest_release(session, repo, repo_obj)

        session.add(repo_obj)
        await session.flush()

    if await is_subscribed(session, chat.id, repo.id):
        if not silent:
            await bot.send_message(
                chat_id=chat.id,
                text=f"GitHub repo <b>{repo.full_name}</b> has already been added.",
                parse_mode=ParseMode.HTML,
                link_preview_options=LinkPreviewOptions(
                    url=repo.html_url, prefer_small_media=True
                ),
            )
    else:
        repo_obj.chats.append(chat)
        await session.flush()

        if repo_obj.archived:
            text = f"Added GitHub repo: <b>{repo.full_name}</b>, but it is archived"
        elif repo_obj.get_latest_release():
            text = f"Added GitHub repo: <b>{repo.full_name}</b>"
        else:
            text = f"Added GitHub repo: <b>{repo.full_name}</b>, but it has no releases"

        await bot.send_message(
            chat_id=chat.id,
            text=text,
            parse_mode=ParseMode.HTML,
            link_preview_options=LinkPreviewOptions(
                url=repo.html_url, prefer_small_media=True
            ),
        )


async def add_starred_repos(
    chat_id: int, github_user: NamedUser | AuthenticatedUser, bot: Bot, session: AsyncSession
) -> None:
    repos = github_user.get_starred()
    for repo in repos:
        await add_repo(chat_id, repo, bot, session, True)


@router.callback_query(F.data == "cancel")
async def cancel_btn(query: CallbackQuery):
    await query.answer()
    if isinstance(query.message, Message):
        await query.message.delete()


@router.callback_query(UserSubAction.filter(F.action == "unsubscribe"))
async def unsubscribe_btn(query: CallbackQuery, session: AsyncSession, chat_id: int) -> None:
    await query.answer()
    chat = await get_or_create_chat(session, chat_id)
    github_username = chat.github_username
    chat.github_username = None
    await session.flush()
    if github_username and isinstance(query.message, Message):
        await query.message.edit_text(text=f"Unsubscribed from user {github_username}.")


@router.callback_query(UserSubAction.filter(F.action == "subscribe"))
async def subscribe_btn(
    query: CallbackQuery,
    callback_data: UserSubAction,
    session: AsyncSession,
    github_client: Github,
    bot: Bot,
    chat_id: int,
):
    if isinstance(query.message, Message):
        await query.answer()
        try:
            github_user = github_client.get_user(callback_data.username)
        except GithubException:
            await query.message.answer("Error: User not found.")
            return

        chat = await get_or_create_chat(session, chat_id)
        chat.github_username = github_user.login
        await session.flush()

        await query.message.edit_text(
            text=f"Subscribed to user {github_user.login} starred repos."
        )
        await add_starred_repos(chat_id, github_user, bot, session)


@router.callback_query(UserSubAction.filter(F.action == "add_repos"))
async def add_repos_btn(
    query: CallbackQuery,
    callback_data: UserSubAction,
    session: AsyncSession,
    github_client: Github,
    chat_id: int,
    bot: Bot,
) -> None:
    if isinstance(query.message, Message):
        await query.answer()
        try:
            github_user = github_client.get_user(callback_data.username)
        except GithubException:
            await query.message.answer("Error: User not found.")
            return

        await add_starred_repos(chat_id, github_user, bot, session)
        await query.message.delete()


@router.callback_query(ReleaseFormatAction.filter(F.format == "menu"))
async def on_open_release_format_menu(
    query: CallbackQuery, session: AsyncSession, chat_id: int
) -> None:
    await query.answer()
    chat = await get_or_create_chat(session, chat_id)

    def mark(fmt: str | None) -> str:
        return "✅ " if chat.release_note_format == fmt else ""

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{mark('quote')}Quote",
                    callback_data=ReleaseFormatAction(format="quote").pack(),
                ),
                InlineKeyboardButton(
                    text=f"{mark('pre')}Pre",
                    callback_data=ReleaseFormatAction(format="pre").pack(),
                ),
                InlineKeyboardButton(
                    text=f"{mark(None)}Markdown",
                    callback_data=ReleaseFormatAction(format="markdown").pack(),
                ),
                InlineKeyboardButton(
                    text=f"{mark('html')}HTML",
                    callback_data=ReleaseFormatAction(format="html").pack(),
                ),
            ],
            [InlineKeyboardButton(text="Cancel", callback_data="cancel")],
        ]
    )
    if isinstance(query.message, Message):
        await query.message.edit_reply_markup(reply_markup=keyboard)


_FORMAT_VALUES: dict[str, str | None] = {
    "quote": "quote",
    "pre": "pre",
    "markdown": None,
    "html": "html",
}


@router.callback_query(
    ReleaseFormatAction.filter(F.format.in_({"quote", "pre", "markdown", "html"}))
)
async def release_format_btn(
    query: CallbackQuery,
    callback_data: ReleaseFormatAction,
    session: AsyncSession,
    chat_id: int,
) -> None:
    await query.answer()
    chat = await get_or_create_chat(session, chat_id)
    chat.release_note_format = _FORMAT_VALUES[callback_data.format]
    await session.flush()
    if isinstance(query.message, Message):
        await query.message.edit_text(text="Release note format changed.")


@router.callback_query(PageAction.filter())
async def change_page_btn(
    query: CallbackQuery, callback_data: PageAction, session: AsyncSession, chat_id: int
) -> None:
    await query.answer()
    keyboard = await get_repo_keyboard(chat_id, callback_data.page, session)
    if keyboard and isinstance(query.message, Message):
        await query.message.edit_reply_markup(reply_markup=keyboard)


@router.callback_query(RepoAction.filter(F.action == "pre"))
async def toggle_prerelease_btn(
    query: CallbackQuery,
    callback_data: RepoAction,
    session: AsyncSession,
    chat_id: int,
    bot: Bot,
) -> None:
    await query.answer()
    chat = await get_or_create_chat(session, chat_id)
    repo_obj = await session.get(Repo, callback_data.repo_id)
    if not repo_obj and isinstance(query.message, Message):
        await query.message.answer("Error: Repo not found.")
        return

    if isinstance(repo_obj, Repo):
        chat_repo = get_chat_repo(chat, repo_obj, session)
        chat_repo.process_pre_releases = not chat_repo.process_pre_releases
        await session.flush()

        if chat_repo.process_pre_releases:
            reply_message = (
                f"You are subscribed to repo <b>{repo_obj.full_name}</b> pre-releases."
            )
        else:
            reply_message = f"You are unsubscribed from repo <b>{repo_obj.full_name}</b> pre-releases."

        keyboard = await get_repo_keyboard(chat_id, callback_data.page, session)
        if isinstance(query.message, Message):
            await query.message.edit_reply_markup(reply_markup=keyboard)

        await bot.send_message(
            chat_id,
            reply_message,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(
                url=repo_obj.link, prefer_small_media=True
            ),
        )


@router.callback_query(RepoAction.filter(F.action == "delete"))
async def on_delete_repo(
    query: CallbackQuery,
    callback_data: RepoAction,
    session: AsyncSession,
    chat_id: int,
    bot: Bot,
) -> None:
    await query.answer()
    chat = await get_or_create_chat(session, chat_id)
    repo_obj = await session.get(Repo, callback_data.repo_id)

    if repo_obj:
        await session.execute(
            delete(ChatRepo).where(
                ChatRepo.chat_id == chat.id, ChatRepo.repo_id == repo_obj.id
            )
        )
        await session.flush()
        reply_message = f"Deleted repo: <b>{repo_obj.full_name}</b>"
        repo_url = repo_obj.link
    else:
        reply_message = "Error: Repo not found."
        repo_url = None

    keyboard = await get_repo_keyboard(chat_id, callback_data.page, session)
    if isinstance(query.message, Message):
        if keyboard:
            await query.message.edit_reply_markup(reply_markup=keyboard)
        elif callback_data.page > 0:
            keyboard = await get_repo_keyboard(chat_id, callback_data.page - 1, session)
            await query.message.edit_reply_markup(reply_markup=keyboard)
        else:
            await query.message.edit_text(text="You no longer have any repos.")

    await bot.send_message(
        chat_id,
        reply_message,
        parse_mode="HTML",
        link_preview_options=(
            LinkPreviewOptions(url=repo_url, prefer_small_media=True)
            if repo_url
            else None
        ),
    )


@router.message(Command("starred"))
async def starred_command(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    github_client: Github,
) -> None:
    chat = await get_or_create_chat(session, message.chat.id)

    if chat.github_username:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Unsubscribe from user",
                        callback_data=UserSubAction(
                            action="unsubscribe",
                        ).pack(),
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="Cancel",
                        callback_data="cancel",
                    ),
                ],
            ]
        )

        await message.answer(
            f"You are already subscribed to the user {chat.github_username}.\n"
            "Unsubscribe now?",
            reply_markup=keyboard,
        )
        return

    args = command.args.split() if command.args else []
    if len(args) != 1:
        await message.answer(
            "Specify a GitHub username in the following format: /starred username",
        )
        return

    username = args[0]

    try:
        github_user = github_client.get_user(username)
    except GithubException:
        await message.answer("Sorry, I can't find that user.")
        return

    starred = github_user.get_starred()

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Subscribe user",
                    callback_data=UserSubAction(
                        action="subscribe",
                        username=username,
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Add user's repos",
                    callback_data=UserSubAction(
                        action="add_repos",
                        username=username,
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Cancel",
                    callback_data="cancel",
                ),
            ],
        ]
    )

    await message.answer(
        f"User {username} has {starred.totalCount} starred repos. "
        "Subscribe to the user or add user's repos once?",
        reply_markup=keyboard,
    )


@router.message(Command("settings"))
async def settings_command(message: Message) -> None:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Release note format",
                    callback_data=ReleaseFormatAction(format="menu").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Cancel",
                    callback_data="cancel",
                )
            ],
        ]
    )

    await message.answer(
        "Settings",
        reply_markup=keyboard,
    )


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
    subscription_count = await session.scalar(select(func.count()).select_from(ChatRepo))

    text = (
        f"I have to update {release_count} releases for {repo_count} repos via {subscription_count} "
        f"subscriptions added by {user_count} users."
    )

    await message.answer(text)


@router.message(Command("test"))
async def test_command(
    message: Message,
    command: CommandObject,
    chat_id: int,
    session: AsyncSession,
    github_obj: Github,
    bot: Bot,
) -> None:
    """Send a message when the command /test is issued."""
    chat = await get_or_create_chat(session, chat_id)

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

    text, parse_mode, entities = format_release_message(
        chat.release_note_format, repo, release
    )

    await bot.send_message(
        chat_id,
        text,
        parse_mode=parse_mode,
        entities=entities,
        link_preview_options=LinkPreviewOptions(
            url=repo.html_url, prefer_small_media=True
        ),
    )


def _first_github_repo(urls: dict, keys: list[str]) -> str | None:
    for key in keys:
        url = urls.get(key)
        if url and (match := github_link_pattern.search(url)):
            return match.group(1)
    return None


def _pypi2github(project_name: str) -> tuple[int, str | None]:
    resp = urllib3.request("GET", f"https://pypi.org/pypi/{project_name}/json")
    if resp.status != 200:
        return resp.status, None

    info = json.loads(resp.data.decode("utf-8"))["info"]

    if info["project_urls"]:
        repo_name = _first_github_repo(
            info["project_urls"], ["Source", "Source Code", "Homepage"]
        )
    else:
        repo_name = _first_github_repo({"home_page": info["home_page"]}, ["home_page"])

    return resp.status, repo_name


def _npm2github(package_name: str) -> tuple[int, str | None]:
    package_name_quoted = urllib.parse.quote(package_name, safe="")
    resp = urllib3.request(
        "GET", f"https://api.npms.io/v2/package/{package_name_quoted}"
    )
    if resp.status != 200:
        return resp.status, None

    links = json.loads(resp.data.decode("utf-8"))["collected"]["metadata"]["links"]
    repo_name = _first_github_repo(links, ["repository", "homepage"])

    return resp.status, repo_name


async def _resolve_repo_name_from_link(
    message: Message, project: str, resolver
) -> str | None:
    status, repo_name = resolver(project)
    if status != 200:
        await message.answer("Error: Invalid repo.")
        return None
    if not repo_name:
        await message.answer(f"Project {project} has not link to GitHub repository.")
        return None
    return repo_name


@router.message(F.text)
async def message(
    message: Message, session: AsyncSession, bot: Bot, github_obj: Github, chat_id: int
) -> None:
    """Add GitHub repo"""
    text = cast(str, message.text)
    if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        bot_name = cast(str, (await bot.get_me()).username).lower()
        if not text.lower().startswith(f"@{bot_name}"):
            return

    if match := pypi_link_pattern.search(text):
        repo_name = await _resolve_repo_name_from_link(
            message, match.group(1), _pypi2github
        )
        if repo_name is None:
            return
    elif match := npm_link_pattern.search(text):
        repo_name = await _resolve_repo_name_from_link(
            message, match.group(1), _npm2github
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
    except GithubException as e:
        await message.answer("Sorry, I can't find that repo.")
        print(f"GithubException for {repo_name} in message: {e}")
        return

    await add_repo(chat_id, repo, bot, session, False)


async def _add_repos_from_packages(
    chat_id: int,
    package_names,
    resolver,
    bot: Bot,
    session: AsyncSession,
    github_client: Github,
) -> None:
    for name in package_names:
        status, repo_name = resolver(name)
        if status == 200 and repo_name:
            try:
                repo = github_client.get_repo(repo_name)
            except GithubException as e:
                print("Github Exception in download_file", e)
                continue

            await add_repo(chat_id, repo, bot, session, True)


@router.message(F.document)
async def download_file(
    message: Message, session: AsyncSession, bot: Bot, github_client: Github
) -> None:
    """Add GitHub repo from uploaded requirements.txt"""
    document = cast(Document, message.document)

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
            message.chat.id, package_names, _pypi2github, bot, session, github_client
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
            message.chat.id, package_names, _npm2github, bot, session, github_client
        )

    else:
        await message.answer("I don't know this file format.")


@router.message(F.text.startswith("/"))
async def unknown_command(message: Message, bot: Bot) -> None:
    if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        text = cast(str, message.text).lower()
        bot_name = str((await bot.get_me()).username).lower()
        if len(text) > 2 and "@" in text[1:] and f"@{bot_name}" not in text:
            return

    await message.answer(
        "Sorry, I don't understand. Please pick one of the valid options."
    )
    await start_command(message)
