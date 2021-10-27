from functools import wraps

from telegram import Update
from telegram.ext import CallbackContext

from bot.models import TelegramUser


class BotContext:
    CONTEXT_NAME = None

    bot_logic: 'BotLogic'
    chat_data: dict

    def __init__(self, bot_logic: 'BotLogic'):
        self.bot_logic = bot_logic
        self.chat_data = bot_logic.context.chat_data
        self.context = None
        self.init_context()

    def init_context(self):
        if self.CONTEXT_NAME not in self.chat_data:
            self.chat_data[self.CONTEXT_NAME] = {}
        self.context = self.chat_data[self.CONTEXT_NAME]

    @classmethod
    def wrapper(cls, function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            bot_logic: BotLogic = args[0]
            bot_logic.bot_context = cls(bot_logic)
            return function(*args, **kwargs)

        return wrapper


class BotLogic:
    telegram_user: TelegramUser = None
    update: Update = None
    context: CallbackContext = None
    bot_context: BotContext = None
