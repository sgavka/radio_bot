import logging
from django.core.management.base import BaseCommand
from bot.bot_logic.main import BotLogicMain


class Command(BaseCommand):
    def handle(self, *args, **options):
        self.logger = logging.getLogger('start_bot')

        try:
            bot_logic = BotLogicMain()
            bot_logic.init()
        except BaseException as e:
            self.logger.critical(str(e), exc_info=True)
            raise e
