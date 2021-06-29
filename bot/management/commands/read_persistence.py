from django.core.management.base import BaseCommand
import pickle
from bot.models import *


class Command(BaseCommand):
    def handle(self, *args, **options):
        # read python dict back from the file
        file = open('data/bot_states.prs', 'rb')
        states_dict = pickle.load(file)
        file.close()

        print(states_dict)
