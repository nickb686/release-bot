import re
from collections.abc import Awaitable, Callable

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)
from dishka.integrations.aiogram import FromDishka
from github import Github, GithubException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.database.models import Chat, ChatRepo, Repo
from app.services.subscriprion_service import (
    add_starred_repos,
    get_chat_repo,
    get_chat_repos_with_repo_by_chat_id,
    is_subscribed,
)
from app.telegram_bot.callbacks import (
    PageActionCallback,
    RepoActionCallback,
    RepoActionEnum,
    UserSubActionCallback,
    UserSubActionEnum,
)
from app.telegram_bot.keyboards import get_repo_keyboard
from config import Settings

router = Router()

direct_pattern = re.compile(".+/.+")


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


async def _handle_repo_command(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    bot: Bot,
    usage_hint: str,
    action: Callable[[int, int], Awaitable[str]],
    chat_id: int,
) -> None:
    repo_obj = await _resolve_repo_from_command(message, command, session, usage_hint)
    if repo_obj is None:
        return

    if not await is_subscribed(session, chat_id, repo_obj.id):
        await message.answer("Error: Repo not found.")
        return

    reply_message = await action(chat_id, repo_obj.id)
    await session.flush()
    await bot.send_message(
        chat_id,
        reply_message,
        parse_mode=ParseMode.HTML,
        link_preview_options=LinkPreviewOptions(
            url=repo_obj.link, prefer_small_media=True
        ),
    )


async def get_chat_repo_with_repo(
    session: AsyncSession, chat_id: int, repo_id: int
) -> ChatRepo:
    return (
        await session.execute(
            select(ChatRepo)
            .options(joinedload(ChatRepo.repo))
            .where(ChatRepo.chat_id == chat_id, ChatRepo.repo_id == repo_id)
        )
    ).scalar_one()


@router.message(Command("prerelease"))
async def prerelease_command(
    message: Message,
    command: CommandObject,
    session: FromDishka[AsyncSession],
    bot: Bot,
    chat: Chat,
) -> None:
    async def toggle_prerelease(chat_id: int, repo_id: int) -> str:
        chat_repo = await get_chat_repo_with_repo(session, chat_id, repo_id)
        chat_repo.process_pre_releases = not chat_repo.process_pre_releases
        state = (
            "subscribed to" if chat_repo.process_pre_releases else "unsubscribed from"
        )
        return f"You are {state} repo <b>{chat_repo.repo.full_name}</b> pre-releases."

    await _handle_repo_command(
        message,
        command,
        session,
        bot,
        "Specify a GitHub repo in the following format: /prerelease owner/repo",
        toggle_prerelease,
        chat.id,
    )


@router.message(Command("delete"))
async def delete_command(
    message: Message,
    command: CommandObject,
    session: FromDishka[AsyncSession],
    bot: Bot,
    chat: Chat,
) -> None:
    async def remove_repo(chat_id: int, repo_id: int) -> str:
        full_name = (
            await session.execute(select(Repo.full_name).where(Repo.id == repo_id))
        ).scalar_one()
        await session.execute(
            delete(ChatRepo).where(
                ChatRepo.chat_id == chat_id, ChatRepo.repo_id == repo_id
            )
        )
        return f"Deleted repo: <b>{full_name}</b>"

    await _handle_repo_command(
        message,
        command,
        session,
        bot,
        "Specify a GitHub repo in the following format: /delete owner/repo",
        remove_repo,
        chat.id,
    )


@router.callback_query(
    UserSubActionCallback.filter(F.action == UserSubActionEnum.subscribe)
)
async def subscribe_btn(
    query: CallbackQuery,
    callback_data: UserSubActionCallback,
    session: FromDishka[AsyncSession],
    github_client: FromDishka[Github],
    settings: FromDishka[Settings],
    bot: Bot,
    chat: Chat,
):
    if isinstance(query.message, Message):
        await query.answer()
        try:
            github_user = github_client.get_user(callback_data.username)
        except GithubException:
            await query.message.answer("Error: User not found.")
            return

        chat.github_username = github_user.login
        await session.flush()

        await query.message.edit_text(
            text=f"Subscribed to user {github_user.login} starred repos.",
        )
        await add_starred_repos(chat.id, github_user, bot, session, settings)


@router.callback_query(
    UserSubActionCallback.filter(F.action == UserSubActionEnum.add_repos)
)
async def add_repos_btn(
    query: CallbackQuery,
    callback_data: UserSubActionCallback,
    session: FromDishka[AsyncSession],
    github_client: FromDishka[Github],
    settings: FromDishka[Settings],
    chat: Chat,
    bot: Bot,
) -> None:
    if isinstance(query.message, Message):
        await query.answer()
        try:
            github_user = github_client.get_user(callback_data.username)
        except GithubException:
            await query.message.answer("Error: User not found.")
            return

        await add_starred_repos(chat.id, github_user, bot, session, settings)
        await query.message.delete()


