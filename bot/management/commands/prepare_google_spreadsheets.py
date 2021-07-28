from django.core.management.base import BaseCommand

from bot.helpers import GoogleHelper


class Command(BaseCommand):
    def handle(self, *args, **options):
        service = GoogleHelper.init_sheets_service()
        pass
