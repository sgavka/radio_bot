# todo: for next iteration (then other users will use bot) need to create table with file_id for each broadcaster
import os
from shutil import copyfile
import ffmpeg
from django.core.management import BaseCommand
from django.db import transaction
from pyrogram import Client
from telegram import Bot, Message
from telegram.error import NetworkError

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
        # init userbot
        first_queue = audio_file.queue_set.first()
        radio = first_queue.radio
        broadcast_user = radio.broadcast_user

        # create session dir & get session name
        sessions_directory = 'data/sessions'
        if not os.path.exists(sessions_directory):
            os.mkdir(sessions_directory)
        download_session_name = '%s_account_%s_radio_download' % (broadcast_user.uid, radio.id)
        session_name = '%s_account' % (broadcast_user.uid,)
        if not os.path.exists(sessions_directory + '/' + download_session_name + '.session'):
            if os.path.exists(sessions_directory + '/' + session_name + '.session'):
                copyfile(
                    sessions_directory + '/' + session_name + '.session',
                    sessions_directory + '/' + download_session_name + '.session'
                )
            else:
                pass  # todo: need to handle this case
        client = Client(download_session_name,
                        api_id=broadcast_user.api_id,
                        api_hash=broadcast_user.api_hash,
                        workdir=sessions_directory
                        )
        is_authorized = client.connect()
        if not is_authorized:
            pass  # todo: handle this exclusion -- set error status for the radio and for the account
            # todo: send error message throw bot
        # initialize client
        client.initialize()
        if not client.is_connected:
            pass  # todo: handle this exclusion

        bot_from_db = get_bot_from_db()
        telegram_bot = Bot(bot_from_db.token)

        message = telegram_bot.send_document(radio.download_chat_id, audio_file.telegram_file_id)
        audio = None
        if type(message) is Message:
            messages = client.search_messages(radio.download_chat_id, from_user=message.from_user.id)
            for message in messages:
                if hasattr(message, 'audio') and message.audio.file_unique_id == audio_file.telegram_unique_id:
                    audio = message.audio
                    break

        # download audio file
        if audio:
            file = client.download_media(audio.file_id)
        else:
            pass  # todo: handle this case

        # convert audio file to raw
        file_name_raw = audio.file_id + '.raw'
        file_directory = 'data/tmp-audio/'
        if not os.path.exists(file_directory):
            os.mkdir(file_directory)
        file_path_raw = file_directory + file_name_raw
        ffmpeg.input(file) \
            .output(file_path_raw,
                    format='s16le',
                    acodec='pcm_s16le', ac=2, ar='48k'
                    )\
            .overwrite_output()\
            .run()

        # delete original file
        os.remove(file)

        # send raw file to telegram
        upload_success = False
        with open(file_path_raw, 'rb') as file:
            try:
                message: Message = telegram_bot.send_document(
                    chat_id=radio.download_chat_id,
                    document=file,
                    filename=audio_file.file_name,
                    caption=audio_file.title,
                    timeout=2*60  # 2 minutes
                )
            except NetworkError as e:
                pass  # todo: timeout error
            if type(message) is Message:
                upload_success = True
        if upload_success:
            message = client.get_messages(message.chat_id, message.message_id)
            audio_file.raw_telegram_file_id = message.document.file_id
            audio_file.raw_telegram_unique_id = message.document.file_unique_id
            with transaction.atomic():
                Queue.objects.filter(audio_file=audio_file).update(status=Queue.STATUS_IN_QUEUE)
                audio_file.save()
        else:
            pass  # todo: repeat or maybe set error status

        # delete raw file
        os.remove(file_path_raw)
