import asyncio
import os
from multiprocessing import Process

import pyrogram
import pytgcalls
from django.core.management.base import BaseCommand
from pyrogram.raw.types import InputPeerChat
from pytgcalls.exceptions import GroupCallNotFoundError
from pyrogram import Client, idle


class Command(BaseCommand):
    TOKEN = os.environ.get('TELEGRAM_API_KEY')
    INPUT_FILENAME = 'input.raw'
    OUTPUT_FILENAME = 'output.raw'

    async def playout_ended(self, group_call, file_name):
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
            pass
        await client.initialize()
        while not client.is_connected:
            return

        client_second = Client('2057673468_account_2',  # '1_queue_add_new'
                        api_id=18217511,
                        api_hash='a89ec27a235fb147ff5d0457fe793d18',
                        workdir='data/sessions'
                        # ,test_mode=True
                        )
        is_authorized = await client_second.connect()
        if not is_authorized:
            pass
        await client_second.initialize()
        while not client_second.is_connected:
            return

        try:
            group_call = False
            group_call_second = False
            is_handler_playout_ended_set = False
            is_handler_playout_ended_set_second = False
            is_started = False
            is_started_second = False
            is_file_set = False
            is_file_set_second = False
            while True:
                if group_call is False:
                    group_call = pytgcalls.GroupCallFactory(client).get_file_group_call()

                if group_call_second is False:
                    group_call_second = pytgcalls.GroupCallFactory(client_second).get_file_group_call()

                if not is_handler_playout_ended_set:
                    group_call.on_playout_ended(self.playout_ended)
                    is_handler_playout_ended_set = True

                if not is_handler_playout_ended_set_second:
                    group_call_second.on_playout_ended(self.playout_ended)
                    is_handler_playout_ended_set_second = True

                if not is_started:
                    await group_call.start(-1001647841512)
                    while not group_call.is_connected:  # after that the group call starts
                        await asyncio.sleep(0.001)
                    group_call.play_on_repeat = False
                    is_started = True

                if not is_started_second:
                    await group_call_second.start(-1001692110023)
                    while not group_call_second.is_connected:  # after that the group call starts
                        await asyncio.sleep(0.001)
                    group_call_second.play_on_repeat = False
                    is_started_second = True

                if not is_file_set:
                    group_call.input_filename = self.INPUT_FILENAME
                    is_file_set = True

                if not is_file_set_second:
                    group_call_second.input_filename = self.INPUT_FILENAME
                    is_file_set_second = True

                # await asyncio.sleep(0.001)
            pass
        except GroupCallNotFoundError as e:
            pass
        except Exception as e:
            pass

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
        await pyrogram.idle()

    def setup(self):
        loop = asyncio.new_event_loop()
        loop.run_until_complete(self.main())

    def handle(self, *args, **options):
        import logging
        logging.basicConfig(level=logging.DEBUG)

        process = Process(target=self.setup)
        process.start()
        while True:
            pass
