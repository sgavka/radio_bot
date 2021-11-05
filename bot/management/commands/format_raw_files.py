# todo: for next iteration (then other users will use bot) need to create table with file_id for each broadcaster
import logging
import os
from shutil import copyfile
import ffmpeg
import pyrogram
from django.core.management import BaseCommand
from django.db import transaction
from pyrogram import Client
from telegram import Bot, Message
from telegram.error import NetworkError, BadRequest
from bot.models import Queue
from bot.services.bot import get_bot_from_db


class Command(BaseCommand):
    def handle(self, *args, **options):
        self.logger = logging.getLogger('format_raw_files')

        # todo: maybe use multiprocessing
        try:
            while True:
                queues = Queue.objects.filter(audio_file__raw_telegram_file_id=None).order_by('sort')

                for queue in queues:
                    self.prepare(queue)
        except BaseException as e:
            self.logger.critical(str(e), exc_info=True)
            raise e

    def prepare(self, queue: Queue):
        radio = queue.radio
        broadcast_user = radio.broadcast_user
        audio_file = queue.audio_file

        # create session dir & get session name
        sessions_directory = 'data/sessions'
        if not os.path.exists(sessions_directory):
            os.mkdir(sessions_directory)
        download_session_name = '%s_account_%s_radio_download' % (broadcast_user.uid, radio.id)
        session_name = '%s_account' % (broadcast_user.uid,)
        if not os.path.exists(sessions_directory + '/' + download_session_name + '.session'):
            main_session = sessions_directory + '/' + session_name + '.session'
            if os.path.exists(main_session):
                copyfile(
                    main_session,
                    sessions_directory + '/' + download_session_name + '.session'
                )
            else:
                raise Exception('Session `%s` does not exists!' % (main_session,))
                pass  # todo: need to handle this case
        client = Client(download_session_name,
                        api_id=broadcast_user.api_id,
                        api_hash=broadcast_user.api_hash,
                        workdir=sessions_directory
                        )
        is_authorized = client.connect()
        if not is_authorized:
            raise Exception('Client `%s` is not authorized!' % (broadcast_user.uid,))
            pass  # todo: handle this exclusion -- set error status for the radio and for the account
            # todo: send error message throw bot
        # initialize client
        client.initialize()
        if not client.is_connected:
            raise Exception('Can\'t connect client `%s`!' % (broadcast_user.uid,)) # todo: handle this exclusion

        bot_from_db = get_bot_from_db()
        telegram_bot = Bot(bot_from_db.token)

        try:
            if queue.type == Queue.AUDIO_FILE_TYPE:
                message = telegram_bot.send_document(radio.download_chat_id, audio_file.telegram_file_id)
            elif queue.type == Queue.VOICE_TYPE:
                message = telegram_bot.send_voice(radio.download_chat_id, audio_file.telegram_file_id)
            else:
                raise Exception('Unknown queue type `%s`!' % (queue.type,))  # todo: handle this exclusion
        except BadRequest as e:
            self.logger.critical(str(e), exc_info=True)
            raise Exception('Bad request while send audio/voice to chat. Queue ID: `%s`!' % (queue.id,))
            # todo: handle this (Chat not found) -- bot is not in this chat

        audio = None
        if type(message) is Message:
            message = client.get_messages(radio.download_chat_id, message.message_id)
            if message.audio:
                audio = message.audio
            elif message.voice:
                audio = message.voice
            else:
                raise Exception('Message has not audio/voice! Message ID: %s' % (message.message_id,))
                # todo: handle this exclusion

        # download audio file
        if audio is not None:
            file = client.download_media(audio.file_id)
        else:
            raise Exception('Message has not audio/voice (2)! Message ID: %s' % (message.message_id,)) # todo: handle this case

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
                message: pyrogram.types.messages_and_media.message.Message = client.send_document(
                    chat_id=radio.download_chat_id,
                    document=file,
                    file_name=audio_file.file_name,
                    caption=audio_file.title,
                    force_document=True
                    # timeout=10*60  # 10 minutes
                )
            except NetworkError as e:
                raise e
                # todo: timeout error
            if type(message) is pyrogram.types.messages_and_media.message.Message:
                upload_success = True
        if upload_success:
            message = client.get_messages(message.chat.id, message.message_id)
            audio_file.raw_telegram_file_id = message.document.file_id
            audio_file.raw_telegram_unique_id = message.document.file_unique_id
            with transaction.atomic():
                Queue.objects.filter(audio_file=audio_file).update(status=Queue.STATUS_IN_QUEUE)
                audio_file.save()
        else:
            raise Exception('Raw of audio file `%s` can\'t be send to Telegram!' % (audio_file.id,))
            pass  # todo: repeat or maybe set error status

        # close session
        client.terminate()
        client.disconnect()

        # delete raw file
        os.remove(file_path_raw)
