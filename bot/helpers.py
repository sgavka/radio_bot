import os
import pickle
from functools import wraps

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build, Resource
from telegram import Update
from telegram.ext import CallbackContext

from bot.bot_logic.bot_logic import BotLogic
from bot.models import TelegramUser


def handlers_wrapper(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        bot_logic: BotLogic = args[0]
        update: Update = args[1]
        context: CallbackContext = args[2]
        telegram_user_id = update.effective_user.id
        telegram_user = TelegramUser.objects.filter(uid=telegram_user_id).get()
        bot_logic.telegram_user = telegram_user
        bot_logic.update = update
        bot_logic.context = context
        return function(*args, **kwargs)

    return wrapper


class GoogleHelper:
    GOOGLE_API_SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
    PATH_TO_CREDS = 'data/google_token.pickle'

    @classmethod
    def init_drive_service(cls):
        creds = cls.get_google_creds()
        service = build('drive', 'v3', credentials=creds)
        return service

    @classmethod
    def init_sheets_service(cls) -> Resource:
        creds = cls.get_google_creds()
        service = build('sheets', 'v4', creds)
        return service

    @classmethod
    def get_google_creds(cls):
        # The file stores the user's access and refresh tokens, and is
        # created automatically when the authorization flow completes for the first
        # time.
        if os.path.exists(cls.PATH_TO_CREDS):
            with open(cls.PATH_TO_CREDS, 'rb') as token:
                creds = pickle.load(token)
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                # Save the credentials to the file
                with open(cls.PATH_TO_CREDS, 'wb') as token:
                    pickle.dump(creds, token)
        else:
            raise Exception  # todo: determine exception more exactly
        return creds

    @classmethod
    def save_token(cls, token) -> bool:
        flow = cls.get_flow()
        try:
            creds = flow.fetch_token(code=token)
        except:
            return False

        # Save the credentials to the file
        with open(cls.PATH_TO_CREDS, 'wb') as token:
            pickle.dump(flow.credentials, token)

        return True

    @classmethod
    def get_flow(cls):
        flow = InstalledAppFlow.from_client_secrets_file(
            'google_credentials.json', cls.GOOGLE_API_SCOPES)
        flow.redirect_uri = flow._OOB_REDIRECT_URI
        return flow

    @classmethod
    def get_auth_url(cls) -> str:
        flow = cls.get_flow()
        url, state = flow.authorization_url()
        return url
