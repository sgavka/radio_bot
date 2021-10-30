import os
import asyncio
from multiprocessing import Process
import pytgcalls
from asgiref.sync import sync_to_async
from django.core.management.base import BaseCommand
from pyrogram import Client
from pytgcalls.exceptions import GroupCallNotFoundError
from telegram import Bot
from bot.models import Radio, BroadcastUser, Queue, AudioFile
from bot.services.bot import get_bot_from_db


class QueueStorage(object):
    def __init__(self):
        self.clients = {}

        # init bot
        bot_from_db = get_bot_from_db()
        self.bot = Bot(bot_from_db.token)
        self._queue_to_download = {}
        self._queue_downloaded = {}
        self._last_queue = {}

    def init(self, broadcast_user_uid: int, broadcast_user_api_id: int,
             broadcast_user_api_hash: str) -> 'QueueClient':
        if broadcast_user_uid not in self.clients.keys():
            self.clients[broadcast_user_uid] = QueueClient(broadcast_user_uid, broadcast_user_api_id,
                                                           broadcast_user_api_hash, self)
        return self.clients[broadcast_user_uid]

    def get_bot(self) -> Bot:
        return self.bot

    async def init_download_file(self, radio: Radio):
        if radio.id not in self._queue_to_download.keys():
            self._queue_to_download[radio.id] = {}
        if len(self._queue_to_download[radio.id]) == 0:
            get_first_audio_file = sync_to_async(self._get_first_audio_file)
            audio_file = await get_first_audio_file(radio)
            if audio_file:
                self._queue_to_download[radio.id][audio_file.id] = audio_file
            else:
                pass  # don't set file to download, this mean radio will wait for new audio file in the queue
        for audio_file in self._queue_to_download[radio.id].values():
            await self._download_audio_file(audio_file, radio)
            del self._queue_to_download[radio.id][audio_file.id]
            break
        if len(self._queue_downloaded[radio.id]):
            for key, value in self._queue_downloaded[radio.id].items():
                del self._queue_downloaded[radio.id][key]
                return key, value  # get downloaded audio file
        return False

    def _get_first_audio_file(self, radio) -> AudioFile:
        queue_audio_file = Queue.objects.filter(radio=radio, status=Queue.STATUS_IN_QUEUE).order_by('sort').first()
        if queue_audio_file:
            # todo: get group id from DB
            self._last_queue[-582672833] = queue_audio_file
            return queue_audio_file.audio_file
        return None

    async def _download_audio_file(self, audio_file, radio):
        file = self.get_bot().get_file(audio_file.raw_telegram_file_id)
        file_name = file.file_id + '.raw'
        # create path for each radio with audio files
        file_directory = 'data/now-play-audio/' + radio.id + '/'
        if not os.path.exists(file_directory):
            os.mkdir(file_directory)
        file_path = file_directory + file_name
        file.download(file_path)
        if radio.id not in self._queue_downloaded.keys():
            self._queue_downloaded[radio.id] = {}
        self._queue_downloaded[radio.id][audio_file.id] = file_path


class QueueClient(object):
    def __init__(self, broadcast_user_uid: int, broadcast_user_api_id: int, broadcast_user_api_hash: str,
                 storage: QueueStorage):
        session_name, sessions_directory = self.init_session(broadcast_user_uid)
        self.client = Client(session_name,
                             api_id=broadcast_user_api_id,
                             api_hash=broadcast_user_api_hash,
                             workdir=sessions_directory
                             )
        self.group_calls = {}
        self.storage = storage

    def get(self):
        return self.client

    def init_group_call(self, chat_id: int) -> 'QueueGroupCall':
        if chat_id not in self.group_calls.keys():
            self.group_calls[chat_id] = QueueGroupCall(self.client, self.storage)
        return self.group_calls[chat_id]

    def init_session(self, broadcast_user_uid: int):
        # todo: move all strings to constants or config
        # init sessions directory
        sessions_directory = 'data/sessions'
        if not os.path.exists(sessions_directory):
            os.mkdir(sessions_directory)
        session_name = '%s_account' % (broadcast_user_uid,)
        return session_name, sessions_directory


