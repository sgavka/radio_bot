from telegram import Update
from telegram.ext import CallbackContext

from bot.models import TelegramUser


class BotContext:
    pass


class BotLogic:
    telegram_user: TelegramUser = None
    update: Update = None
    context: CallbackContext = None
    bot_context: BotContext = None
