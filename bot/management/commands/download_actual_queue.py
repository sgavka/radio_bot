import logging
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
        self.logger = logging.getLogger('download_actual_queue')
        # todo: maybe use multiprocessing
        try:
            while True:
                radios = Queue.objects\
                    .annotate(cnt=Count('radio_id'))\
                    .values('radio_id')\
                    .filter(
                        cnt__gte=self.COUNT_OF_FILES_TO_DOWNLOAD_FOR_RADIO,
                        status=Queue.STATUS_IN_QUEUE_AND_DOWNLOADED
                    ).annotate(cnt=Count('radio_id'))\
                    .values('radio_id')
                queues = Queue.objects
                if radios:
                    queues = queues.filter(~Q(radio__in=radios))
                queues = queues.filter(status=Queue.STATUS_IN_QUEUE) \
                    .filter(~Q(audio_file__raw_telegram_file_id=None))\
                    .order_by('sort')

                for queue in queues[:1]:
                    self.prepare(queue)
        except BaseException as e:
            self.logger.critical(str(e), exc_info=True)
            raise e

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
            main_session = sessions_directory + '/' + session_name + '.session'
            if os.path.exists(main_session):
                copyfile(
                    main_session,
                    download_session_file_path
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

        # download audio file
        try:
            file = client.download_media(queue.audio_file.raw_telegram_file_id)
        except Exception as e:
            self.logger.critical(str(e), exc_info=True)
            raise Exception('Failed to download audio file `%s`!' % (queue.audio_file.id,))

        if file:
            file_name = queue.audio_file.raw_telegram_file_id + '.raw'
            file_path = 'data/now-play-audio/' + str(radio.id) + '/' + file_name
            shutil.move(file, file_path)
        else:
            raise Exception('Failed (2) to download audio file `%s`! File: `%s`.' % (queue.audio_file.id, repr(file)))

        # save status
        queue.status = Queue.STATUS_IN_QUEUE_AND_DOWNLOADED
        queue.save()

        # close session
        client.terminate()
        client.disconnect()

        # delete session file
        os.remove(download_session_file_path)
