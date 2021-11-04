from telegram import Update, ParseMode, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import PicklePersistence, Updater, Dispatcher, CallbackContext, CommandHandler, ConversationHandler, \
    CallbackQueryHandler, MessageHandler, Filters
from django.utils.translation import ugettext as _

from bot.bot_logic.bot_logic import BotLogic
from bot.bot_logic.radio import BotLogicRadio
from bot.bot_logic.radio_telegram_account import BotLogicRadioTelegramAccount
from bot.helpers import handlers_wrapper
from bot.models import Bot


class BotLogicMain(BotLogic):
    RADIO_CALLBACK_DATA = 'radio'
    TELEGRAM_ACCOUNT_CALLBACK_DATA = 'telegram_account'
    ADMIN_CALLBACK_DATA = 'admin'
    BACK_CALLBACK_DATA = 'back'

    RADIO_STATE = 'radio'
    ADMIN_STATE = 'admin'

    def __init__(self):
        self.updater: Updater = None
        self.bot: Bot = None

    def select_bot(self):
        from bot.services.bot import get_bot_from_db
        self.bot = get_bot_from_db()

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
                    BotLogicRadioTelegramAccount.get_conversation_handler(),
                    CallbackQueryHandler(self.enter_admin_section_handler, pattern=self.ADMIN_CALLBACK_DATA),
                ],
                self.ADMIN_STATE: [
                    CallbackQueryHandler(self.back_from_admin_handler, pattern=self.BACK_CALLBACK_DATA),
                    MessageHandler(Filters.all, self.admin_message_handler),
                ],
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
                InlineKeyboardButton(
                    _('Telegram Account List'),
                    callback_data=cls.TELEGRAM_ACCOUNT_CALLBACK_DATA),
            ],
        ]

        if cls.telegram_user.is_admin():
            keyboard.append([
                InlineKeyboardButton(
                    _('Admin section'),
                    callback_data=cls.ADMIN_CALLBACK_DATA),
            ])

        return keyboard

    @classmethod
    @handlers_wrapper
    def enter_admin_section_handler(cls, update: Update, context: CallbackContext):
        message = context.bot.send_message(
            update.effective_chat.id,
            text=_('You are now in Admin section.\n'
                   'Admin\'s commands:\n'
                   '[[empty]]'),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    _('Leave Admin Section'),
                    callback_data=cls.BACK_CALLBACK_DATA), ],
            ])
        )
        context.chat_data['admin_section_message_id'] = message.message_id

        context.bot.answer_callback_query(update.callback_query.id)
        return cls.ADMIN_STATE

    @classmethod
    def admin_message_handler(cls, update: Update, context: CallbackContext):
        if 'state' in context.chat_data:
            pass

    @classmethod
    def back_from_admin_handler(cls, update: Update, context: CallbackContext):
        if 'admin_section_message_id' in context.chat_data:
            context.bot.delete_message(
                update.effective_chat.id,
                context.chat_data['admin_section_message_id']
            )

        context.bot.answer_callback_query(update.callback_query.id)
        return cls.RADIO_STATE
