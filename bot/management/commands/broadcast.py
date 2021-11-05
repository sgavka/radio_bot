# todo: error then audio chat is not available
# todo: after restart server put all radio in status STATUS_NOT_ON_AIR
# todo: fix audio lags (maybe because of wait/sleep or because of queries while broadcast)
import logging
import os
import asyncio
import re
from multiprocessing import Process
from shutil import copyfile
import pyrogram
import pytgcalls
from asgiref.sync import sync_to_async
from django.core.management.base import BaseCommand
from sqlite3 import OperationalError
from pyrogram import Client
from pyrogram.errors import FloodWait, ChannelInvalid
from pyrogram.raw.functions.channels import GetFullChannel
from pyrogram.raw.functions.phone import EditGroupCallTitle
from pyrogram.utils import get_channel_id
from pytgcalls.exceptions import GroupCallNotFoundError
from telegram import Bot, ParseMode
from django.utils.translation import ugettext as _
from bot.models import Radio, BroadcastUser, Queue, TelegramUser
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
        self.client = client
        self.group_call = pytgcalls.GroupCallFactory(client).get_file_group_call()
        self.is_handler_playout_ended_set = False
        self.storage = storage
        self._is_started = False
        self._is_now_playing = False
        self.queue = None
        self.radio = None

    def get(self) -> pytgcalls.GroupCall:
        return self.group_call

    def add_handler_playout_ended(self, playout_ended):
        if not self.is_handler_playout_ended_set:
            self.group_call.on_playout_ended(playout_ended)
            self.is_handler_playout_ended_set = True

    async def start(self, chat_id: int, radio: Radio):
        if not self._is_started:
            # await self.group_call.leave_current_group_call()
            await self.group_call.start(chat_id, join_as=chat_id)
            while not self.group_call.is_connected:  # after that the group call starts
                # todo: check pyrogram.errors.exceptions.bad_request_400.BadRequest: [400 Bad Request]: [400
                #  JOIN_AS_PEER_INVALID] (caused by "phone.JoinGroupCall")
                await asyncio.sleep(0.001)
            radio.status = Radio.STATUS_ON_AIR
            save_data_to_db = sync_to_async(Command.save_data_to_db)
            await save_data_to_db(radio)
            self._is_started = True
            self.radio = radio

    def is_now_playing(self):
        return self._is_now_playing

    def set_file(self, audio_file_path):
        self._is_now_playing = True
        self.group_call.input_filename = audio_file_path

    async def set_title(self, title: str):
        peer = await self.client.resolve_peer(self.radio.chat_id)
        chat = await self.client.send(GetFullChannel(channel=peer))
        data = EditGroupCallTitle(call=chat.full_chat.call, title=title)
        result = await self.client.send(data)
        if type(result) is pyrogram.raw.types.updates_t.Updates:
            return True
        else:
            return False  # todo: check errors

    def is_started(self):
        return self._is_started

    def set_queue(self, queue: Queue):
        self.queue = queue

    def get_queue(self):
        return self.queue


