import re
from functools import wraps
from io import StringIO
from urllib.parse import urlparse

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import transaction
from telegram import Update, ParseMode, InlineKeyboardMarkup, InlineKeyboardButton, Message, MessageEntity
from telegram.error import BadRequest
from telegram.ext import ConversationHandler, CallbackQueryHandler, CallbackContext, MessageHandler, Filters
from django.utils.translation import ugettext as _
from bot.bot_logic.bot_logic import BotLogic, BotContext
from bot.helpers import handlers_wrapper
from bot.models import Radio, TelegramUser, UserToRadio, AudioFile
from bot.services import radio_user, google_sheets
import requests
import csv

from bot.services.radio_user import get_radio_queue


class BotContextRadio(BotContext):
    CONTEXT_NAME = 'radio'
    EDIT_CONTEXT = 'edit'
    ACTION_CONTEXT = 'action'
    ID_CONTEXT = 'id'
    NEW_OBJECT_CONTEXT = 'new_object'
    ACTUAL_FIELD_CONTEXT = 'actual_field'
    OBJECT_MESSAGE_CONTEXT = 'object_message'
    QUEUE_MESSAGE_CONTEXT = 'queue_message'
    MESSAGES_TO_DELETE_CONTEXT = 'messages_to_delete'
    QUEUE_MESSAGES_TO_DELETE_CONTEXT = 'queue_messages_to_delete'
    EDIT_OBJECT_CONTEXT = 'edit_object'
    LIST_MESSAGE_CONTEXT = 'list_message'

    EDIT_ACTION = 'edit'
    CREATE_ACTION = 'create'
    ADD_TO_QUEUE_ACTION = 'add_to_queue'

    @classmethod
    def wrapper(cls, function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            bot_logic: BotLogic = args[0]
            bot_logic.bot_context = BotContextRadio(bot_logic)
            return function(*args, **kwargs)

        return wrapper

    def __init__(self, bot_logic: BotLogic):
        self.bot_logic = bot_logic
        self.chat_data = bot_logic.context.chat_data
        self.radio = None
        self.edit = None
        self.radio_object = None
        self.new_object = None
        self.actual_field = None
        self.object_message = None

        self.init_context()
        self.init_edit_context()

    def init_context(self):
        if self.CONTEXT_NAME not in self.chat_data:
            self.chat_data[self.CONTEXT_NAME] = {}
        self.radio = self.chat_data[self.CONTEXT_NAME]

    def init_edit_context(self):
        if self.EDIT_CONTEXT not in self.radio:
            self.radio[self.EDIT_CONTEXT] = {}
        self.edit = self.radio[self.EDIT_CONTEXT]

    def set_edited_id(self, edit_id: int):
        self.edit[self.ID_CONTEXT] = edit_id
        if self.EDIT_OBJECT_CONTEXT in self.edit:
            del self.edit[self.EDIT_OBJECT_CONTEXT]

    def get_edited_object(self) -> Radio:
        if self.ID_CONTEXT not in self.edit:
            raise Exception('Edited Radio ID is not set!')
        if self.EDIT_OBJECT_CONTEXT not in self.edit:
            radio_object = Radio.objects.filter(id=self.edit[self.ID_CONTEXT]).get()
            self.edit[self.EDIT_OBJECT_CONTEXT] = radio_object
        return self.edit[self.EDIT_OBJECT_CONTEXT]

    def set_edit_action(self):
        self.radio[self.ACTION_CONTEXT] = self.EDIT_ACTION

    def set_create_action(self):
        self.radio[self.ACTION_CONTEXT] = self.CREATE_ACTION

    def set_add_to_queue_action(self):
        self.radio[self.ACTION_CONTEXT] = self.ADD_TO_QUEUE_ACTION

    def get_action(self):
        return self.radio[self.ACTION_CONTEXT]

    def is_edit_action(self):
        return self.radio[self.ACTION_CONTEXT] is self.EDIT_ACTION

    def is_create_action(self):
        return self.radio[self.ACTION_CONTEXT] is self.CREATE_ACTION

    def init_new_object(self):
        if self.NEW_OBJECT_CONTEXT not in self.radio:
            self.radio[self.NEW_OBJECT_CONTEXT] = Radio()
        return self.radio[self.NEW_OBJECT_CONTEXT]

    def get_actual_object(self) -> Radio:
        action = self.get_action()
        if action in [self.EDIT_ACTION, self.ADD_TO_QUEUE_ACTION]:
            return self.get_edited_object()
        elif action is self.CREATE_ACTION:
            return self.init_new_object()

    def has_actual_object(self):
        if self.get_actual_object():
            return True
        return False

    def set_actual_field(self, field_name):
        self.radio[self.ACTUAL_FIELD_CONTEXT] = field_name

    def get_actual_field(self):
        return self.radio[self.ACTUAL_FIELD_CONTEXT]

    def set_queue_message_id(self, message_id):
        self.radio[self.QUEUE_MESSAGE_CONTEXT] = message_id

    def get_queue_message_id(self):
        return self.radio[self.QUEUE_MESSAGE_CONTEXT]

    def add_queue_message_to_delete(self, message_id):
        if self.QUEUE_MESSAGES_TO_DELETE_CONTEXT not in self.radio:
            self.radio[self.QUEUE_MESSAGES_TO_DELETE_CONTEXT] = []
        self.radio[self.QUEUE_MESSAGES_TO_DELETE_CONTEXT].append(message_id)

    def delete_queue_messages(self):
        for message_id in self.radio[self.QUEUE_MESSAGES_TO_DELETE_CONTEXT]:
            try:
                self.bot_logic.context.bot.delete_message(self.bot_logic.update.effective_chat.id, message_id)
            except BadRequest:
                pass
        del self.radio[self.QUEUE_MESSAGES_TO_DELETE_CONTEXT]

    def add_message_to_delete(self, message_id):
        if self.MESSAGES_TO_DELETE_CONTEXT not in self.radio:
            self.radio[self.MESSAGES_TO_DELETE_CONTEXT] = []
        self.radio[self.MESSAGES_TO_DELETE_CONTEXT].append(message_id)

    def delete_list_message(self):
        if self.LIST_MESSAGE_CONTEXT in self.radio:
            message_id = self.radio[self.LIST_MESSAGE_CONTEXT]
            try:
                self.bot_logic.context.bot.delete_message(self.bot_logic.update.effective_chat.id, message_id)
            except BadRequest:
                pass

    def delete_messages(self):
        for message_id in self.radio[self.MESSAGES_TO_DELETE_CONTEXT]:
            try:
                self.bot_logic.context.bot.delete_message(self.bot_logic.update.effective_chat.id, message_id)
            except BadRequest:
                pass
        del self.radio[self.MESSAGES_TO_DELETE_CONTEXT]

    def set_list_message(self, message_id):
        self.radio[self.LIST_MESSAGE_CONTEXT] = message_id

    def get_list_message(self):
        return self.radio[self.LIST_MESSAGE_CONTEXT]

    def set_object_message_id(self, message_id):
        self.radio[self.OBJECT_MESSAGE_CONTEXT] = message_id
        self.add_message_to_delete(message_id)

    def get_object_message_id(self):
        return self.radio[self.OBJECT_MESSAGE_CONTEXT]

    def clear_after_save(self):
        self.delete_messages()
        del self.radio[self.OBJECT_MESSAGE_CONTEXT]
        if self.NEW_OBJECT_CONTEXT in self.radio:
            del self.radio[self.NEW_OBJECT_CONTEXT]
        del self.radio[self.EDIT_CONTEXT]


class BotLogicRadio(BotLogic):
    bot_context: BotContextRadio
    fields_errors: list

    CREATE_STATE = r'create'
    EDIT_STATE = r'edit'
    LIST_STATE = r'list'
    BACK_STATE = r'back'
    ACTIONS_STATE = r'actions'
    SET_FIELDS_STATE = r'set_fields'
    SET_FIELDS_TEXT_STATE = r'set_fields_text'
    ADD_TO_QUEUE_CALLBACK_STATE = r'add_to_queue'

    SET_NAME_CALLBACK_DATA = r'set_name'
    SET_TITLE_TEMPLATE_CALLBACK_DATA = r'set_title_template'
    SET_GOOGLE_TABLE_ID_CALLBACK_DATA = r'set_google_table_id'
    ADD_TO_QUEUE_CALLBACK_DATA = r'add_to_queue'
    BACK_CALLBACK_DATA = r'back'
    BACK_FROM_ADD_TO_QUEUE_CALLBACK_DATA = r'back_from_add_to_queue'
    REFRESH_GOOGLE_TABLE_CALLBACK_DATA = r'refresh_google_table'
    EDIT_BACK_CALLBACK_DATA = r'edit_back'
    SAVE_CALLBACK_DATA = r'save'
    CREATE_CALLBACK_DATA = r'create'
    EDIT_CALLBACK_DATA = r'edit_%s'
    EDIT_CALLBACK_DATA_PATTERN = r'edit_(\d+)'

    create_message_text = _('To create new object select field and set data.\nData:\n%s')
    edit_message_text = _('It\'s your radio *%s*.\n%s\nSelect some action.')
    list_message_text = _('Here is your radios. Select one to manage:')
    add_to_queue_message_text = _('Upload or forward audio files here to add them to queue.\nYour actual queue:\n%s')

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def edit_back(cls, update: Update, context: CallbackContext):
        cls.bot_context.clear_after_save()
        context.bot.answer_callback_query(update.callback_query.id, _('Back! Changes was cleared.'))
        return cls.LIST_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def back(cls, update: Update, context: CallbackContext):
        cls.bot_context.delete_list_message()
        return cls.BACK_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def back_from_add_to_queue(cls, update: Update, context: CallbackContext):
        cls.bot_context.delete_queue_messages()
        cls.bot_context.set_edit_action()
        return cls.SET_FIELDS_STATE

    @classmethod
    def get_queue_keyboard(cls):
        keyboard = [
            [
                InlineKeyboardButton(
                    _('Refresh from Google Table Queue'),
                    callback_data=cls.REFRESH_GOOGLE_TABLE_CALLBACK_DATA),
            ],
            [
                InlineKeyboardButton(
                    _('Back'),
                    callback_data=cls.BACK_FROM_ADD_TO_QUEUE_CALLBACK_DATA),
            ],
        ]

        return keyboard

    @classmethod
    def get_queue_message_text(cls):
        queues = get_radio_queue(cls.bot_context.get_actual_object())

        queue_list = []
        for queue in queues:
            audio_file: AudioFile = queue.audio_file
            queue_list.append(_('%s — %s') % (audio_file.author, audio_file.title))

        queue_list_str = '\n'.join(queue_list)
        return cls.add_to_queue_message_text % (queue_list_str if queue_list_str else '[[empty]]',)

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def add_to_queue_upload(cls, update: Update, context: CallbackContext):
        message: Message = update.message
        if message.audio is not None:
            radio_user.add_file_to_queue(message.audio, cls.bot_context.get_actual_object())
            message = context.bot.send_message(
                update.effective_chat.id,
                text=_('Thanks, file is added, you can continue or press Back.'),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(cls.get_queue_keyboard())
            )
            cls.bot_context.add_queue_message_to_delete(message.message_id)
            cls.update_queue_message()
        return cls.ADD_TO_QUEUE_CALLBACK_STATE

    @classmethod
    def update_queue_message(cls):
        message_id = cls.bot_context.get_queue_message_id()
        cls.context.bot.edit_message_text(cls.get_queue_message_text(),
                                          cls.update.effective_chat.id,
                                          message_id,
                                          parse_mode=ParseMode.MARKDOWN,
                                          reply_markup=InlineKeyboardMarkup(cls.get_queue_keyboard())
                                          )

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def add_to_queue(cls, update: Update, context: CallbackContext):
        cls.bot_context.set_add_to_queue_action()

        message = context.bot.send_message(
            update.effective_chat.id,
            text=cls.get_queue_message_text(),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(cls.get_queue_keyboard())
        )

        cls.bot_context.add_queue_message_to_delete(message.message_id)
        cls.bot_context.set_queue_message_id(message.message_id)

        return cls.ADD_TO_QUEUE_CALLBACK_STATE

    @classmethod
    def get_conversation_handler(cls) -> ConversationHandler:
        from bot.bot_logic.main import BotLogicMain
        list_handler = CallbackQueryHandler(cls.show_list, pattern=BotLogicMain.RADIO_CALLBACK_DATA)
        create_handler = CallbackQueryHandler(cls.create, pattern=cls.CREATE_CALLBACK_DATA)
        edit_handler = CallbackQueryHandler(cls.edit, pattern=cls.EDIT_CALLBACK_DATA_PATTERN)
        conversation_handler = ConversationHandler(
            entry_points=[list_handler],
            states={
                cls.LIST_STATE: [list_handler, create_handler, edit_handler],
                cls.SET_FIELDS_STATE: [
                    CallbackQueryHandler(cls.set_name_start, pattern=cls.SET_NAME_CALLBACK_DATA),
                    CallbackQueryHandler(cls.set_title_template_start, pattern=cls.SET_TITLE_TEMPLATE_CALLBACK_DATA),
                    CallbackQueryHandler(cls.set_google_table_id_start, pattern=cls.SET_GOOGLE_TABLE_ID_CALLBACK_DATA),
                    CallbackQueryHandler(cls.save, pattern=cls.SAVE_CALLBACK_DATA),
                    CallbackQueryHandler(cls.edit_back, pattern=cls.EDIT_BACK_CALLBACK_DATA),
                    CallbackQueryHandler(cls.add_to_queue, pattern=cls.ADD_TO_QUEUE_CALLBACK_DATA),
                ],
                cls.ADD_TO_QUEUE_CALLBACK_STATE: [
                    CallbackQueryHandler(cls.back_from_add_to_queue, pattern=cls.BACK_FROM_ADD_TO_QUEUE_CALLBACK_DATA),
                    MessageHandler(Filters.all, cls.add_to_queue_upload),
                ],
                cls.SET_FIELDS_TEXT_STATE: [MessageHandler(Filters.text, cls.set_fields_text)]
            },
            fallbacks=[
                CallbackQueryHandler(cls.back, pattern=cls.BACK_CALLBACK_DATA),
            ],
            map_to_parent={
                cls.BACK_STATE: BotLogicMain.RADIO_STATE,
                BotLogicMain.RADIO_STATE: BotLogicMain.RADIO_STATE,
            }
        )

        return conversation_handler

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def save(cls, update: Update, context: CallbackContext):
        context.bot.answer_callback_query(update.callback_query.id)
        radio = cls.bot_context.get_actual_object()
        radio_user = None

        if not hasattr(radio, 'telegram_account'):
            telegram_user = TelegramUser.objects.get(uid=update.effective_user.id)
            if not telegram_user:
                user = User.objects.create()
                telegram_user = TelegramUser.objects.create(uid=update.effective_user.id, user=user)
            radio_user = telegram_user.user

        saved = False
        try:
            try:
                radio.full_clean()
            except ValidationError as e:
                errors = '\n'.join(
                    [_('*%s*: _%s_') % (field, ', '.join(messages)) for (field, messages) in e.message_dict.items()]
                )
                message = context.bot.send_message(
                    update.effective_chat.id,
                    text=_('Your have validation error(-s):\n%s') % (errors,),
                    parse_mode=ParseMode.MARKDOWN
                )
                cls.bot_context.add_message_to_delete(message.message_id)
                return cls.SET_FIELDS_STATE

            with transaction.atomic():
                radio.save()
                radio_to_user = UserToRadio()
                radio_to_user.user = radio_user
                radio_to_user.radio = radio
                radio_to_user.save()

            saved = True
        except Exception as e:
            pass

        if saved:
            context.bot.answer_callback_query(update.callback_query.id, _('Radio was saved!'))

            cls.update_list_message()
            cls.bot_context.clear_after_save()

            return cls.LIST_STATE
        else:
            message = context.bot.send_message(
                update.effective_chat.id,
                text=_('Internal error. Please restart!'),
                parse_mode=ParseMode.MARKDOWN
            )
            cls.bot_context.add_message_to_delete(message.message_id)

            return ConversationHandler.END

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def create(cls, update: Update, context: CallbackContext):
        context.bot.answer_callback_query(update.callback_query.id)

        cls.bot_context.set_create_action()
        radio = cls.bot_context.init_new_object()
        keyboard = cls.get_object_keyboard()
        data_strings = cls.get_data_strings(radio)
        message = context.bot.send_message(
            update.effective_chat.id,
            text=cls.create_message_text % ('\n'.join(data_strings),),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        cls.bot_context.set_object_message_id(message.message_id)

        return cls.SET_FIELDS_STATE

    @classmethod
    def get_status_string(cls, radio):
        if not cls.bot_context.is_edit_action():
            return ''

        errors = []
        if radio.google_table_id is None:
            errors.append(_('⚠ You mast set Google Table Queue'))

        if errors:
            return _('Status: Need to Set Up\nProblems:\n%s') % ('\n'.join(errors),)
        return ''

    @classmethod
    def get_data_strings(cls, radio):
        data_strings = [_('Name**: %s') % (radio.name if radio.name else r'—',),
                        _('Title Template: %s') % (radio.title_template if radio.title_template else r'—',),
                        _('Google Table Queue: %s') % (
                            _('[link](%s)') % (radio.google_table_id,) if radio.google_table_id else r'—',
                        )]
        return data_strings

    @classmethod
    def get_object_keyboard(cls):
        radio = cls.bot_context.get_actual_object()
        if radio.name:
            set_name_text = _('Change name')
        else:
            set_name_text = _('Add name')

        if radio.google_table_id:
            set_google_table_id_text = _('Change Google Table Queue')
        else:
            set_google_table_id_text = _('Add Google Table Queue')

        if radio.title_template:
            set_title_template_text = _('Change Title Template')
        else:
            set_title_template_text = _('Add Title Template')

        keyboard = [[
            InlineKeyboardButton(
                set_name_text,
                callback_data=cls.SET_NAME_CALLBACK_DATA),
            InlineKeyboardButton(
                set_title_template_text,
                callback_data=cls.SET_TITLE_TEMPLATE_CALLBACK_DATA),
        ]]

        google_table_row = [
            InlineKeyboardButton(
                set_google_table_id_text,
                callback_data=cls.SET_GOOGLE_TABLE_ID_CALLBACK_DATA),
        ]

        if cls.bot_context.is_edit_action() and radio.google_table_id:
            google_table_row.append(
                InlineKeyboardButton(
                    _('Add to Queue'),
                    callback_data=cls.ADD_TO_QUEUE_CALLBACK_DATA),
            )

        keyboard.append(google_table_row)

        keyboard.append([
            InlineKeyboardButton(
                _('Save'),
                callback_data=cls.SAVE_CALLBACK_DATA),
        ])
        keyboard.append([
            InlineKeyboardButton(
                _('Back'),
                callback_data=cls.EDIT_BACK_CALLBACK_DATA),
        ])

        return keyboard

    @classmethod
    def set_google_table_id_check(cls):
        message: Message = cls.update.message
        entity: MessageEntity
        url = None
        for entity in message.entities:
            if entity.type == MessageEntity.URL:
                url = message.text[entity.offset:entity.length]
                break
        if url is None:
            cls.fields_errors.append(_('You mast sent URL.'))
            return False
        return google_sheets.is_queue_file_valid_by_url(url)

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def set_fields_text(cls, update: Update, context: CallbackContext):
        field = cls.bot_context.get_actual_field()
        radio = cls.bot_context.get_actual_object()

        valid = True
        if field is Radio.google_table_id.field.name:
            valid &= cls.set_google_table_id_check()

        if valid:
            setattr(radio, field, update.message.text)
            cls.update_object_message()

        return cls.SET_FIELDS_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def set_name_start(cls, update: Update, context: CallbackContext):
        context.bot.answer_callback_query(update.callback_query.id)

        cls.bot_context.set_actual_field('name')
        message = context.bot.send_message(
            update.effective_chat.id,
            text=_('Enter Name below:'),
            parse_mode=ParseMode.MARKDOWN,
        )
        cls.bot_context.add_message_to_delete(message.message_id)

        return cls.SET_FIELDS_TEXT_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def set_title_template_start(cls, update: Update, context: CallbackContext):
        context.bot.answer_callback_query(update.callback_query.id)

        cls.bot_context.set_actual_field('title_template')
        message = context.bot.send_message(
            update.effective_chat.id,
            text=_('Enter Title Template below:'),
            parse_mode=ParseMode.MARKDOWN,
        )
        cls.bot_context.add_message_to_delete(message.message_id)

        return cls.SET_FIELDS_TEXT_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def set_google_table_id_start(cls, update: Update, context: CallbackContext):
        context.bot.answer_callback_query(update.callback_query.id)

        cls.bot_context.set_actual_field('google_table_id')
        message = context.bot.send_message(
            update.effective_chat.id,
            text=_(
                'Enter Google Sheets URL below. Spreadsheet must be visible for every one with link. And have next '
                'columns on first page:\n'
                '- Title\n'
                '- Author\n'
                '- File ID\n'
                '- Date Time on Air\n'
                '- On Air always'
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
        cls.bot_context.add_message_to_delete(message.message_id)

        return cls.SET_FIELDS_TEXT_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def edit(cls, update: Update, context: CallbackContext):
        context.bot.answer_callback_query(update.callback_query.id)

        match = re.match(cls.EDIT_CALLBACK_DATA_PATTERN, update.callback_query.data)
        if match:
            edit_id = int(match.group(1))
            cls.bot_context.set_edited_id(edit_id)
            radio = cls.bot_context.get_edited_object()
            cls.bot_context.set_edit_action()

            keyboard = cls.get_object_keyboard()
            data_strings = cls.get_data_strings(radio)
            text = cls.edit_message_text % (radio.name, '\n'.join(data_strings))
            text += '\n' + cls.get_status_string(radio)
            message = context.bot.send_message(
                update.effective_chat.id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(keyboard),
                disable_web_page_preview=True
            )

            cls.bot_context.set_object_message_id(message.message_id)

            return cls.SET_FIELDS_STATE
        return cls.BACK_STATE

    @classmethod
    def get_list_keyboard(cls):
        radios = radio_user.get_user_radios(cls.telegram_user.user_id)
        keyboard_radios = []
        for radio in radios:
            keyboard_radios.append([
                InlineKeyboardButton(
                    _(radio.name),
                    callback_data=cls.EDIT_CALLBACK_DATA % (radio.id,))
            ])

        keyboard_radios.append([
            InlineKeyboardButton(
                _('Create New'),
                callback_data=cls.CREATE_CALLBACK_DATA),
        ])

        keyboard_radios.append([
            InlineKeyboardButton(
                _('Back'),
                callback_data=cls.BACK_CALLBACK_DATA),
        ])

        return keyboard_radios

    @classmethod
    def update_list_message(cls):
        message_id = cls.bot_context.get_list_message()
        keyboard = cls.get_list_keyboard()
        try:
            cls.context.bot.edit_message_reply_markup(cls.update.effective_chat.id,
                                                      message_id, reply_markup=InlineKeyboardMarkup(keyboard))
        except BadRequest:
            pass

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def show_list(cls, update: Update, context: CallbackContext):
        context.bot.answer_callback_query(update.callback_query.id)

        keyboard_radios = cls.get_list_keyboard()

        message = context.bot.send_message(
            update.effective_chat.id,
            text=cls.list_message_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard_radios)
        )

        cls.bot_context.set_list_message(message.message_id)
        return cls.LIST_STATE

    @classmethod
    def update_object_message(cls):
        message_id = cls.bot_context.get_object_message_id()

        radio = cls.bot_context.get_actual_object()
        keyboard = cls.get_object_keyboard()
        data_strings = cls.get_data_strings(radio)

        text = ''
        if cls.bot_context.is_edit_action():
            text = cls.edit_message_text % (radio.name, '\n'.join(data_strings))
        elif cls.bot_context.is_create_action():
            text = cls.create_message_text % ('\n'.join(data_strings),)
        text += '\n' + cls.get_status_string(radio)

        if text:
            cls.context.bot.edit_message_text(text,
                                              cls.update.effective_chat.id,
                                              message_id,
                                              parse_mode=ParseMode.MARKDOWN,
                                              disable_web_page_preview=True)

        cls.context.bot.edit_message_reply_markup(cls.update.effective_chat.id,
                                                  message_id, reply_markup=InlineKeyboardMarkup(keyboard))
