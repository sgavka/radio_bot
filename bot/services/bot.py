from bot.models import Bot


def get_bot_from_db() -> Bot:
    bot = Bot.objects.first()
    if not bot:
        raise Exception('Bot must be set in DB!')

    return bot