class QueueGroupCall(object):
    def __init__(self, client: Client, storage):
        self.group_call = pytgcalls.GroupCallFactory(client).get_file_group_call()
        self.is_handler_playout_ended_set = False
        self.storage = storage
        self.is_started = False
        self._is_now_playing = False

    def get(self) -> pytgcalls.GroupCall:
        return self.group_call

    def add_handler_playout_ended(self, playout_ended):
        if not self.is_handler_playout_ended_set:
            self.group_call.on_playout_ended(playout_ended)
            self.is_handler_playout_ended_set = True

    async def start(self, chat_id: int):
        if not self.is_started:
            await self.group_call.start(chat_id)  # todo: get group id from DB
            while not self.group_call.is_connected:  # after that the group call starts
                await asyncio.sleep(0.001)
            self.is_started = True

    def is_now_playing(self):
        return self._is_now_playing

    def set_file(self, audio_file_path):
        self._is_now_playing = True
        self.group_call.input_filename = audio_file_path


class Command(BaseCommand):
    def handle(self, *args, **options):
        # todo: create QueueCollection prop
        self.storage = QueueStorage()

        while True:
            radios = Radio.objects.filter(status=Radio.STATUS_ASKING_FOR_BROADCAST)

            for radio in radios:
                radio.status = Radio.STATUS_STARTING_BROADCAST
                radio.save()
                process = Process(target=self.worker, args=(radio,))
                process.start()

    def worker(self, radio: Radio):
        broadcast_user = BroadcastUser.objects.get(id=radio.broadcast_user_id)

        import logging
        logging.basicConfig(level=logging.DEBUG)

        loop = asyncio.new_event_loop()
        loop.run_until_complete(self.broadcast_worker(radio, broadcast_user))
        loop.close()

    async def broadcast_worker(self, radio: Radio, broadcast_user: BroadcastUser):
        # todo: resolve db exceptions
        # todo: flood error handling
        try:
            # show debug messages in console
            import logging
            logging.basicConfig(level=logging.DEBUG)

            # init client
            queue_client = self.storage.init(broadcast_user.uid, broadcast_user.api_id, broadcast_user.api_hash)
            client = queue_client.get()

            # connect client
            is_authorized = await client.connect()
            # while not client.is_connected:
            #     await asyncio.sleep(0.001)
            if not is_authorized:
                pass  # todo: handle this exclusion -- set error status for the radio and for the account
                # todo: send error message throw bot

            # initialize client
            await client.initialize()
            while not client.is_connected:
                pass  # todo: handle this exclusion

            while True:
                try:
                    # todo: get chat id from db
                    chat_id = -582672833
                    queue_group_call = queue_client.init_group_call(chat_id)
                    queue_group_call.add_handler_playout_ended(self.playout_ended)

                    await queue_group_call.start(chat_id)

                    group_call = queue_group_call.get()

                    if not queue_group_call.is_now_playing():
                        file_tuple = await self.storage.init_download_file(radio)
                        if file_tuple is not False:
                            audio_file_id, audio_file_path = file_tuple
                            group_call.play_on_repeat = False
                            queue_group_call.set_file(audio_file_path)

                    # fix: make playout_ended handler work
                    await asyncio.sleep(0.001)

                    # todo: wait actions: pause, stop, play
                    # todo: break if radio status changed to STATUS_ASKING_FOR_STOP_BROADCAST

                    # todo: change status in telegram message
                    # todo: set radio status On Air
                except GroupCallNotFoundError as e:
                    pass  # todo: react on this exception
                except Exception as e:
                    pass  # todo: react on this exceptions
        except Exception as e:
            pass
        pass

    async def playout_ended(self, group_call, file_name):
        # mark prev queue as played
        queue_group_call = None
        queue_client: QueueClient
        for queue_client in self.storage.clients.values():
            queue_group_call: QueueGroupCall
            for group_id, queue_group_call in queue_client.group_calls.items():
                if group_id == group_call.chat_peer.chat_id * -1:
                    break
        if queue_group_call:
            last_queue: Queue = self.storage._last_queue[group_id]
            set_queue_played_status = sync_to_async(self._set_queue_played_status)
            await set_queue_played_status(last_queue)
            queue_group_call._is_now_playing = False
            # delete prev file from disk
            os.remove(file_name)
        else:
            pass  # todo: check error

    def _set_queue_played_status(self, queue):
        queue.status = Queue.STATUS_PLAYED
        queue.save()
