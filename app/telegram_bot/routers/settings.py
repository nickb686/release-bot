from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dishka.integrations.aiogram import FromDishka
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Chat
from app.telegram_bot.callbacks import ReleaseFormatActionCallback, SettingsMenuCallback

router = Router()


@router.callback_query(SettingsMenuCallback.filter(F.action == "menu"))
async def on_open_release_format_menu(query: CallbackQuery, chat: Chat) -> None:
    await query.answer()

    def mark(fmt: str | None) -> str:
        return "✅ " if chat.release_note_format == fmt else ""

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{mark('quote')}Quote",
                    callback_data=ReleaseFormatActionCallback(format="quote").pack(),
                ),
                InlineKeyboardButton(
                    text=f"{mark('pre')}Pre",
                    callback_data=ReleaseFormatActionCallback(format="pre").pack(),
                ),
                InlineKeyboardButton(
                    text=f"{mark(None)}Markdown",
                    callback_data=ReleaseFormatActionCallback(format="markdown").pack(),
                ),
                InlineKeyboardButton(
                    text=f"{mark('html')}HTML",
                    callback_data=ReleaseFormatActionCallback(format="html").pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Cancel",
                    callback_data=SettingsMenuCallback(action="cancel").pack(),
                )
            ],
        ],
    )
    if isinstance(query.message, Message):
        await query.message.edit_reply_markup(reply_markup=keyboard)


@router.callback_query(
    ReleaseFormatActionCallback.filter(F.format()),
)
async def release_format_btn(
    query: CallbackQuery,
    callback_data: ReleaseFormatActionCallback,
    session: FromDishka[AsyncSession],
    chat: Chat,
) -> None:
    await query.answer()
    chat.release_note_format = callback_data.format
    await session.flush()
    if isinstance(query.message, Message):
        await query.message.edit_text(text="Release note format changed.")


@router.message(Command("settings"))
async def settings_command(message: Message) -> None:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Release note format",
                    callback_data=SettingsMenuCallback(action="menu").pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Cancel",
                    callback_data=SettingsMenuCallback(action="cancel").pack(),
                ),
            ],
        ],
    )

    await message.answer(
        "Settings",
        reply_markup=keyboard,
    )


@router.callback_query(SettingsMenuCallback.filter(F.action == "cancel"))
async def cancel_btn(query: CallbackQuery):
    await query.answer()
    if isinstance(query.message, Message):
        await query.message.delete()
