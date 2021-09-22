from functools import wraps

from telegram import Update
from telegram.ext import CallbackContext

from bot.bot_logic.bot_logic import BotLogic
from bot.models import TelegramUser


def handlers_wrapper(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        bot_logic: BotLogic = args[0]
        update: Update = args[1]
        context: CallbackContext = args[2]
        telegram_user_id = update.effective_user.id
        telegram_user = TelegramUser.objects.filter(uid=telegram_user_id).get()
        bot_logic.telegram_user = telegram_user
        bot_logic.update = update
        bot_logic.context = context
        return function(*args, **kwargs)

    return wrapper
