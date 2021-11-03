import os
import shutil
from shutil import copyfile
from django.core.management import BaseCommand
from django.db.models import Q, Count
from pyrogram import Client
from bot.models import Queue


class Command(BaseCommand):
    COUNT_OF_FILES_TO_DOWNLOAD_FOR_RADIO = 5

    def handle(self, *args, **options):
        # todo: maybe use multiprocessing
        while True:
            radios = Queue.objects.annotate(cnt=Count('radio_id')).filter(
                cnt__gt=self.COUNT_OF_FILES_TO_DOWNLOAD_FOR_RADIO,
                status=Queue.STATUS_IN_QUEUE_AND_DOWNLOADED
            ).values('radio_id')
            queues = Queue.objects.filter(~Q(radio__in=radios)) \
                .filter(status=Queue.STATUS_IN_QUEUE) \
                .filter(~Q(audio_file__raw_telegram_file_id=None))

            for queue in queues:
                self.prepare(queue)

    def prepare(self, queue: Queue):
        # init userbot
        radio = queue.radio
        broadcast_user = radio.broadcast_user

        # create session dir & get session name
        sessions_directory = 'data/sessions'
        if not os.path.exists(sessions_directory):
            os.mkdir(sessions_directory)
        download_session_name = '%s_account_%s_radio_raw_%s_download' % (
        broadcast_user.uid, radio.id, queue.audio_file.id)
        session_name = '%s_account' % (broadcast_user.uid,)
        download_session_file_path = sessions_directory + '/' + download_session_name + '.session'
        if not os.path.exists(download_session_file_path):
            if os.path.exists(sessions_directory + '/' + session_name + '.session'):
                copyfile(
                    sessions_directory + '/' + session_name + '.session',
                    download_session_file_path
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

        # download audio file
        file = client.download_media(queue.audio_file.raw_telegram_file_id)
        if file:
            file_name = queue.audio_file.raw_telegram_file_id + '.raw'
            file_path = 'data/now-play-audio/' + str(radio.id) + '/' + file_name
            shutil.move(file, file_path)

        # seve status
        queue.status = Queue.STATUS_IN_QUEUE_AND_DOWNLOADED
        queue.save()

        # delete session file
        os.remove(download_session_file_path)
