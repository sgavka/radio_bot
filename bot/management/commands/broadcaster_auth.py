import os
from django.core.management.base import BaseCommand
from django.db import transaction
from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded, RPCError, PhoneCodeExpired, BadRequest
from pyrogram.types import TermsOfService, User
from bot.models import BroadcastUser, BroadcasterAuthQueue
from bot.services.telegram_sessions import get_tmp_session_name, get_session_directory, get_session_name


class Command(BaseCommand):
    apps = {}

    def handle(self, *args, **options):
        while True:
            broadcaster_queue = BroadcasterAuthQueue.objects.filter(status__in=[
                BroadcasterAuthQueue.STATUS_NEED_TO_AUTH,
                BroadcasterAuthQueue.STATUS_NEED_TO_AUTH_WITH_CODE,
                BroadcasterAuthQueue.STATUS_NEED_TO_AUTH_WITH_PASSWORD,
            ]).all()
            # todo: maybe use subprocess there
            for broadcast_auth in broadcaster_queue:
                self.login(broadcast_auth)

    def login(self, broadcast_auth: BroadcasterAuthQueue):
        # init sessions directory
        sessions_directory = get_session_directory()

        # todo: remote after debugging
        import logging
        logging.basicConfig(level=logging.DEBUG)

        # get client
        session_name = get_tmp_session_name(broadcast_auth.id)
        if session_name in self.apps.keys():
            app = self.apps[session_name]
        else:
            app = Client(session_name,
                         api_id=int(broadcast_auth.broadcast_user.api_id),
                         api_hash=broadcast_auth.broadcast_user.api_hash,
                         workdir=sessions_directory
                         # ,test_mode=True
                         )
            self.apps[session_name] = app

        # check if session is already authorized
        is_authorize = False
        try:
            is_authorize = app.connect()
        except ConnectionError:
            pass  # go to next block

        user = None
        if not is_authorize:
            try:
                if not app.is_connected:
                    app.connect()

                if broadcast_auth.status == BroadcasterAuthQueue.STATUS_NEED_TO_AUTH:
                    try:
                        code_result = app.send_code(broadcast_auth.broadcast_user.phone_number)
                    except BadRequest:
                        broadcast_auth.status = BroadcasterAuthQueue.STATUS_PHONE_IS_INVALID
                        broadcast_auth.save()
                    else:
                        broadcast_auth.phone_hash = code_result.phone_code_hash
                        broadcast_auth.status = BroadcasterAuthQueue.STATUS_NEED_CODE
                        broadcast_auth.save()
                elif broadcast_auth.status == BroadcasterAuthQueue.STATUS_NEED_TO_AUTH_WITH_CODE:
                    try:
                        auth = app.sign_in(
                            phone_number=broadcast_auth.broadcast_user.phone_number,
                            phone_code_hash=broadcast_auth.phone_hash,
                            phone_code=broadcast_auth.code
                        )
                        if type(auth) is TermsOfService or (type(auth) is bool and auth is False):
                            broadcast_auth.status = BroadcasterAuthQueue.STATUS_ACCOUNT_IS_NOT_REGISTERED
                            broadcast_auth.save()
                        elif type(auth) is User or (type(auth) is bool and auth is True):
                            user = auth
                            self.set_success(broadcast_auth, app)
                    except PhoneCodeExpired:
                        broadcast_auth.status = BroadcasterAuthQueue.STATUS_CODE_EXPIRED
                        broadcast_auth.save()
                    except SessionPasswordNeeded:
                        broadcast_auth.status = BroadcasterAuthQueue.STATUS_NEED_PASSWORD
                        broadcast_auth.save()
                    except BadRequest:
                        broadcast_auth.status = BroadcasterAuthQueue.STATUS_CODE_IS_INVALID
                        broadcast_auth.save()
                elif broadcast_auth.status == BroadcasterAuthQueue.STATUS_NEED_TO_AUTH_WITH_PASSWORD:
                    try:
                        user = app.check_password(broadcast_auth.password)
                    except BadRequest:
                        broadcast_auth.status = BroadcasterAuthQueue.STATUS_PASSWORD_IS_INVALID
                        broadcast_auth.save()
                    else:
                        self.set_success(broadcast_auth, app)
            except RPCError as e:
                broadcast_auth.status = BroadcasterAuthQueue.STATUS_UNKNOWN_ERROR
                broadcast_auth.save()
                # todo: logging
        else:
            self.set_success(broadcast_auth, app)

    def set_success(self, broadcast_auth: BroadcasterAuthQueue, app: Client):
        user = app.get_me()
        if type(user) is User:
            with transaction.atomic():
                broadcast_auth.broadcast_user.uid = user.id

                broadcast_auth.status = BroadcasterAuthQueue.STATUS_SUCCESS
                broadcast_auth.broadcast_user.status = BroadcastUser.STATUS_IS_AUTH
                broadcast_auth.save()
                broadcast_auth.broadcast_user.save()

            session_name = get_tmp_session_name(broadcast_auth.id)
            session_path = 'data/sessions/'
            os.rename(
                session_path + session_name + '.session',
                session_path + get_session_name(broadcast_auth.broadcast_user.uid) + '.session'
            )
            del self.apps[session_name]
