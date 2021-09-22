import re
from functools import wraps
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
from bot.services import radio_user
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
    MANAGE_QUEUE_CONTEXT = 'manage_queue'
    MANAGE_QUEUE_PAGE_CONTEXT = 'manage_queue_page'
    MANAGE_QUEUE_POINTER_CONTEXT = 'manage_queue_pointer'

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

    def set_manage_queue_pointer(self, pointer: tuple):
        if self.MANAGE_QUEUE_CONTEXT not in self.edit:
            self.edit[self.MANAGE_QUEUE_CONTEXT] = {}
        self.edit[self.MANAGE_QUEUE_CONTEXT][self.MANAGE_QUEUE_POINTER_CONTEXT] = pointer

    def get_manage_queue_pointer(self):
        if self.MANAGE_QUEUE_CONTEXT in self.edit and self.MANAGE_QUEUE_POINTER_CONTEXT in self.edit[self.MANAGE_QUEUE_CONTEXT]:
            return self.edit[self.MANAGE_QUEUE_CONTEXT][self.MANAGE_QUEUE_POINTER_CONTEXT]
        return BotLogicRadio.MANAGE_QUEUE_DEFAULT_POINTER

    def set_manage_queue_page(self, page: int):
        if self.MANAGE_QUEUE_CONTEXT not in self.edit:
            self.edit[self.MANAGE_QUEUE_CONTEXT] = {}
        self.edit[self.MANAGE_QUEUE_CONTEXT][self.MANAGE_QUEUE_PAGE_CONTEXT] = page

    def get_manage_queue_page(self):
        if self.MANAGE_QUEUE_CONTEXT in self.edit and self.MANAGE_QUEUE_PAGE_CONTEXT in self.edit[self.MANAGE_QUEUE_CONTEXT]:
            return self.edit[self.MANAGE_QUEUE_CONTEXT][self.MANAGE_QUEUE_PAGE_CONTEXT]
        return BotLogicRadio.MANAGE_QUEUE_DEFAULT_PAGE

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
    MANAGE_QUEUE_CALLBACK_STATE = r'add_to_queue'

    SET_NAME_CALLBACK_DATA = r'set_name'
    SET_TITLE_TEMPLATE_CALLBACK_DATA = r'set_title_template'
    MANAGE_QUEUE_CALLBACK_DATA = r'add_to_queue'
    BACK_CALLBACK_DATA = r'back'
    BACK_FROM_MANAGE_QUEUE_CALLBACK_DATA = r'back_from_add_to_queue'
    EDIT_BACK_CALLBACK_DATA = r'edit_back'
    SAVE_CALLBACK_DATA = r'save'
    CREATE_CALLBACK_DATA = r'create'
    EDIT_CALLBACK_DATA = r'edit_%s'
    EDIT_CALLBACK_DATA_PATTERN = r'edit_(\d+)'

    create_message_text = _('To create new object select field and set data.\nData:\n%s')
    edit_message_text = _('It\'s your radio *%s*.\n%s\nSelect some action.')
    list_message_text = _('Here is your radios. Select one to manage:')
    add_to_queue_message_text = _('Upload or forward audio files here to add them to queue.\nYour actual queue:\n%s')

    MANAGE_QUEUE_ITEMS_ON_PAGE = 20
    MANAGE_QUEUE_DEFAULT_PAGE = 0
    MANAGE_QUEUE_DEFAULT_POINTER = (0, 0,)

    UNSELECT_DOWN_CALLBACK_DATA = 'UNSELECT_DOWN'
    SELECT_DOWN_CALLBACK_DATA = 'SELECT_DOWN'
    UNSELECT_UP_CALLBACK_DATA = 'UNSELECT_UP'
    SELECT_UP_CALLBACK_DATA = 'SELECT_UP'
    DESELECT_CALLBACK_DATA = 'DESELECT'
    MOVE_POINTER_DOWN_CALLBACK_DATA = 'MOVE_POINTER_DOWN'
    MOVE_POINTER_UP_CALLBACK_DATA = 'MOVE_POINTER_UP'

    @classmethod
    def get_conversation_handler(cls) -> ConversationHandler:
        from bot.bot_logic.main import BotLogicMain
        list_handler = CallbackQueryHandler(cls.show_list_action, pattern=BotLogicMain.RADIO_CALLBACK_DATA)
        create_handler = CallbackQueryHandler(cls.create_action, pattern=cls.CREATE_CALLBACK_DATA)
        edit_handler = CallbackQueryHandler(cls.edit_action, pattern=cls.EDIT_CALLBACK_DATA_PATTERN)
        conversation_handler = ConversationHandler(
            entry_points=[list_handler],
            states={
                cls.LIST_STATE: [list_handler, create_handler, edit_handler],
                cls.SET_FIELDS_STATE: [
                    CallbackQueryHandler(cls.set_name_start_action, pattern=cls.SET_NAME_CALLBACK_DATA),
                    CallbackQueryHandler(cls.set_title_template_start_action, pattern=cls.SET_TITLE_TEMPLATE_CALLBACK_DATA),
                    CallbackQueryHandler(cls.save_action, pattern=cls.SAVE_CALLBACK_DATA),
                    CallbackQueryHandler(cls.edit_back_action, pattern=cls.EDIT_BACK_CALLBACK_DATA),
                    CallbackQueryHandler(cls.manage_queue_action, pattern=cls.MANAGE_QUEUE_CALLBACK_DATA),
                ],
                cls.MANAGE_QUEUE_CALLBACK_STATE: [
                    CallbackQueryHandler(cls.back_from_add_to_queue_action, pattern=cls.BACK_FROM_MANAGE_QUEUE_CALLBACK_DATA),
                    CallbackQueryHandler(cls.unselect_down_action, pattern=cls.UNSELECT_DOWN_CALLBACK_DATA),
                    CallbackQueryHandler(cls.select_down_action, pattern=cls.SELECT_DOWN_CALLBACK_DATA),
                    CallbackQueryHandler(cls.unselect_up_action, pattern=cls.UNSELECT_UP_CALLBACK_DATA),
                    CallbackQueryHandler(cls.select_up_action, pattern=cls.SELECT_UP_CALLBACK_DATA),
                    CallbackQueryHandler(cls.deselect_action, pattern=cls.DESELECT_CALLBACK_DATA),
                    CallbackQueryHandler(cls.move_pointer_down_action, pattern=cls.MOVE_POINTER_DOWN_CALLBACK_DATA),
                    CallbackQueryHandler(cls.move_pointer_up_action, pattern=cls.MOVE_POINTER_UP_CALLBACK_DATA),
                    MessageHandler(Filters.all, cls.add_to_queue_upload_action),
                ],
                cls.SET_FIELDS_TEXT_STATE: [MessageHandler(Filters.text, cls.set_fields_text_action)]
            },
            fallbacks=[
                CallbackQueryHandler(cls.back_action, pattern=cls.BACK_CALLBACK_DATA),
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
    def edit_back_action(cls, update: Update, context: CallbackContext):
        cls.bot_context.clear_after_save()
        context.bot.answer_callback_query(update.callback_query.id, _('Back! Changes was cleared.'))
        return cls.LIST_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def back_action(cls, update: Update, context: CallbackContext):
        cls.bot_context.delete_list_message()
        return cls.BACK_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def back_from_add_to_queue_action(cls, update: Update, context: CallbackContext):
        cls.bot_context.delete_queue_messages()
        cls.bot_context.set_edit_action()
        cls.bot_context.set_manage_queue_pointer((0, 0,))
        return cls.SET_FIELDS_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def unselect_down_action(cls, update: Update, context: CallbackContext):
        (pointer_start, pointer_end) = cls.bot_context.get_manage_queue_pointer()
        if pointer_end != pointer_start:
            pointer_end -= 1
            cls.bot_context.set_manage_queue_pointer((pointer_start, pointer_end,))
            cls.update_queue_message()

        return cls.MANAGE_QUEUE_CALLBACK_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def select_down_action(cls, update: Update, context: CallbackContext):
        (pointer_start, pointer_end) = cls.bot_context.get_manage_queue_pointer()
        if pointer_end + 1 <= cls.MANAGE_QUEUE_ITEMS_ON_PAGE:
            pointer_end += 1
            cls.bot_context.set_manage_queue_pointer((pointer_start, pointer_end,))
            cls.update_queue_message()

        return cls.MANAGE_QUEUE_CALLBACK_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def unselect_up_action(cls, update: Update, context: CallbackContext):
        (pointer_start, pointer_end) = cls.bot_context.get_manage_queue_pointer()
        if pointer_start != pointer_end:
            pointer_start += 1
            cls.bot_context.set_manage_queue_pointer((pointer_start, pointer_end,))
            cls.update_queue_message()

        return cls.MANAGE_QUEUE_CALLBACK_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def select_up_action(cls, update: Update, context: CallbackContext):
        (pointer_start, pointer_end) = cls.bot_context.get_manage_queue_pointer()
        if pointer_start - 1 >= 0:
            pointer_start -= 1
            cls.bot_context.set_manage_queue_pointer((pointer_start, pointer_end,))
            cls.update_queue_message()

        return cls.MANAGE_QUEUE_CALLBACK_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def deselect_action(cls, update: Update, context: CallbackContext):
        (pointer_start, pointer_end) = cls.bot_context.get_manage_queue_pointer()
        pointer_end = pointer_start
        cls.bot_context.set_manage_queue_pointer((pointer_start, pointer_end,))
        cls.update_queue_message()

        return cls.MANAGE_QUEUE_CALLBACK_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def move_pointer_down_action(cls, update: Update, context: CallbackContext):
        (pointer_start, pointer_end) = cls.bot_context.get_manage_queue_pointer()
        if pointer_start + 1 <= cls.MANAGE_QUEUE_ITEMS_ON_PAGE:
            pointer_start += 1
            pointer_end = pointer_start
            cls.bot_context.set_manage_queue_pointer((pointer_start, pointer_end,))
            cls.update_queue_message()

        return cls.MANAGE_QUEUE_CALLBACK_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def move_pointer_up_action(cls, update: Update, context: CallbackContext):
        (pointer_start, pointer_end) = cls.bot_context.get_manage_queue_pointer()
        if pointer_start - 1 >= 0:
            pointer_start -= 1
            pointer_end = pointer_start
            cls.bot_context.set_manage_queue_pointer((pointer_start, pointer_end,))
            cls.update_queue_message()

        return cls.MANAGE_QUEUE_CALLBACK_STATE

    @classmethod
    def get_queue_keyboard(cls):
        keyboard = []

        (pointer_start, pointer_end) = cls.bot_context.get_manage_queue_pointer()

        move_pointer_line = []
        if pointer_start == pointer_end:
            if pointer_start > 0:
                move_pointer_line.append(
                    InlineKeyboardButton(
                        _('↑'),
                        callback_data=cls.MOVE_POINTER_UP_CALLBACK_DATA),
                )
            if pointer_end < cls.MANAGE_QUEUE_ITEMS_ON_PAGE - 1:
                move_pointer_line.append(
                    InlineKeyboardButton(
                        _('↓'),
                        callback_data=cls.MOVE_POINTER_DOWN_CALLBACK_DATA),
                )
        else:
            move_pointer_line.append(
                InlineKeyboardButton(
                    _('Deselect'),
                    callback_data=cls.DESELECT_CALLBACK_DATA),
            )

        keyboard.append(move_pointer_line)

        select_line = []
        if pointer_start > 0 or pointer_start != pointer_end:
            if pointer_start != pointer_end:
                select_line.append(
                    InlineKeyboardButton(
                        _('⇣'),
                        callback_data=cls.UNSELECT_UP_CALLBACK_DATA),
                )
            if pointer_start > 0:
                select_line.append(
                    InlineKeyboardButton(
                        _('↥'),
                        callback_data=cls.SELECT_UP_CALLBACK_DATA),
                )
        if pointer_end < cls.MANAGE_QUEUE_ITEMS_ON_PAGE - 1 or pointer_start != pointer_end:
            if pointer_end < cls.MANAGE_QUEUE_ITEMS_ON_PAGE - 1:
                select_line.append(
                    InlineKeyboardButton(
                        _('↧'),
                        callback_data=cls.SELECT_DOWN_CALLBACK_DATA),
                )
            if pointer_start != pointer_end:
                select_line.append(
                    InlineKeyboardButton(
                        _('⇡'),
                        callback_data=cls.UNSELECT_DOWN_CALLBACK_DATA),
                )

        keyboard.append(select_line)

        keyboard.append([
            InlineKeyboardButton(
                _('Back'),
                callback_data=cls.BACK_FROM_MANAGE_QUEUE_CALLBACK_DATA),
        ])

        return keyboard

    @classmethod
    def get_queue_message_text(cls):
        page = cls.bot_context.get_manage_queue_page()
        (pointer_start, pointer_end,) = cls.bot_context.get_manage_queue_pointer()
        queues = get_radio_queue(cls.bot_context.get_actual_object(),
                                 page=page,
                                 page_size=cls.MANAGE_QUEUE_ITEMS_ON_PAGE)

        queue_list = []
        index = 0
        for queue in queues:
            audio_file: AudioFile = queue.audio_file

            if pointer_start <= index <= pointer_end:
                title = '*%s*' % (audio_file.get_full_title(),)
            else:
                title = audio_file.get_full_title()
            queue_list.append(title)
            index += 1

        queue_list_str = '\n'.join(queue_list)
        return cls.add_to_queue_message_text % (queue_list_str if queue_list_str else '[[empty]]',)

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def add_to_queue_upload_action(cls, update: Update, context: CallbackContext):
        message: Message = update.message
        if message.audio is not None:
            result = radio_user.add_file_to_queue(message.audio, cls.bot_context.get_actual_object())
            if result:
                message = context.bot.send_message(
                    update.effective_chat.id,
                    text=_('Thanks, file is added, you can continue or press Back.'),
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup(cls.get_queue_keyboard())
                )
            else:
                message = context.bot.send_message(
                    update.effective_chat.id,
                    text=_('There is internal error, please try again.'),
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup(cls.get_queue_keyboard())
                )
            cls.bot_context.add_queue_message_to_delete(message.message_id)
            cls.update_queue_message()
        return cls.MANAGE_QUEUE_CALLBACK_STATE

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
    def manage_queue_action(cls, update: Update, context: CallbackContext):
        cls.bot_context.set_add_to_queue_action()

        message = context.bot.send_message(
            update.effective_chat.id,
            text=cls.get_queue_message_text(),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(cls.get_queue_keyboard())
        )

        cls.bot_context.add_queue_message_to_delete(message.message_id)
        cls.bot_context.set_queue_message_id(message.message_id)

        return cls.MANAGE_QUEUE_CALLBACK_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def save_action(cls, update: Update, context: CallbackContext):
        context.bot.answer_callback_query(update.callback_query.id)
        radio = cls.bot_context.get_actual_object()
        radio_user = None

        if not hasattr(radio, 'telegram_account'):
            telegram_user = TelegramUser.objects.get(uid=update.effective_user.id)
            if not telegram_user:
                user = User.objects.create_action()
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
    def create_action(cls, update: Update, context: CallbackContext):
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

        if errors:
            return _('Status: Need to Set Up\nProblems:\n%s') % ('\n'.join(errors),)
        return ''

    @classmethod
    def get_data_strings(cls, radio):
        data_strings = [_('Name**: %s') % (radio.name if radio.name else r'—',),
                        _('Title Template: %s') % (radio.title_template if radio.title_template else r'—',)]
        return data_strings

    @classmethod
    def get_object_keyboard(cls):
        radio = cls.bot_context.get_actual_object()
        if radio.name:
            set_name_text = _('Change name')
        else:
            set_name_text = _('Add name')

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

        google_table_row = []

        if cls.bot_context.is_edit_action():
            google_table_row.append(
                InlineKeyboardButton(
                    _('Manage Queue'),
                    callback_data=cls.MANAGE_QUEUE_CALLBACK_DATA),
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
    @handlers_wrapper
    @BotContextRadio.wrapper
    def set_fields_text_action(cls, update: Update, context: CallbackContext):
        field = cls.bot_context.get_actual_field()
        radio = cls.bot_context.get_actual_object()

        valid = True

        if valid:
            setattr(radio, field, update.message.text)
            cls.update_object_message()

        return cls.SET_FIELDS_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def set_name_start_action(cls, update: Update, context: CallbackContext):
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
    def set_title_template_start_action(cls, update: Update, context: CallbackContext):
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
    def edit_action(cls, update: Update, context: CallbackContext):
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
    def show_list_action(cls, update: Update, context: CallbackContext):
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
