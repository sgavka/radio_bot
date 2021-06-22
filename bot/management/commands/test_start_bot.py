1import asyncio
import logging
import os
from typing import Dict

import pyrogram
import pytgcalls
from django.core.management.base import BaseCommand
from pyrogram.errors import SessionPasswordNeeded, RPCError

from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext, Dispatcher, PicklePersistence, \
    InlineQueryHandler, CallbackQueryHandler, MessageHandler, MessageFilter, Filters

from pyrogram import Client, filters
from pyrogram.utils import MAX_CHANNEL_ID

from pytgcalls import GroupCall


class Command(BaseCommand):
    TOKEN = os.environ.get('TELEGRAM_API_KEY')
    INPUT_FILENAME = 'input.raw'
    OUTPUT_FILENAME = 'output.raw'

    async def main(self, client: Client):
        await client.start()
        while not client.is_connected:
            return

        try:
            group_call = pytgcalls.GroupCall(client, self.INPUT_FILENAME, self.OUTPUT_FILENAME)
            await group_call.start(-582672833)
            await asyncio.sleep(15)
            group_call.input_filename = None
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

    def login(
        self,
        phone: str,
        code: str = "",
        phone_hash: str = "",
        password: str = "",
        app = None
    ) -> Dict:
        if app is None:
            app = Client("sgavka",
                         api_id=1740375,
                         api_hash='b439c8ce88a1f2aa463f60a8895f86da'
                         )

        try:
            app.connect()
            if not code:
                code_result = app.send_code(phone)
                if code_result:
                    return {'status': False, 'phone_code_hash': code_result.phone_code_hash, 'app': app}
                return {'status': False, 'app': app}
            if code and phone_hash:
                app.sign_in(phone_number=phone, phone_code_hash=phone_hash, phone_code=code)
                return {'status': True, 'app': app}
        except SessionPasswordNeeded:
            if password:
                app.password = password
                app.sign_in(phone, phone_hash, code)
                return {'status': True, 'app': app}
            else:
                return {'status': False, 'app': app}
        except RPCError as e:
            return {'status': False, 'message': e, 'app': app}
        # finally:
        #     app.disconnect()
        return {'status': False, 'app': app}

    def handle(self, *args, **options):
        phone_number = '+380993638187'
        password = '199s5serhi2y4'
        app = Client('sgavka',
                     # bot_token='758816171:AAEEv_GxKGuSdOhxSgaU9NM-yMmM2L9x8fc',
                     # phone_number=phone_number,
                     # password=password,
                     api_id=1740375,
                     api_hash='b439c8ce88a1f2aa463f60a8895f86da'
                     )

        # login_result = self.login(phone_number, '', '', password)
        # if not login_result['status'] and login_result['phone_code_hash']:
        #     code = str(input())
        #     login_result = self.login(phone_number, code, login_result['phone_code_hash'], password)

        # print(login_result)
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.main(app))
