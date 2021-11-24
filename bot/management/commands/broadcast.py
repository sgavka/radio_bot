# todo: broadcaster can broadcast as channel only if it owns the channel
# todo: catch error pyrogram.errors.exceptions.bad_request_400.BadRequest: [400 Bad Request]: [400 JOIN_AS_PEER_INVALID] (caused by "phone.JoinGroupCall")
# todo: error -- sqlite3.OperationalError: database is locked
# todo: cant stop then broadcast is on pause
# todo: check audio quality
import logging
import multiprocessing
import os
import asyncio
from logging.handlers import QueueHandler
from multiprocessing import Process
from shutil import copyfile
from time import sleep, time
import pyrogram
import pytgcalls
from asgiref.sync import sync_to_async
from django.core.management.base import BaseCommand
from sqlite3 import OperationalError
from pyrogram import Client
from pyrogram.errors import FloodWait, ChannelInvalid
from pyrogram.raw.functions.channels import GetFullChannel
from pyrogram.raw.functions.phone import EditGroupCallTitle, GetGroupParticipants
from pyrogram.raw.types import InputPeerChat, InputPeerChannel, InputGroupCall
from pyrogram.raw.types.phone import GroupParticipants
from pyrogram.utils import get_channel_id
from pytgcalls.exceptions import GroupCallNotFoundError
from pytgcalls.implementation import GroupCallFile
from telegram import Bot, ParseMode
from django.utils.translation import ugettext as _
from telegram.error import NetworkError
from bot.models import Radio, BroadcastUser, Queue, TelegramUser
from bot.services.bot import get_bot_from_db


class QueueStorage(object):
    def __init__(self):
        self.radios = {}

    def is_radio_on_queue(self, radio_id: int):
        return radio_id in self.radios.keys()

    def init(self, broadcast_user_uid: int, broadcast_user_api_id: int,
             broadcast_user_api_hash: str, radio_id: int) -> 'QueueRadio':
        if radio_id not in self.radios.keys():
            self.radios[radio_id] = QueueRadio(broadcast_user_uid, broadcast_user_api_id,
                                                                   broadcast_user_api_hash, radio_id, self)
        return self.radios[radio_id]


class QueueRadio(object):
    def __init__(self, broadcast_user_uid: int, broadcast_user_api_id: int, broadcast_user_api_hash: str,
                 radio_id: int, storage: QueueStorage):
        session_name, sessions_directory = self.init_session(broadcast_user_uid)
        radio_session_name, sessions_directory = self.init_radio_session(broadcast_user_uid, radio_id)
        # todo: extract generation of session names (& maybe create helper to work with seesions)
        if not os.path.exists(sessions_directory + '/' + radio_session_name + '.session'):
            main_session = sessions_directory + '/' + session_name + '.session'
            if os.path.exists(main_session):
                copyfile(
                    main_session,
                    sessions_directory + '/' + radio_session_name + '.session'
                )
            else:
                raise Exception('Session\'s file `%s` not exists!' % (main_session,))
        self.client = Client(radio_session_name,
                             api_id=broadcast_user_api_id,
                             api_hash=broadcast_user_api_hash,
                             workdir=sessions_directory
                             )
        self.group_call: QueueGroupCall = None
        self.storage = storage

    def get(self):
        return self.client

    def init_group_call(self, chat_id: int) -> 'QueueGroupCall':
        if self.group_call is None:
            self.group_call = QueueGroupCall(self.client, self.storage, chat_id)
        return self.group_call

    def init_session(self, broadcast_user_uid: int):
        # todo: move all strings to constants or config
        # init sessions directory
        sessions_directory = 'data/sessions'
        if not os.path.exists(sessions_directory):
            os.makedirs(sessions_directory)
        session_name = '%s_account' % (broadcast_user_uid,)
        return session_name, sessions_directory

    def init_radio_session(self, broadcast_user_uid: int, radio_id: int):
        # init sessions directory
        sessions_directory = 'data/sessions'
        if not os.path.exists(sessions_directory):
            os.makedirs(sessions_directory)
        session_name = '%s_account_%s_radio' % (broadcast_user_uid, radio_id)
        return session_name, sessions_directory