@router.message(Command("list"))
async def list_command(message: Message, session: FromDishka[AsyncSession], chat: Chat):
    text = "Your subscriptions:\n"
    subscriptions = await get_chat_repos_with_repo_by_chat_id(session, chat.id)
    for i, chat_repo_obj in enumerate(subscriptions):
        repo_emoji = ""
        if chat_repo_obj.repo.archived:
            repo_emoji += " 📦"
        if chat_repo_obj.repo.blocked:
            repo_emoji += " 🚫"

        if chat_repo_obj.starred:
            repo_emoji += " ⭐"

        text += f"{i + 1}. <b><a href='{chat_repo_obj.repo.link}'>{chat_repo_obj.repo.full_name}</a></b>{repo_emoji}\n"

    await message.answer(
        text,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("edit_list"))
async def edit_list_command(
    message: Message, session: FromDishka[AsyncSession], chat: Chat
):
    keyboard = await get_repo_keyboard(chat.id, 0, session)
    if keyboard:
        await message.answer(
            "Here's all your added repos with their releases:",
            reply_markup=keyboard,
        )
    else:
        await message.answer("You don't have any repos yet.")


@router.callback_query(F.data == "cancel")
async def cancel_btn(query: CallbackQuery):
    await query.answer()
    if isinstance(query.message, Message):
        await query.message.delete()


@router.callback_query(
    UserSubActionCallback.filter(F.action == UserSubActionEnum.unsubscribe)
)
async def unsubscribe_btn(
    query: CallbackQuery,
    session: FromDishka[AsyncSession],
    chat: Chat,
) -> None:
    await query.answer()
    github_username = chat.github_username
    chat.github_username = None
    await session.flush()
    if github_username and isinstance(query.message, Message):
        await query.message.edit_text(text=f"Unsubscribed from user {github_username}.")


@router.callback_query(PageActionCallback.filter())
async def change_page_btn(
    query: CallbackQuery,
    callback_data: PageActionCallback,
    session: FromDishka[AsyncSession],
    chat: Chat,
) -> None:
    await query.answer()
    keyboard = await get_repo_keyboard(chat.id, callback_data.page, session)
    if keyboard and isinstance(query.message, Message):
        await query.message.edit_reply_markup(reply_markup=keyboard)


@router.callback_query(RepoActionCallback.filter(F.action == RepoActionEnum.pre))
async def toggle_prerelease_btn(
    query: CallbackQuery,
    callback_data: RepoActionCallback,
    session: FromDishka[AsyncSession],
    chat: Chat,
    bot: Bot,
) -> None:
    await query.answer()
    repo_obj = await session.get(Repo, callback_data.repo_id)
    if not repo_obj and isinstance(query.message, Message):
        await query.message.answer("Error: Repo not found.")
        return

    if isinstance(repo_obj, Repo):
        chat_repo = await get_chat_repo(chat.id, repo_obj.id, session)
        chat_repo.process_pre_releases = not chat_repo.process_pre_releases
        await session.flush()

        if chat_repo.process_pre_releases:
            reply_message = (
                f"You are subscribed to repo <b>{repo_obj.full_name}</b> pre-releases."
            )
        else:
            reply_message = (
                f"You are unsubscribed from repo "
                f"<b>{repo_obj.full_name}</b> pre-releases."
            )

        keyboard = await get_repo_keyboard(chat.id, callback_data.page, session)
        if isinstance(query.message, Message):
            await query.message.edit_reply_markup(reply_markup=keyboard)

        await bot.send_message(
            chat.id,
            reply_message,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(
                url=repo_obj.link,
                prefer_small_media=True,
            ),
        )


@router.callback_query(RepoActionCallback.filter(F.action == RepoActionEnum.delete))
async def on_delete_repo(
    query: CallbackQuery,
    callback_data: RepoActionCallback,
    session: FromDishka[AsyncSession],
    chat: Chat,
    bot: Bot,
) -> None:
    await query.answer()
    repo_obj = await session.get(Repo, callback_data.repo_id)

    if repo_obj:
        await session.execute(
            delete(ChatRepo).where(
                ChatRepo.chat_id == chat.id,
                ChatRepo.repo_id == repo_obj.id,
            ),
        )
        await session.flush()
        reply_message = f"Deleted repo: <b>{repo_obj.full_name}</b>"
        repo_url = repo_obj.link
    else:
        reply_message = "Error: Repo not found."
        repo_url = None

    keyboard = await get_repo_keyboard(chat.id, callback_data.page, session)
    if isinstance(query.message, Message):
        if keyboard:
            await query.message.edit_reply_markup(reply_markup=keyboard)
        elif callback_data.page > 0:
            keyboard = await get_repo_keyboard(chat.id, callback_data.page - 1, session)
            await query.message.edit_reply_markup(reply_markup=keyboard)
        else:
            await query.message.edit_text(text="You no longer have any repos.")

    await bot.send_message(
        chat.id,
        reply_message,
        parse_mode=ParseMode.HTML,
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
    github_client: FromDishka[Github],
    chat: Chat,
) -> None:
    if chat.github_username:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Unsubscribe from user",
                        callback_data=UserSubActionCallback(
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
            ],
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
                    callback_data=UserSubActionCallback(
                        action="subscribe",
                        username=username,
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Add user's repos",
                    callback_data=UserSubActionCallback(
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
        ],
    )

    await message.answer(
        f"User {username} has {starred.totalCount} starred repos. "
        "Subscribe to the user or add user's repos once?",
        reply_markup=keyboard,
    )
