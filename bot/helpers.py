import uuid
from functools import wraps

from django.contrib.auth.models import User
from django.db import transaction
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
        try:
            telegram_user = TelegramUser.objects.filter(uid=telegram_user_id).get()
        except TelegramUser.DoesNotExist:
            with transaction.atomic():
                user = create_user(update.effective_user.username)
                telegram_user = TelegramUser.objects.create(uid=update.effective_user.id, user=user)
        bot_logic.telegram_user = telegram_user
        bot_logic.update = update
        bot_logic.context = context
        return function(*args, **kwargs)

    return wrapper


def create_user(telegram_username: str):
    user = User()
    hash = uuid.uuid4().hex
    user.username = '%s_%s' % (telegram_username, hash[:10])
    user.save()

    return user
