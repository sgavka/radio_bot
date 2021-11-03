# todo: error then audio chat is not available
import os
import asyncio
import re
from multiprocessing import Process
from shutil import copyfile
import pytgcalls
from asgiref.sync import sync_to_async
from django.core.management.base import BaseCommand
from sqlite3 import OperationalError
from pyrogram import Client
from pyrogram.errors import FloodWait, ChannelInvalid
from pyrogram.utils import get_channel_id
from pytgcalls.exceptions import GroupCallNotFoundError
from telegram import Bot
from bot.models import Radio, BroadcastUser, Queue
from bot.services.bot import get_bot_from_db


class QueueStorage(object):
    def __init__(self):
        self.clients = {}

    def init(self, broadcast_user_uid: int, broadcast_user_api_id: int,
             broadcast_user_api_hash: str, radio_id: int) -> 'QueueClient':
        if broadcast_user_uid not in self.clients.keys():
            self.clients[broadcast_user_uid] = {}

        if radio_id not in self.clients[broadcast_user_uid]:
            self.clients[broadcast_user_uid][radio_id] = QueueClient(broadcast_user_uid, broadcast_user_api_id,
                                                                     broadcast_user_api_hash, radio_id, self)
        return self.clients[broadcast_user_uid][radio_id]


class QueueClient(object):
    def __init__(self, broadcast_user_uid: int, broadcast_user_api_id: int, broadcast_user_api_hash: str,
                 radio_id: int, storage: QueueStorage):
        session_name, sessions_directory = self.init_session(broadcast_user_uid)
        radio_session_name, sessions_directory = self.init_radio_session(broadcast_user_uid, radio_id)
        # todo: extract generation of session names (& maybe create helper to work with seesions)
        if not os.path.exists(sessions_directory + '/' + radio_session_name + '.session'):
            if os.path.exists(sessions_directory + '/' + session_name + '.session'):
                copyfile(
                    sessions_directory + '/' + session_name + '.session',
                    sessions_directory + '/' + radio_session_name + '.session'
                )
            else:
                pass  # todo: need to handle this case
        self.client = Client(radio_session_name,
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

    def init_radio_session(self, broadcast_user_uid: int, radio_id: int):
        # todo: move all strings to constants or config
        # init sessions directory
        sessions_directory = 'data/sessions'
        if not os.path.exists(sessions_directory):
            os.mkdir(sessions_directory)
        session_name = '%s_account_%s_radio' % (broadcast_user_uid, radio_id)
        return session_name, sessions_directory


class QueueGroupCall(object):
    def __init__(self, client: Client, storage):
        self.group_call = pytgcalls.GroupCallFactory(client).get_file_group_call()
        self.is_handler_playout_ended_set = False
        self.storage = storage
        self._is_started = False
        self._is_now_playing = False
        self.queue = None

    def get(self) -> pytgcalls.GroupCall:
        return self.group_call

    def add_handler_playout_ended(self, playout_ended):
        if not self.is_handler_playout_ended_set:
            self.group_call.on_playout_ended(playout_ended)
            self.is_handler_playout_ended_set = True

    async def start(self, chat_id: int):
        if not self._is_started:
            # await self.group_call.leave_current_group_call()
            await self.group_call.start(chat_id)  # todo: get group id from DB
            while not self.group_call.is_connected:  # after that the group call starts
                await asyncio.sleep(0.001)
            self._is_started = True

    def is_now_playing(self):
        return self._is_now_playing

    def set_file(self, audio_file_path):
        self._is_now_playing = True
        self.group_call.input_filename = audio_file_path

    def is_started(self):
        return self._is_started

    def set_queue(self, queue: Queue):
        self.queue = queue

    def get_queue(self):
        return self.queue


class Command(BaseCommand):
    def handle(self, *args, **options):
        # todo: create QueueCollection prop
        self.storage = QueueStorage()

        while True:
            radios = Radio.objects.filter(status=Radio.STATUS_ASKING_FOR_BROADCAST)

            try:
                for radio in radios:
                    radio.status = Radio.STATUS_STARTING_BROADCAST
                    radio.save()
                    process = Process(target=self.worker, args=(radio,))
                    process.start()
            except RuntimeError as e:
                if 'StopIteration' in str(e):
                    pass
                else:
                    raise e
            except StopIteration:
                pass

    def worker(self, radio: Radio):
        try:
            broadcast_user = BroadcastUser.objects.get(id=radio.broadcast_user_id)
        except BroadcastUser.DoesNotExist:
            broadcast_user = BroadcastUser.objects.get(id=radio.broadcast_user_id)  # todo: sometime this not help

        import logging
        logging.basicConfig(level=logging.DEBUG)

        loop = asyncio.new_event_loop()
        loop.run_until_complete(self.broadcast_worker(radio, broadcast_user))
        loop.close()

    def get_broadcast_user_by_id(self, radio):
        broadcast_user = BroadcastUser.objects.get(id=radio.broadcast_user_id)
        return broadcast_user

    async def broadcast_worker(self, radio: Radio, broadcast_user: BroadcastUser):
        # todo: resolve db exceptions
        # todo: flood error handling
        try:
            # show debug messages in console
            import logging
            logging.basicConfig(level=logging.DEBUG)

            # init client
            queue_client = self.storage.init(broadcast_user.uid,
                                             broadcast_user.api_id,
                                             broadcast_user.api_hash,
                                             radio.id)
            client = queue_client.get()

            # connect client
            is_authorized = await client.connect()
            if not is_authorized:
                pass  # todo: handle this exclusion -- set error status for the radio and for the account
                # todo: send error message throw bot

            # initialize client
            await client.initialize()
            while not client.is_connected:
                pass  # todo: handle this exclusion

            refresh_data_iterator = 0
            while True:
                try:
                    if refresh_data_iterator == 5:  # todo: move to constant
                        refresh_data_from_db = sync_to_async(self.refresh_data_from_db)
                        radio = await refresh_data_from_db(radio)
                        refresh_data_iterator = 0
                    else:
                        refresh_data_iterator += 1

                    if radio.status == Radio.STATUS_ASKING_FOR_STOP_BROADCAST:
                        radio.status = Radio.STATUS_NOT_ON_AIR
                        save_data_to_db = sync_to_async(self.save_data_to_db)
                        await save_data_to_db(radio)
                        break

                    queue_group_call = queue_client.init_group_call(radio.chat_id)
                    queue_group_call.add_handler_playout_ended(self.playout_ended)

                    try:
                        await queue_group_call.start(radio.chat_id)
                    except OperationalError as e:
                        pass

                    group_call = queue_group_call.get()

                    if queue_group_call.is_started() and not queue_group_call.is_now_playing():
                        get_first_queue = sync_to_async(self.get_first_queue)
                        first_queue: Queue = await get_first_queue(radio)
                        if not first_queue and first_queue.status != Queue.STATUS_IN_QUEUE:
                            await asyncio.sleep(5.0)  # wait some time to download the next audio file
                            continue

                        file_name = first_queue.audio_file.raw_telegram_file_id + '.raw'
                        file_path = 'data/now-play-audio/' + str(radio.id) + '/' + file_name

                        queue_group_call.set_queue(first_queue)

                        group_call.play_on_repeat = False
                        queue_group_call.set_file(file_path)

                    # fix: make playout_ended handler work
                    await asyncio.sleep(0.001)

                    # todo: wait actions: pause, stop, play
                    # todo: change status in telegram message
                    # todo: set radio status On Air
                except GroupCallNotFoundError as e:
                    pass  # todo: react on this exception
                    # todo: create status for this
                    # todo: set wait maybe
                    # todo: save last chat_id & message_id there radio is shown & update this message
                except FloodWait as e:
                    match = re.search(r'\ \d+\  ', str(e))
                    # todo: maybe need to match async
                    if match:
                        await asyncio.sleep(int(match.group(1)))
                    else:
                        pass
                except ChannelInvalid as e:
                    pass  # todo: react on this exception (broadcaster is not in the channel/chat)
                except OperationalError as e:
                    pass
                except Exception as e:
                    pass  # todo: react on this exceptions
                    # todo: set wait maybe
        except Exception as e:
            pass
        pass

    def get_first_queue(self, radio):
        first_queue = Queue.objects.filter(radio=radio, status__in=[Queue.STATUS_IN_QUEUE,
                                                                    Queue.STATUS_IN_QUEUE_AND_DOWNLOADED]) \
            .order_by('sort').first()
        if first_queue:
            # get audio file object (need to do there to have access from queue object outside of this method
            audio_file = first_queue.audio_file
        return first_queue

    def refresh_data_from_db(self, model):
        model.refresh_from_db()
        return model

    def save_data_to_db(self, model):
        model.save()

    async def playout_ended(self, group_call, file_name):
        # mark prev queue as played
        queue_group_call = None
        group_id = None
        queue_client: QueueClient
        for client_radio in self.storage.clients.values():
            for queue_client in client_radio.values():
                queue_group_call: QueueGroupCall
                for group_id, queue_group_call in queue_client.group_calls.items():
                    if hasattr(group_call.chat_peer, 'chat_id'):
                        if group_id == group_call.chat_peer.chat_id * -1:  # todo: check if this works
                            break
                    elif hasattr(group_call.chat_peer, 'channel_id'):
                        if group_id == get_channel_id(group_call.chat_peer.channel_id):
                            break
        if queue_group_call and type(group_id) is int:
            last_queue = queue_group_call.get_queue()
            set_queue_played_status = sync_to_async(self._set_queue_played_status)
            await set_queue_played_status(last_queue)
            queue_group_call.set_queue(None)
            queue_group_call._is_now_playing = False
            # delete prev file from disk
            os.remove(file_name)
        else:
            pass  # todo: check error

    def _set_queue_played_status(self, queue):
        queue.status = Queue.STATUS_PLAYED
        queue.save()
