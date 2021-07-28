from telegram import Update, ParseMode, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import PicklePersistence, Updater, Dispatcher, CallbackContext, CommandHandler, ConversationHandler, \
    CallbackQueryHandler, MessageHandler, Filters
from django.utils.translation import ugettext as _

from bot.bot_logic.bot_logic import BotLogic
from bot.bot_logic.radio import BotLogicRadio
from bot.helpers import handlers_wrapper, GoogleHelper
from bot.models import Bot


class BotLogicMain(BotLogic):
    RADIO_CALLBACK_DATA = 'radio'
    ADMIN_CALLBACK_DATA = 'admin'
    BACK_CALLBACK_DATA = 'back'

    RADIO_STATE = 'radio'
    ADMIN_STATE = 'admin'

    def __init__(self):
        self.updater: Updater = None
        self.bot: Bot = None

    def select_bot(self):
        bot = Bot.objects.first()
        if not bot:
            raise Exception('Bot must be set in DB!')

        self.bot = bot

    @classmethod
    def error_handler(cls, update: Update, context: CallbackContext):
        pass

    @classmethod
    @handlers_wrapper
    def start_handler(cls, update: Update, context: CallbackContext):
        keyboard = cls.get_main_menu_keyboard()
        context.bot.send_message(
            update.effective_chat.id,
            text=_('Hello, it\'s *Personal Radio Bot*! Start with creating your personal radio.'),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return cls.RADIO_STATE

    def init(self):
        self.select_bot()
        self.setup_updater()

        dispatcher: Dispatcher = self.updater.dispatcher

        conversation_handler = ConversationHandler(
            entry_points=[CommandHandler('start', self.start_handler)],
            states={
                self.RADIO_STATE: [
                    BotLogicRadio.get_conversation_handler(),
                    CallbackQueryHandler(self.enter_admin_section_handler, pattern=self.ADMIN_CALLBACK_DATA),
                ],
                self.ADMIN_STATE: [
                    CommandHandler('google_auth', self.google_auth_command_handler),
                    CallbackQueryHandler(self.back_from_admin_handler, pattern=self.BACK_CALLBACK_DATA),
                    MessageHandler(Filters.all, self.admin_message_handler),
                ]
            },
            fallbacks=[]
        )

        dispatcher.add_handler(conversation_handler)

        dispatcher.add_error_handler(self.error_handler)

        self.updater.start_polling()

    def setup_updater(self):
        persistence = PicklePersistence(filename='data/bot_states.prs')
        self.updater = Updater(token=self.bot.token, persistence=persistence, use_context=True)

    @classmethod
    def get_main_menu_keyboard(cls):
        keyboard = [
            [
                InlineKeyboardButton(
                    _('Radio List'),
                    callback_data=cls.RADIO_CALLBACK_DATA),
            ],
        ]

        if cls.telegram_user.is_admin():
            keyboard.append([
                InlineKeyboardButton(
                    _('Admin section'),
                    callback_data=cls.ADMIN_CALLBACK_DATA),
            ])

            keyboard.append([
                InlineKeyboardButton(
                    _('Back from Admin section'),
                    callback_data=cls.BACK_CALLBACK_DATA),
            ])

        return keyboard

    @classmethod
    @handlers_wrapper
    def enter_admin_section_handler(cls, update: Update, context: CallbackContext):
        context.bot.send_message(
            update.effective_chat.id,
            text=_('You are now in Admin section.\n'
                   'Admin\'s commands:\n'
                   '/google\\_auth — connect google account to read & write Spreadsheets.'),
            parse_mode=ParseMode.MARKDOWN
        )

        return cls.ADMIN_STATE

    @classmethod
    @handlers_wrapper
    def google_auth_command_handler(cls, update: Update, context: CallbackContext):
        url = GoogleHelper.get_auth_url()
        context.bot.send_message(update.effective_chat.id,
                                 _('Open URL & login to account, then copy token and paste below: %s') % (url,))
        context.chat_data['state'] = 'wait_google_auth_token'

    @classmethod
    def set_google_auth_token_handler(cls, update: Update, context: CallbackContext):
        if not GoogleHelper.save_token(update.message.text):
            context.bot.send_message(update.effective_chat.id,
                                     'Token is invalid. Try again!')
            return
        context.bot.send_message(update.effective_chat.id,
                                 'Token is saved!')
        del context.chat_data['state']

    @classmethod
    def admin_message_handler(cls, update: Update, context: CallbackContext):
        if 'state' in context.chat_data:
            if context.chat_data['state'] == 'wait_google_auth_token':
                cls.set_google_auth_token_handler(update, context)

    @classmethod
    def back_from_admin_handler(cls, update: Update, context: CallbackContext):
        return ConversationHandler.END
