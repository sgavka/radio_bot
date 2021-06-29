from django.core.management.base import BaseCommand

from bot.bot_logic.main import BotLogicMain


class Command(BaseCommand):
    def handle(self, *args, **options):
        bot_logic = BotLogicMain()
        bot_logic.init()
