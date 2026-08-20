import asyncio
from contextlib import suppress

from aiogram import Bot, Dispatcher, Router
from aiogram.types import BotCommand

from config import settings

from .routers import service_router, settings_router, subscription_router

router = Router()
router.include_routers(subscription_router, settings_router, service_router)
__all__ = ["router", "set_commands"]


async def set_commands(bot: Bot):
    commands = [
        BotCommand(command="list", description="show your subscriptions"),
        BotCommand(command="edit_list", description="show and edit your subscriptions"),
        BotCommand(
            command="prerelease", description="unsubscribe from repo pre-releases"
        ),
        BotCommand(command="delete", description="unsubscribe from repo releases"),
        BotCommand(command="starred", description="subscribe to user's starred repos"),
        BotCommand(command="settings", description="change output format"),
        BotCommand(command="about", description="information about this bot"),
        BotCommand(command="help", description="brief usage info"),
    ]
    await bot.set_my_commands(commands)


class BotRunner:
    def __init__(self, dp: Dispatcher, bot: Bot):
        self.dp, self.bot = dp, bot

    async def start(self): ...
    async def stop(self): ...


class PollingRunner(BotRunner):
    async def start(self):
        self.task = asyncio.create_task(self.dp.start_polling(self.bot))

    async def stop(self):
        self.task.cancel()
        with suppress(asyncio.CancelledError):
            await self.task


class WebhookRunner(BotRunner):
    async def start(self):
        await self.bot.set_webhook(
            settings.webhook_url, secret_token=settings.WEBHOOK_SECRET
        )

    async def stop(self):
        await self.bot.delete_webhook()