class QueueGroupCall(object):
    def __init__(self, client: Client, storage, chat_id):
        self.chat_id = chat_id
        self.client = client
        self.group_call: GroupCallFile = pytgcalls.GroupCallFactory(
            client
        ).get_file_group_call()
        self.is_handler_playout_ended_set = False
        self.is_handler_participant_list_updated_set = False
        self.storage = storage
        self._is_started = False
        self._is_now_playing = False
        self._asking_pause = False
        self._asking_resume = False
        self._is_on_zero_participants_pause = False
        self.queue = None
        self.radio = None
        self.participants_count = None

    def is_asking_pause(self):
        return self._asking_pause

    def is_asking_resume(self):
        return self._asking_resume

    def asking_pause(self):
        self._asking_pause = True
        self._is_on_zero_participants_pause = True

    def is_on_zero_participants_pause(self):
        return self._is_on_zero_participants_pause

    def unasking_pause(self):
        self._asking_pause = False

    def asking_resume(self):
        self._asking_resume = True

    def unasking_resume(self):
        self._asking_resume = False

    def get(self):
        return self.group_call

    def add_handler_playout_ended(self, playout_ended):
        if not self.is_handler_playout_ended_set:
            self.group_call.on_playout_ended(playout_ended)
            self.is_handler_playout_ended_set = True

    def add_handler_participant_list_updated(self, handler):
        if not self.is_handler_participant_list_updated_set:
            self.group_call.on_participant_list_updated(handler)
            self.is_handler_participant_list_updated_set = True

    async def start(self, chat_id: int, radio: Radio):
        if not self._is_started:
            # await self.group_call.leave_current_group_call()
            await self.group_call.start(chat_id, join_as=chat_id)
            while not self.group_call.is_connected:  # after that the group call starts
                # todo: check pyrogram.errors.exceptions.bad_request_400.BadRequest: [400 Bad Request]: [400
                #  JOIN_AS_PEER_INVALID] (caused by "phone.JoinGroupCall")
                await asyncio.sleep(0.1)  # fix for CPU height usage
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

    async def set_title(self, title: str, additional_channel_id: int = None):
        if self.radio or additional_channel_id is not None:
            if additional_channel_id is None:
                peer = await self.client.resolve_peer(self.radio.chat_id)
            else:
                peer = await self.client.resolve_peer(additional_channel_id)
            chat = await self.client.send(GetFullChannel(channel=peer))
            data = EditGroupCallTitle(call=chat.full_chat.call, title=title)
            if type(chat) is pyrogram.raw.types.messages.chat_full.ChatFull \
                    and type(chat.full_chat.call) is pyrogram.raw.types.input_group_call.InputGroupCall:
                result = await self.client.send(data)
                if type(result) is pyrogram.raw.types.updates_t.Updates:
                    return True
                else:
                    return False  # todo: check errors (write to logs) (raise exception)
            else:
                return False  # todo: check errors (write to logs) (raise exception)
        else:
            return False  # todo: check errors (write to logs) (raise exception)

    def is_started(self):
        return self._is_started

    def set_queue(self, queue: Queue):
        self.queue = queue

    def get_queue(self):
        return self.queue


