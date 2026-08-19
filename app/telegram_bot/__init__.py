from aiogram import Bot, Router
from aiogram.types import BotCommand

from .routers.service import router as service_router
from .routers.settings import router as settings_router
from .routers.subscription import router as subscription_router

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