class Command(BaseCommand):
    REFRESH_DATA_ITERATIONS = 5

    def handle(self, *args, **options):
        self.storage = QueueStorage()
        self.logger = logging.getLogger('broadcast')
        bot_from_db = get_bot_from_db()
        self.bot = Bot(bot_from_db.token)

        try:

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
        except BroadcastUser as e:
            self.logger.critical(str(e), exc_info=True)
            raise e

    def worker(self, radio: Radio):
        try:
            broadcast_user = BroadcastUser.objects.get(id=radio.broadcast_user_id)
        except BroadcastUser.DoesNotExist:
            self.logger.error('Exception `BroadcastUser.DoesNotExist` was raised! Code try again.', exc_info=True)
            try:
                broadcast_user = BroadcastUser.objects.get(id=radio.broadcast_user_id)  # todo: sometime this not help
            except BroadcastUser.DoesNotExist as e:
                self.logger.error('Exception `BroadcastUser.DoesNotExist` was raised! Second try don\'t help.',
                                  exc_info=True)
                # try again (put radio to the queue again)
                radio.status = Radio.STATUS_ASKING_FOR_BROADCAST
                radio.save()
                return
        import logging
        logging.basicConfig(level=logging.DEBUG)

        loop = asyncio.new_event_loop()
        loop.run_until_complete(self.broadcast_worker(radio, broadcast_user))
        loop.close()

    def get_broadcast_user_by_id(self, radio):
        broadcast_user = BroadcastUser.objects.get(id=radio.broadcast_user_id)
        return broadcast_user

    async def broadcast_worker(self, radio: Radio, broadcast_user: BroadcastUser):
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
                raise Exception('Client `%s` is not authorized!' % (broadcast_user.uid,))
                pass  # todo: handle this exclusion -- set error status for the radio and for the account
                # todo: send error message throw bot

            # initialize client
            await client.initialize()
            while not client.is_connected:
                raise Exception('Can\'t connect client `%s`!' % (broadcast_user.uid,))  # todo: handle this exclusion

            refresh_data_iterator = 0
            start_message_is_sent = False
            while True:
                try:
                    if refresh_data_iterator == self.REFRESH_DATA_ITERATIONS:
                        refresh_data_from_db = sync_to_async(self.refresh_data_from_db)
                        radio = await refresh_data_from_db(radio)
                        refresh_data_iterator = 0
                    else:
                        refresh_data_iterator += 1

                    if radio.status == Radio.STATUS_ASKING_FOR_STOP_BROADCAST:
                        radio.status = Radio.STATUS_NOT_ON_AIR
                        save_data_to_db = sync_to_async(Command.save_data_to_db)
                        await save_data_to_db(radio)
                        break

                    queue_group_call = queue_client.init_group_call(radio.chat_id)
                    queue_group_call.add_handler_playout_ended(self.playout_ended)
                    group_call = queue_group_call.get()

                    if radio.status == Radio.STATUS_ASKING_FOR_PAUSE_BROADCAST:
                        radio.status = Radio.STATUS_ON_PAUSE
                        save_data_to_db = sync_to_async(Command.save_data_to_db)
                        await save_data_to_db(radio)
                        group_call.input_filename = None
                        queue_group_call.set_queue(None)  # to not update queue status in DB
                        queue_group_call._is_now_playing = False
                        await queue_group_call.set_title(_('On Pause!'))
                        continue

                    if radio.status == Radio.STATUS_ASKING_FOR_RESUME_BROADCAST:
                        radio.status = Radio.STATUS_ON_AIR
                        save_data_to_db = sync_to_async(Command.save_data_to_db)
                        await save_data_to_db(radio)
                        queue_group_call._is_now_playing = True
                        await queue_group_call.set_title(_('Resuming...'))
                        continue

                    try:
                        await queue_group_call.start(radio.chat_id, radio)
                        if not start_message_is_sent:
                            start_message_is_sent = True
                            await self.send_message(_('Radio is On Air!'), radio)
                            await queue_group_call.set_title(_('Starting...'))
                    except OperationalError as e:
                        self.logger.critical(str(e), exc_info=True)
                        raise e  # todo: that is this error?

                    if queue_group_call.is_started() and not queue_group_call.is_now_playing():
                        get_first_queue = sync_to_async(self.get_first_queue)
                        first_queue: Queue = await get_first_queue(radio)
                        if not first_queue:
                            await asyncio.sleep(5.0)  # wait some time to download the next audio file
                            continue

                        file_name = first_queue.audio_file.raw_telegram_file_id + '.raw'
                        file_path = 'data/now-play-audio/' + str(radio.id) + '/' + file_name

                        queue_group_call.set_queue(first_queue)

                        group_call.play_on_repeat = False
                        queue_group_call.set_file(file_path)
                        await queue_group_call.set_title(first_queue.audio_file.get_full_title())

                    # fix: make playout_ended handler work
                    await asyncio.sleep(0.001)
                except GroupCallNotFoundError:
                    radio.status = Radio.STATUS_ERROR_AUDIO_CHAT_IS_NOT_STARTED
                    save_data_to_db = sync_to_async(Command.save_data_to_db)
                    await save_data_to_db(radio)
                    await self.send_message(
                        _('Your audio chat is not started, please start it and request radio start again!'),
                        radio
                    )
                    break
                except FloodWait as e:
                    match = re.search(r'\ \d+\  ', str(e))
                    if match:
                        await asyncio.sleep(int(match.group(1)))
                    else:
                        self.logger.critical('Can\'t parse FloodWait exception to wait!', exc_info=True)
                        self.logger.critical(str(e), exc_info=True)
                        raise e
                except ChannelInvalid as e:
                    self.logger.critical(str(e), exc_info=True)  # log it on case if it is different error than handled
                    radio.status = Radio.STATUS_ERROR_BROADCASTER_IS_NOT_IN_BROADCAST_GROUP_OR_CHANNEL
                    save_data_to_db = sync_to_async(Command.save_data_to_db)
                    await save_data_to_db(radio)
                    await self.send_message(
                        _('Your broadcast account is not in broadcast group/channel!'
                          ' Add it there and start radio again.'),
                        radio
                    )
                    break
                except OperationalError as e:
                    self.logger.critical(str(e), exc_info=True)
                    radio.status = Radio.STATUS_ERROR_UNEXPECTED
                    save_data_to_db = sync_to_async(Command.save_data_to_db)
                    await save_data_to_db(radio)
                    await self.send_message(
                        _('There is unexpected error, please address to @sgavka!'),
                        radio
                    )
                    break
                except Exception as e:
                    self.logger.critical(str(e), exc_info=True)
                    radio.status = Radio.STATUS_ERROR_UNEXPECTED
                    save_data_to_db = sync_to_async(Command.save_data_to_db)
                    await save_data_to_db(radio)
                    await self.send_message(
                        _('There is unexpected error, please address to @sgavka!'),
                        radio
                    )
                    break
        except Exception as e:
            self.logger.critical(str(e), exc_info=True)
            radio.status = Radio.STATUS_ERROR_UNEXPECTED
            save_data_to_db = sync_to_async(Command.save_data_to_db)
            await save_data_to_db(radio)
            await self.send_message(
                _('There is unexpected error, please address to @sgavka!'),
                radio
            )
            pass

    def get_first_queue(self, radio):
        first_queue = Queue.objects.filter(radio=radio, status__in=[Queue.STATUS_IN_QUEUE_AND_DOWNLOADED]) \
            .order_by('sort').first()
        if first_queue:
            # get audio file object (need to do there to have access from queue object outside of this method
            audio_file = first_queue.audio_file
        return first_queue

    def refresh_data_from_db(self, model):
        model.refresh_from_db()
        return model

    @classmethod
    def save_data_to_db(cls, model):
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
                        if group_id == group_call.chat_peer.channel_id * -100:  # todo: check if this works
                            break
                    elif hasattr(group_call.chat_peer, 'channel_id'):
                        if group_id == get_channel_id(group_call.chat_peer.channel_id):
                            break
        if queue_group_call and type(group_id) is int:
            last_queue = queue_group_call.get_queue()
            if last_queue:
                set_queue_played_status = sync_to_async(self._set_queue_played_status)
                await set_queue_played_status(last_queue)
            queue_group_call.set_queue(None)
            queue_group_call._is_now_playing = False
            await queue_group_call.set_title(_('Next track...'))
            # delete prev file from disk
            os.remove(file_name)
        else:
            self.logger.error('Can\'t find group call to end playout!', exc_info=True)
            pass  # todo: check error

    def _set_queue_played_status(self, queue):
        queue.status = Queue.STATUS_PLAYED
        queue.save()

    def _get_telegram_user_by_radio(self, radio: Radio) -> TelegramUser:
        user_to_radio = radio.usertoradio_set.first()
        telegram_user = TelegramUser.objects.filter(user=user_to_radio.user).get()
        return telegram_user

    async def send_message(self, text, radio: Radio):
        _get_telegram_user_by_radio = sync_to_async(self._get_telegram_user_by_radio)
        telegram_user = await _get_telegram_user_by_radio(radio)
        self.bot.send_message(telegram_user.uid,
                              text,
                              parse_mode=ParseMode.MARKDOWN
                              )
