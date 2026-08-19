from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.subscriprion_service import (
    get_chat_repos_with_repo_by_chat_id,
    get_latest_chat_release,
)
from app.telegram_bot.callbacks import PageActionCallback, RepoActionCallback


async def get_repo_keyboard(
    chat_id: int,
    curr_page: int,
    session: AsyncSession,
) -> InlineKeyboardMarkup | None:
    btn_per_line = 4
    lines = (100 - 3) // btn_per_line
    chat_repos = (await get_chat_repos_with_repo_by_chat_id(session, chat_id)).all()
    if len(chat_repos) == 0:
        return None

    builder = InlineKeyboardBuilder()
    page_repos = chat_repos[curr_page * lines : (curr_page + 1) * lines]

    for chat_repo in page_repos:
        repo_name = chat_repo.repo.full_name.split("/")[1]
        latest_release = await get_latest_chat_release(
            session, chat_id, chat_repo.repo.id
        )
        if latest_release:
            repo_current_tag = latest_release.tag_name
            repo_current_tag_url = (
                latest_release.link
                or f"{chat_repo.repo.link}/releases/tag/{repo_current_tag}"
            )
        else:
            repo_current_tag = "N/A"
            repo_current_tag_url = f"{chat_repo.repo.link}/releases"
        process_pre_releases = "✔️" if chat_repo.process_pre_releases else "❌"
        builder.row(
            InlineKeyboardButton(text=repo_name, url=chat_repo.repo.link),
            InlineKeyboardButton(text=repo_current_tag, url=repo_current_tag_url),
            InlineKeyboardButton(
                text=f"Pre: {process_pre_releases}️️",
                callback_data=RepoActionCallback(
                    action="pre",
                    page=curr_page,
                    repo_id=chat_repo.repo.id,
                ).pack(),
            ),
            InlineKeyboardButton(
                text="🗑️",
                callback_data=RepoActionCallback(
                    action="delete",
                    page=curr_page,
                    repo_id=chat_repo.repo.id,
                ).pack(),
            ),
        )

    if not page_repos:
        return builder.as_markup()

    has_next = len(chat_repos) > (curr_page + 1) * lines
    has_prev = curr_page > 0

    nav_row = []
    if has_prev:
        nav_row.append(
            InlineKeyboardButton(
                text="⬅️ Prev",
                callback_data=PageActionCallback(
                    action="prev", page=curr_page - 1
                ).pack(),
            ),
        )
    nav_row.append(InlineKeyboardButton(text="Cancel", callback_data="cancel"))
    if has_next:
        nav_row.append(
            InlineKeyboardButton(
                text="Next ➡️",
                callback_data=PageActionCallback(
                    action="next", page=curr_page + 1
                ).pack(),
            ),
        )
    builder.row(*nav_row)
    return builder.as_markup()
