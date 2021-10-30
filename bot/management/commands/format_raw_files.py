import os

import ffmpeg
import telegram
from django.core.management import BaseCommand
from django.db import transaction
from telegram import Bot, Message

from bot.models import AudioFile, Queue
from bot.services.bot import get_bot_from_db


class Command(BaseCommand):
    def handle(self, *args, **options):
        # todo: maybe use multiprocessing
        while True:
            audio_files = AudioFile.objects.filter(raw_telegram_file_id=None)

            for audio_file in audio_files:
                self.prepare(audio_file)

    def prepare(self, audio_file: AudioFile):
        # init bot
        bot_from_db = get_bot_from_db()
        telegram_bot = Bot(bot_from_db.token)

        # download audio file
        file = telegram_bot.get_file(audio_file.telegram_file_id)
        file_name = file.file_id + '.m4a'  # todo: check file format (maybe get from file.file_path)
        file_directory = 'data/tmp-audio/'
        if not os.path.exists(file_directory):
            os.mkdir(file_directory)
        file_path = file_directory + file_name
        file.download(file_path)

        # convert audio file to raw
        file_name_raw = file.file_id + '.raw'
        file_path_raw = file_directory + file_name_raw
        ffmpeg.input(file_path).output(
            file_path_raw, format='s16le', acodec='pcm_s16le', ac=2, ar='48k'
        ).overwrite_output().run()
        ffmpeg.input(
            file_path).output(
            file_path_raw,
            format='s16le',
            acodec='pcm_s16le', ac=2, ar='48k'
        ).overwrite_output().run()

        # delete original file
        os.remove(file_path)

        # send raw file to telegram
        upload_success = False
        with open(file_path_raw, 'rb') as file:
            message = telegram_bot.send_document(
                chat_id=-582672833,  # todo: need another chat for that purpose
                document=file,
                filename=audio_file.file_name,
                caption=audio_file.title
            )
            if type(message) is Message:
                upload_success = True
        if upload_success:
            audio_file.raw_telegram_file_id = message.document.file_id
            audio_file.raw_telegram_unique_id = message.document.file_unique_id
            with transaction.atomic():
                Queue.objects.filter(audio_file=audio_file).update(status=Queue.STATUS_IN_QUEUE)
                audio_file.save()
        else:
            pass  # todo: repeat or maybe set error status

        # delete raw file
        os.remove(file_path_raw)
