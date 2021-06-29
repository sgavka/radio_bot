from telegram import Update, ParseMode, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import PicklePersistence, Updater, Dispatcher, CallbackContext, CommandHandler, ConversationHandler, \
    CallbackQueryHandler
from django.utils.translation import ugettext as _

from bot.bot_logic.bot_logic import BotLogic
from bot.bot_logic.radio import BotLogicRadio
from bot.models import Bot


class BotLogicMain(BotLogic):
    RADIO_CALLBACK_DATA = 'radio'

    RADIO_STATE = 'radio'

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
                self.RADIO_STATE: [BotLogicRadio.get_conversation_handler()]
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

        return keyboard
