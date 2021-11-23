import asyncio
import os
from multiprocessing import Process
from time import sleep

import ffmpeg
import pyrogram
from pyrogram.raw import functions
from django.core.management.base import BaseCommand
from pyrogram.raw.types import InputPeerChat
from pyrogram import Client, idle

# variants:
# - set low outgoing_audio_bitrate_kbit in group call -- no difference
# - change bitrate, channels & rate on ffmpeg -- bad
# - use raw group call -- no works
# - sleep
# - - sleep(1) in the end of loop -- no
# - - sleep(0.00000001) after every action -- no
# - - sleep(0.000000001) after every action -- so-so
# - - 2 prev -- no
# - use pytgcalls dev --
# - check py-tgcalls
# -- install npm & nodejs >=15v

from pytgcalls import PyTgCalls, StreamType
from pytgcalls.types.groups import JoinedGroupCallParticipant
from pytgcalls.types.input_stream import InputStream, InputAudioStream


class Command(BaseCommand):
    TOKEN = os.environ.get('TELEGRAM_API_KEY')
    INPUT_FILENAME = 'input.raw'
    OUTPUT_FILENAME = 'output.raw'

    async def playout_ended(self, group_call, file_name):
        pass

    async def participant_list_updated(self, group_call, participants):
        self.stdout.write(self.style.SUCCESS('Participant list updated first: ' + group_call.full_chat.about))
        pass

    async def participant_list_updated_second(self, group_call, participants):
        self.stdout.write(self.style.SUCCESS('Participant list updated second: ' + group_call.full_chat.about))
        pass

    async def main(self, client: Client = None):
        client = Client('2057673468_account_1', # '1_queue_add_new'
                        api_id=18217511,
                        api_hash='a89ec27a235fb147ff5d0457fe793d18',
                        workdir='data/sessions'
                        # ,test_mode=True
                        )
        is_authorized = await client.connect()
        if not is_authorized:
            self.stdout.write(self.style.ERROR('First client is not authorized!'))
            return

        await client.initialize()
        while not client.is_connected:
            self.stdout.write(self.style.ERROR('First client is not connected!'))
            return

        client_second = Client('2057673468_account_2',  # '1_queue_add_new'
                               api_id=18217511,
                               api_hash='a89ec27a235fb147ff5d0457fe793d18',
                               workdir='data/sessions'
                               # ,test_mode=True
                               )
        is_authorized = await client_second.connect()
        if not is_authorized:
            self.stdout.write(self.style.ERROR('Second client is not authorized'))
            return
        await client_second.initialize()
        while not client_second.is_connected:
            self.stdout.write(self.style.ERROR('Second client is not connected!'))
            return

        try:
            group_id = -1001680538518
            group_id_second = -1001771950391

            group_call = False
            group_call_second = False

            is_handler_playout_ended_set = False
            is_handler_playout_ended_set_second = False

            is_handler_participant_list_updated_set = False
            is_handler_participant_list_updated_set_second = False

            is_started = False
            is_started_second = False

            is_file_set = False
            is_file_set_second = False

            skip_prepare_file = False
            skip_prepare_file_second = False

            while True:
                group_call = await self.init_group_call(client, group_call)
                group_call_second = await self.init_group_call(client_second, group_call_second)

                # is_handler_playout_ended_set = await self.init_handler(group_call, is_handler_playout_ended_set)

                if not is_handler_participant_list_updated_set:
                    @group_call.on_participants_change()
                    async def handler(client: PyTgCalls, update: JoinedGroupCallParticipant):
                        self.stdout.write(self.style.SUCCESS('Participant list updated. First!'))
                        pass
                    is_handler_participant_list_updated_set = True

                if not is_handler_participant_list_updated_set_second:
                    @group_call_second.on_participants_change()
                    async def handler_second(client: PyTgCalls, update: JoinedGroupCallParticipant):
                        self.stdout.write(self.style.SUCCESS('Participant list updated. Second!'))
                        pass
                    is_handler_participant_list_updated_set_second = True

                is_started = await self.init_start(group_call, group_id, is_started)
                is_started_second = await self.init_start(group_call_second, group_id_second, is_started_second)

                file_path_raw, original_file = await self.init_file_names(1)
                file_path_raw_second, original_file_second = await self.init_file_names(4)

                skip_prepare_file = await self.init_file_prepare(file_path_raw, original_file, skip_prepare_file)
                skip_prepare_file_second = await self.init_file_prepare(file_path_raw_second, original_file_second, skip_prepare_file_second)

                is_file_set = await self.init_set_file(file_path_raw, group_call, is_file_set, group_id)
                is_file_set_second = await self.init_set_file(file_path_raw_second, group_call_second, is_file_set_second, group_id_second)

                # if not is_file_set_second:
                #     group_call_second.input_filename = self.INPUT_FILENAME
                #     is_file_set_second = True

                await asyncio.sleep(1)
                sleep(1)
        # except GroupCallNotFoundError as e:
        #     self.stdout.write(self.style.ERROR('Error GroupCallNotFoundError: ' + str(e)))
        #     return
        except Exception as e:
            self.stdout.write(self.style.ERROR('Error: ' + str(e)))
            return

        pass
        # to change audio file you can do this:
        # group_call.input_filename = 'input2.raw'

        # to change output file:
        # group_call.output_filename = 'output2.raw'

        # to restart play from start:
        # group_call.restart_playout()

        # to stop play:
        # group_call.stop_playout()

        # same with output (recording)
        # .restart_recording, .stop_output

        # to mute yourself:
        # group_call.set_is_mute(True)

        # to leave a VC
        # group_call.stop()

        # to rejoin
        # group_call.rejoin()

        pass
        # await pyrogram.idle()

    async def init_set_file(self, file_path_raw, group_call: PyTgCalls, is_file_set, group_id):
        if not is_file_set:
            await group_call.join_group_call(
                group_id,
                InputStream(
                    InputAudioStream(
                        file_path_raw,
                    ),
                ),
                stream_type=StreamType().local_stream,
            )
            is_file_set = True
            self.stdout.write(self.style.SUCCESS('Set file to play in First Group Call.'))
        return is_file_set

    async def init_file_prepare(self, file_path_raw, original_file, skip_prepare_file):
        if not skip_prepare_file:
            self.stdout.write(self.style.SUCCESS('Start prepare file for First Group Call.'))
            ffmpeg.input(original_file) \
                .output(file_path_raw,
                        format='s16le',
                        acodec='pcm_s16le',
                        ac=1,
                        ar='48k',
                        **{
                            'b:a': '128k'
                        }) \
                .overwrite_output() \
                .run()
            self.stdout.write(self.style.SUCCESS('Ended prepare file for First Group Call.'))
            skip_prepare_file = True
        return skip_prepare_file

    async def init_file_names(self, id: int):
        original_file = 'data/test/' + str(id) + '.mp3'
        file_name_raw = str(id) + '.raw'
        file_directory = 'data/test/'
        if not os.path.exists(file_directory):
            os.makedirs(file_directory)
        file_path_raw = file_directory + file_name_raw
        return file_path_raw, original_file

    async def init_start(self, group_call: PyTgCalls, group_id, is_started):
        if not is_started:
            self.stdout.write(self.style.SUCCESS('Try to start broadcast for First Group Call.'))
            await group_call.start()
            while not group_call.is_connected:  # after that the group call starts
                self.stdout.write(self.style.ERROR('Can\'t start First Group Call. Wait!'))
                await asyncio.sleep(0.001)
            # group_call.play_on_repeat = False
            is_started = True
            self.stdout.write(self.style.SUCCESS('First Group Call is started!'))
        return is_started

    async def init_handler(self, group_call: PyTgCalls, is_handler_playout_ended_set):
        if not is_handler_playout_ended_set:
            group_call.on_playout_ended(self.playout_ended)
            is_handler_playout_ended_set = True
            self.stdout.write(self.style.SUCCESS('Playout Ended handler for First Group Call is set.'))
        return is_handler_playout_ended_set

    async def init_group_call(self, client, group_call) -> PyTgCalls:
        if group_call is False:
            group_call = PyTgCalls(client)
            self.stdout.write(self.style.SUCCESS('First Group Call is created.'))
        return group_call

    def setup(self):
        loop = asyncio.new_event_loop()
        loop.run_until_complete(self.main())

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Start!'))

        import logging
        logging.basicConfig(level=logging.DEBUG)

        process = Process(target=self.setup)
        process.start()

        self.stdout.write(self.style.SUCCESS('Code after Process starts.'))

        while True:
            sleep(10)

        self.stdout.write(self.style.SUCCESS('End!'))
