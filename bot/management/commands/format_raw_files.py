# todo: for next iteration (then other users will use bot) need to create table with file_id for each broadcaster
import logging
import os
from shutil import copyfile
from time import sleep
import ffmpeg
from django.core.management import BaseCommand
from django.db import transaction
from django.db.models import Count, Q
from pyrogram import Client
from telegram import Bot, Message
from telegram.error import BadRequest
from bot.models import Queue
from bot.services.bot import get_bot_from_db


class Command(BaseCommand):
    COUNT_OF_FILES_TO_DOWNLOAD_FOR_RADIO = 5

    def handle(self, *args, **options):
        self.logger = logging.getLogger('format_raw_files')

        # todo: maybe use multiprocessing
        try:
            while True:
                radios = Queue.objects \
                    .annotate(cnt=Count('radio_id')) \
                    .values('radio_id') \
                    .filter(
                    cnt__gte=self.COUNT_OF_FILES_TO_DOWNLOAD_FOR_RADIO,
                    status=Queue.STATUS_IN_QUEUE
                ).annotate(cnt=Count('radio_id')) \
                    .values('radio_id')
                queues = Queue.objects
                if radios:
                    queues = queues.filter(~Q(radio__in=radios))
                queue = queues.filter(status=Queue.STATUS_PROCESSING) \
                    .order_by('sort').first()

                if queue:
                    self.prepare(queue)
                else:
                    sleep(10)  # fix for CPU height usage
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
            os.makedirs(sessions_directory)
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
                message = telegram_bot.send_audio(radio.download_chat_id, audio_file.telegram_file_id)
            elif queue.type == Queue.VOICE_TYPE:
                message = telegram_bot.send_voice(radio.download_chat_id, audio_file.telegram_file_id)
            else:
                raise Exception('Unknown queue type `%s`! Queue ID: `%s`.' % (queue.type, queue.id))  # todo: handle this exclusion
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
                queue.status = Queue.STATUS_ERROR_CANT_DOWNLOAD
                audio_file.save()
                raise Exception('Message has not audio/voice! Message ID: `%s`. Queue ID: `%s`.' % (message.message_id, queue.id))
                # todo: handle this exclusion

        # download audio file
        if audio is not None:
            file = client.download_media(audio)
        else:
            queue.status = Queue.STATUS_ERROR_CANT_DOWNLOAD
            audio_file.save()
            raise Exception('Message has not audio/voice (2)! Message ID: `%s`. Queue ID: `%s`.' % (message.message_id, queue.id))  # todo: handle this case

        # convert audio file to raw
        file_name_raw = audio.file_id + '.raw'
        file_directory = 'data/now-play-audio/' + str(radio.id) + '/'
        if not os.path.exists(file_directory):
            os.makedirs(file_directory)
        file_path_raw = file_directory + file_name_raw
        ffmpeg.input(file) \
            .output(file_path_raw,
                    format='s16le',
                    acodec='pcm_s16le',
                    ac=2,
                    ar='48k',
                    **{
                        'b:a': '128k'
                    }) \
            .overwrite_output() \
            .run()

        # update audio file duration
        # todo: move it to bot then file is added (or to separate command)
        file_probe = ffmpeg.probe(file)
        if 'format' in file_probe and 'duration' in file_probe['format']:
            audio_file.duration_seconds = int(float(file_probe['format']['duration']))

        # set new file id
        audio_file.telegram_file_id = audio.file_id
        audio_file.telegram_unique_id = audio.file_unique_id
        with transaction.atomic():
            Queue.objects.filter(audio_file=audio_file).update(status=Queue.STATUS_IN_QUEUE)
            audio_file.save()

        # remove tmp file
        os.remove(file)

        # close session
        client.terminate()
        client.disconnect()