class Command(BaseCommand):
    REFRESH_DATA_ITERATIONS = 5
    UPDATE_PARTICIPANTS_LIST_EVERY_SECONDS = 5

    def log_processor(self, queue):
        self.logger = logging.getLogger('broadcast')

        while True:
            try:
                record = queue.get()
                if record is None:
                    break
                self.logger.log(record.levelno, record.msg)
            except Exception as e:
                pass
        sleep(0.1)  # fix for CPU height usage

    def handle(self, *args, **options):
        self.storage = QueueStorage()

        queue = multiprocessing.Queue(-1)
        listener = multiprocessing.Process(target=self.log_processor, args=(queue,))
        listener.start()

        bot_from_db = get_bot_from_db()
        self.bot = Bot(bot_from_db.token)

        # before start — all abandoned started radio need to put in error status
        Radio.objects.filter(
            status__in=[
                Radio.STATUS_ON_AIR,
                Radio.STATUS_ON_PAUSE,
                Radio.STATUS_ASKING_FOR_STOP_BROADCAST,
                Radio.STATUS_STARTING_BROADCAST,
                Radio.STATUS_ASKING_FOR_PAUSE_BROADCAST,
            ]
        )\
            .update(status=Radio.STATUS_ERROR_UNEXPECTED)

        # before start — all abandoned queue need to put back to queue
        Queue.objects.filter(
            status=Queue.STATUS_PLAYING
        ).update(status=Queue.STATUS_IN_QUEUE)

        try:
            while True:
                radios = Radio.objects.filter(status=Radio.STATUS_ASKING_FOR_BROADCAST)

                try:
                    for radio in radios:
                        # todo: shared_storage.is_radio_on_queue(radio.id)
                        radio.status = Radio.STATUS_STARTING_BROADCAST
                        radio.save()
                        process = Process(target=self.worker, args=(radio, queue))
                        process.start()
                except RuntimeError as e:
                    if 'StopIteration' in str(e):
                        pass
                    else:
                        raise e
                except StopIteration:
                    pass
                sleep(10)  # fix for CPU height usage
        except asyncio.exceptions.TimeoutError as e:
            logger = logging.getLogger('broadcast')
            logger.critical('asyncio timout error')
            logger.critical(str(e), exc_info=True)
            raise e
        except BaseException as e:
            logger = logging.getLogger('broadcast')
            logger.critical(str(e), exc_info=True)
            raise e

    def worker(self, radio: Radio, queue):
        self.logger = logging.getLogger(__name__)
        self.logger.addHandler(QueueHandler(queue))

        loop = asyncio.new_event_loop()
        loop.run_until_complete(self.broadcast_worker(radio))
        loop.close()

    def get_broadcast_user_by_id(self, radio):
        broadcast_user = BroadcastUser.objects.get(id=radio.broadcast_user_id)
        return broadcast_user

    def get_broadcast_user(self, radio) -> BroadcastUser:
        broadcast_user = BroadcastUser.objects.get(id=radio.broadcast_user_id)
        return broadcast_user

    async def broadcast_worker(self, radio: Radio,):
        try:
            get_broadcast_user = sync_to_async(self.get_broadcast_user)
            broadcast_user = await get_broadcast_user(radio)

            # init client
            queue_client = self.storage.init(broadcast_user.uid,
                                             broadcast_user.api_id,
                                             broadcast_user.api_hash,
                                             radio.id)
            client = queue_client.get()

            # connect client
            is_authorized = await client.connect()
            if not is_authorized:
                radio.status = Radio.STATUS_ERROR_IS_NOT_AUTHORIZED
                save_data_to_db = sync_to_async(Command.save_data_to_db)
                await save_data_to_db(radio)
                await self.send_message(
                    _('Your broadcast account is not in authorized!'),
                    radio
                )
                raise Exception('Client `%s` is not authorized!' % (broadcast_user.uid,))

            # initialize client
            await client.initialize()
            while not client.is_connected:
                radio.status = Radio.STATUS_ERROR_CANT_CONNECT
                save_data_to_db = sync_to_async(Command.save_data_to_db)
                await save_data_to_db(radio)
                await self.send_message(
                    _('Your broadcast account can\'t connect!'),
                    radio
                )
                raise Exception('Can\'t connect client `%s`!' % (broadcast_user.uid,))  # todo: handle this exclusion

            refresh_data_iterator = 0
            start_message_is_sent = False
            actual_queue: Queue = None
            participant_list_updated = time()
            while True:
                try:
                    if refresh_data_iterator == self.REFRESH_DATA_ITERATIONS:
                        refresh_data_from_db = sync_to_async(self.refresh_data_from_db)
                        radio = await refresh_data_from_db(radio)
                        refresh_data_iterator = 0
                    else:
                        refresh_data_iterator += 1

                    queue_group_call = queue_client.init_group_call(radio.chat_id)
                    queue_group_call.add_handler_playout_ended(self.playout_ended)
                    group_call = queue_group_call.get()

                    # queue_group_call.add_handler_participant_list_updated(self.participant_list_updated)
                    if time() - participant_list_updated > self.UPDATE_PARTICIPANTS_LIST_EVERY_SECONDS:
                        await self.participant_list_updated(group_call, queue_group_call, None)
                        participant_list_updated = time()

                    if radio.status >= Radio.STATUS_ERROR_AUDIO_CHAT_IS_NOT_STARTED:
                        del self.storage.radios[radio.id]
                        break

                    if radio.status == Radio.STATUS_ASKING_FOR_STOP_BROADCAST:
                        # set radio status
                        radio.status = Radio.STATUS_NOT_ON_AIR
                        save_data_to_db = sync_to_async(Command.save_data_to_db)
                        await save_data_to_db(radio)

                        # is broadcast is stopped set current queue file again to queue
                        actual_queue.status = Queue.STATUS_IN_QUEUE
                        save_data_to_db = sync_to_async(Command.save_data_to_db)
                        await save_data_to_db(actual_queue)

                        await queue_group_call.set_title(_('Stopped!'))
                        del self.storage.radios[radio.id]
                        break

                    if radio.status == Radio.STATUS_ASKING_FOR_PAUSE_BROADCAST \
                            or queue_group_call.is_asking_pause():
                        radio.status = Radio.STATUS_ON_PAUSE
                        save_data_to_db = sync_to_async(Command.save_data_to_db)
                        await save_data_to_db(radio)
                        group_call.pause_playout()
                        queue_group_call._is_now_playing = False
                        queue_group_call.unasking_pause()
                        await queue_group_call.set_title(_('On Pause!'))
                        continue

                    if radio.status == Radio.STATUS_ASKING_FOR_RESUME_BROADCAST \
                            or queue_group_call.is_asking_resume():
                        radio.status = Radio.STATUS_ON_AIR
                        save_data_to_db = sync_to_async(Command.save_data_to_db)
                        await save_data_to_db(radio)
                        await queue_group_call.set_title(_('Resuming...'))
                        group_call.resume_playout()
                        queue_group_call._is_now_playing = True
                        queue_group_call._is_on_zero_participants_pause = False
                        queue_group_call.unasking_resume()
                        if type(actual_queue) is Queue:
                            await queue_group_call.set_title(actual_queue.audio_file.get_full_title())
                            continue

                    try:
                        await queue_group_call.start(radio.chat_id, radio)
                        if not start_message_is_sent:
                            start_message_is_sent = True
                            await queue_group_call.set_title(_('Starting...'))
                            await self.send_message(_('Radio is On Air!'), radio)
                    except pyrogram.errors.exceptions.bad_request_400.BadRequest as e:
                        if 'JOIN_AS_PEER_INVALID' in str(e):
                            radio.status = Radio.STATUS_ERROR_JOIN_AS_PEER_INVALID
                            save_data_to_db = sync_to_async(Command.save_data_to_db)
                            await save_data_to_db(radio)
                            await self.send_message(
                                _('Error: JOIN_AS_PEER_INVALID!'),
                                radio
                            )
                            del self.storage.radios[radio.id]
                            break
                        else:
                            raise e
                    except OperationalError as e:
                        self.logger.critical(str(e), exc_info=True)
                        raise e  # todo: that is this error?

                    if queue_group_call.is_started() and not queue_group_call.is_now_playing() \
                        and radio.status != Radio.STATUS_ON_PAUSE:
                        get_first_queue = sync_to_async(self.get_first_queue)
                        first_queue: Queue = await get_first_queue(radio)
                        actual_queue = first_queue

                        # if there no audio file in queue or the next file is in queue to download
                        if not first_queue:
                            await queue_group_call.set_title(_('Queue is empty...'))
                            await asyncio.sleep(5.0)  # wait some time to download the next audio file
                            queue_group_call._is_now_playing = False

                            continue

                        # disable play on repeat same file
                        group_call.play_on_repeat = False

                        # set file to play
                        file_name = first_queue.audio_file.telegram_file_id + '.raw'
                        file_path = 'data/now-play-audio/' + str(radio.id) + '/' + file_name
                        queue_group_call.set_queue(first_queue)
                        queue_group_call.set_file(file_path)

                        # set queue file status
                        first_queue.status = Queue.STATUS_PLAYING
                        save_data_to_db = sync_to_async(Command.save_data_to_db)
                        await save_data_to_db(first_queue)

                        # inform then queue is near to end
                        get_queue_count = sync_to_async(self.get_queue_count)
                        count = await get_queue_count(radio)
                        if count <= 5:
                            await self.send_message(
                                _('In your queue is only %s tracks.') % (count,),
                                radio
                            )

                        # set voice chat title
                        await queue_group_call.set_title(first_queue.audio_file.get_full_title())

                    # fix: make playout_ended handler work
                    await asyncio.sleep(1)
                    sleep(1)  # fix for CPU height usage & audio
                except GroupCallNotFoundError:
                    radio.status = Radio.STATUS_ERROR_AUDIO_CHAT_IS_NOT_STARTED
                    save_data_to_db = sync_to_async(Command.save_data_to_db)
                    await save_data_to_db(radio)
                    await self.send_message(
                        _('Your audio chat is not started, please start it and request radio start again!'),
                        radio
                    )
                    del self.storage.radios[radio.id]
                    break
                except FloodWait as e:
                    await asyncio.sleep(int(e.x))
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
                    del self.storage.radios[radio.id]
                    break
                except OperationalError as e:
                    self.logger.critical(str(e), exc_info=True)
                    radio.status = Radio.STATUS_ERROR_UNEXPECTED
                    save_data_to_db = sync_to_async(Command.save_data_to_db)
                    await save_data_to_db(radio)

                    if actual_queue:
                        # is broadcast is stopped set current queue file again to queue
                        actual_queue.status = Queue.STATUS_IN_QUEUE
                        save_data_to_db = sync_to_async(Command.save_data_to_db)
                        await save_data_to_db(actual_queue)

                    await self.send_message(
                        _('There is unexpected error, please address to @sgavka!'),
                        radio
                    )
                    del self.storage.radios[radio.id]
                    break
        except NetworkError as e:
            radio.status = Radio.STATUS_ERROR_NETWORK
            save_data_to_db = sync_to_async(Command.save_data_to_db)
            await save_data_to_db(radio)

            del self.storage.radios[radio.id]

            if actual_queue:
                # is broadcast is stopped set current queue file again to queue
                actual_queue.status = Queue.STATUS_IN_QUEUE
                save_data_to_db = sync_to_async(Command.save_data_to_db)
                await save_data_to_db(actual_queue)

            self.logger.critical(str(e), exc_info=True)

            pass
        except KeyboardInterrupt as e:
            radio.status = Radio.STATUS_ERROR_UNEXPECTED
            save_data_to_db = sync_to_async(Command.save_data_to_db)
            await save_data_to_db(radio)

            del self.storage.radios[radio.id]

            if actual_queue:
                # is broadcast is stopped set current queue file again to queue
                actual_queue.status = Queue.STATUS_IN_QUEUE
                save_data_to_db = sync_to_async(Command.save_data_to_db)
                await save_data_to_db(actual_queue)

            raise e
        except Exception as e:
            radio.status = Radio.STATUS_ERROR_UNEXPECTED
            save_data_to_db = sync_to_async(Command.save_data_to_db)
            await save_data_to_db(radio)

            del self.storage.radios[radio.id]

            if actual_queue:
                try:
                    # is broadcast is stopped set current queue file again to queue
                    actual_queue.status = Queue.STATUS_IN_QUEUE
                    save_data_to_db = sync_to_async(Command.save_data_to_db)
                    await save_data_to_db(actual_queue)
                except UnboundLocalError:
                    pass

            self.logger.critical(str(e), exc_info=True)

            await self.send_message(
                _('There is unexpected error, please address to @sgavka!'),
                radio
            )
            pass

    def get_first_queue(self, radio):
        first_queue = Queue.objects.filter(radio=radio, status=Queue.STATUS_IN_QUEUE) \
            .order_by('sort').first()
        if first_queue:
            # get audio file object (need to do there to have access from queue object outside of this method
            audio_file = first_queue.audio_file
        return first_queue

    def get_queue_count(self, radio):
        count = Queue.objects.filter(radio=radio, status__in=[Queue.STATUS_IN_QUEUE, Queue.STATUS_PROCESSING]).count()
        return count

    def refresh_data_from_db(self, model):
        model.refresh_from_db()
        return model

    @classmethod
    def save_data_to_db(cls, model):
        model.save()

    async def participant_list_updated(self, group_call: GroupCallFile, queue_group_call: QueueGroupCall, participants):
        # queue_group_call = self._get_queue_group_call_in_handler(group_call)
        self.logger.error('participant_list_updated: ' + group_call.full_chat.about)
        if queue_group_call is not False:
            data = GetGroupParticipants(
                call=InputGroupCall(id=group_call.group_call.id, access_hash=group_call.group_call.access_hash),
                ids=[],
                sources=[],
                offset='',
                limit=5000,  # todo: is this enough?
            )

            group_participants: GroupParticipants = await queue_group_call.client.send(data)
            if type(group_participants) is GroupParticipants:
                channel_id = get_channel_id(group_call.full_chat.id)  # todo: check if works for chats
                self.logger.error('participant_list_updated: ' + group_call.full_chat.about + ' count: ' + str(group_participants.count))
                if group_participants.count - 1 == 0:
                    await queue_group_call.set_title(_('Pausing...'), channel_id)
                    queue_group_call.asking_pause()
                elif queue_group_call.is_on_zero_participants_pause():
                    await queue_group_call.set_title(_('Resuming...'), channel_id)
                    queue_group_call.asking_resume()
            else:
                self.logger.error(
                    _('Can\'n get GroupParticipants for group call for queue ID: `%s`.') % (
                        queue_group_call.queue.id,
                    )
                )
                pass  # todo: some times all works but code fall there, why?

    async def playout_ended(self, group_call, file_name):
        # mark prev queue as played
        queue_group_call = self._get_queue_group_call_in_handler(group_call)
        if queue_group_call is not False:
            last_queue = queue_group_call.get_queue()
            if last_queue:
                set_queue_played_status = sync_to_async(self._set_queue_played_status)
                await set_queue_played_status(last_queue)
            await queue_group_call.set_title(_('Next track...'))
            queue_group_call.set_queue(None)
            queue_group_call._is_now_playing = False
            # delete prev file from disk
            os.remove(file_name)
        else:
            self.logger.error('Can\'t find group call to end playout!', exc_info=True)

    def _get_queue_group_call_in_handler(self, group_call) -> QueueGroupCall:
        client_radio: QueueRadio
        for client_radio in self.storage.radios.values():
            if client_radio.group_call is not None:
                if type(group_call.chat_peer) is InputPeerChat:
                    if client_radio.group_call.chat_id == get_channel_id(group_call.chat_peer.channel_id):  # todo: check if this works
                        return client_radio.group_call
                elif type(group_call.chat_peer) is InputPeerChannel:
                    if client_radio.group_call.chat_id == get_channel_id(group_call.chat_peer.channel_id):
                        return client_radio.group_call
        return False

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
