import re
from math import ceil
from django.core.exceptions import ValidationError
from django.db import transaction
from telegram import Update, ParseMode, InlineKeyboardMarkup, InlineKeyboardButton, Message
from telegram.error import BadRequest
from telegram.ext import ConversationHandler, CallbackQueryHandler, CallbackContext, MessageHandler, Filters
from django.utils.translation import ugettext as _
from bot.bot_logic.bot_logic import BotLogic, BotContext
from bot.helpers import handlers_wrapper, create_user
from bot.models import Radio, TelegramUser, UserToRadio, AudioFile, Queue, BroadcastUser
from bot.services import radio_user
from bot.services.broadcast_user import get_owned_broadcasters
from bot.services.radio_user import get_radio_queue, delete_queue_item, move_up_queue_item, move_down_queue_item, \
    count_of_queue_items


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
    MANAGE_QUEUE_ACTUAL_ITEMS_ON_PAGE_CONTEXT = 'manage_queue_actual_items_on_page'

    EDIT_ACTION = 'edit'
    CREATE_ACTION = 'create'
    ADD_TO_QUEUE_ACTION = 'add_to_queue'

    def __init__(self, bot_logic: BotLogic):
        super().__init__(bot_logic)

        self.edit = None
        self.radio_object = None
        self.new_object = None
        self.actual_field = None
        self.object_message = None

        self.init_edit_context()

    def init_edit_context(self):
        if self.EDIT_CONTEXT not in self.context:
            self.context[self.EDIT_CONTEXT] = {}
        self.edit = self.context[self.EDIT_CONTEXT]

    def set_manage_queue_pointer(self, pointer: tuple):
        if self.MANAGE_QUEUE_CONTEXT not in self.edit:
            self.edit[self.MANAGE_QUEUE_CONTEXT] = {}
        self.edit[self.MANAGE_QUEUE_CONTEXT][self.MANAGE_QUEUE_POINTER_CONTEXT] = pointer

    def get_manage_queue_pointer(self):
        if self.MANAGE_QUEUE_CONTEXT in self.edit and self.MANAGE_QUEUE_POINTER_CONTEXT in self.edit[
            self.MANAGE_QUEUE_CONTEXT]:
            return self.edit[self.MANAGE_QUEUE_CONTEXT][self.MANAGE_QUEUE_POINTER_CONTEXT]
        return BotLogicRadio.MANAGE_QUEUE_DEFAULT_POINTER

    def set_manage_queue_page(self, page: int):
        if self.MANAGE_QUEUE_CONTEXT not in self.edit:
            self.edit[self.MANAGE_QUEUE_CONTEXT] = {}
        self.edit[self.MANAGE_QUEUE_CONTEXT][self.MANAGE_QUEUE_PAGE_CONTEXT] = page

    def get_manage_queue_page(self):
        if self.MANAGE_QUEUE_CONTEXT in self.edit and self.MANAGE_QUEUE_PAGE_CONTEXT in self.edit[
            self.MANAGE_QUEUE_CONTEXT]:
            return self.edit[self.MANAGE_QUEUE_CONTEXT][self.MANAGE_QUEUE_PAGE_CONTEXT]
        return BotLogicRadio.MANAGE_QUEUE_DEFAULT_PAGE

    def set_manage_queue_actual_items_on_page(self, items_count: int):
        if self.MANAGE_QUEUE_CONTEXT not in self.edit:
            self.edit[self.MANAGE_QUEUE_CONTEXT] = {}
        self.edit[self.MANAGE_QUEUE_CONTEXT][self.MANAGE_QUEUE_ACTUAL_ITEMS_ON_PAGE_CONTEXT] = items_count

    def get_manage_queue_actual_items_on_page(self):
        if self.MANAGE_QUEUE_CONTEXT in self.edit and self.MANAGE_QUEUE_ACTUAL_ITEMS_ON_PAGE_CONTEXT in self.edit[
            self.MANAGE_QUEUE_CONTEXT]:
            return self.edit[self.MANAGE_QUEUE_CONTEXT][self.MANAGE_QUEUE_ACTUAL_ITEMS_ON_PAGE_CONTEXT]

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
        self.context[self.ACTION_CONTEXT] = self.EDIT_ACTION

    def set_create_action(self):
        self.context[self.ACTION_CONTEXT] = self.CREATE_ACTION

    def set_add_to_queue_action(self):
        self.context[self.ACTION_CONTEXT] = self.ADD_TO_QUEUE_ACTION

    def get_action(self):
        return self.context[self.ACTION_CONTEXT]

    def is_edit_action(self):
        return self.context[self.ACTION_CONTEXT] is self.EDIT_ACTION

    def is_create_action(self):
        return self.context[self.ACTION_CONTEXT] is self.CREATE_ACTION

    def init_new_object(self):
        self.context[self.NEW_OBJECT_CONTEXT] = Radio()
        return self.context[self.NEW_OBJECT_CONTEXT]

    def get_new_object(self):
        if self.NEW_OBJECT_CONTEXT not in self.context:
            self.context[self.NEW_OBJECT_CONTEXT] = Radio()
        return self.context[self.NEW_OBJECT_CONTEXT]

    def get_actual_object(self) -> Radio:
        action = self.get_action()
        if action in [self.EDIT_ACTION, self.ADD_TO_QUEUE_ACTION]:
            return self.get_edited_object()
        elif action is self.CREATE_ACTION:
            return self.get_new_object()

    def has_actual_object(self):
        if self.get_actual_object():
            return True
        return False

    def set_actual_field(self, field_name):
        self.context[self.ACTUAL_FIELD_CONTEXT] = field_name

    def get_actual_field(self):
        return self.context[self.ACTUAL_FIELD_CONTEXT]

    def set_queue_message_id(self, message_id):
        self.context[self.QUEUE_MESSAGE_CONTEXT] = message_id

    def get_queue_message_id(self):
        return self.context[self.QUEUE_MESSAGE_CONTEXT]

    def add_queue_message_to_delete(self, message_id):
        if self.QUEUE_MESSAGES_TO_DELETE_CONTEXT not in self.context:
            self.context[self.QUEUE_MESSAGES_TO_DELETE_CONTEXT] = []
        self.context[self.QUEUE_MESSAGES_TO_DELETE_CONTEXT].append(message_id)

    def delete_queue_messages(self):
        for message_id in self.context[self.QUEUE_MESSAGES_TO_DELETE_CONTEXT]:
            try:
                self.bot_logic.context.bot.delete_message(self.bot_logic.update.effective_chat.id, message_id)
            except BadRequest:
                pass
        del self.context[self.QUEUE_MESSAGES_TO_DELETE_CONTEXT]

    def add_message_to_delete(self, message_id):
        if self.MESSAGES_TO_DELETE_CONTEXT not in self.context:
            self.context[self.MESSAGES_TO_DELETE_CONTEXT] = []
        self.context[self.MESSAGES_TO_DELETE_CONTEXT].append(message_id)

    def delete_list_message(self):
        if self.LIST_MESSAGE_CONTEXT in self.context:
            message_id = self.context[self.LIST_MESSAGE_CONTEXT]
            try:
                self.bot_logic.context.bot.delete_message(self.bot_logic.update.effective_chat.id, message_id)
            except BadRequest:
                pass

    def delete_messages(self):
        for message_id in self.context[self.MESSAGES_TO_DELETE_CONTEXT]:
            try:
                self.bot_logic.context.bot.delete_message(self.bot_logic.update.effective_chat.id, message_id)
            except BadRequest:
                pass
        del self.context[self.MESSAGES_TO_DELETE_CONTEXT]

    def set_list_message(self, message_id):
        self.context[self.LIST_MESSAGE_CONTEXT] = message_id

    def get_list_message(self):
        return self.context[self.LIST_MESSAGE_CONTEXT]

    def set_object_message_id(self, message_id):
        self.context[self.OBJECT_MESSAGE_CONTEXT] = message_id
        self.add_message_to_delete(message_id)

    def get_object_message_id(self):
        return self.context[self.OBJECT_MESSAGE_CONTEXT]

    def clear_after_save(self):
        self.delete_messages()
        del self.context[self.OBJECT_MESSAGE_CONTEXT]
        if self.NEW_OBJECT_CONTEXT in self.context:
            del self.context[self.NEW_OBJECT_CONTEXT]
        del self.context[self.EDIT_CONTEXT]


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
    CHOOSE_BROADCASTER_CALLBACK_STATE = r'choose_broadcaster'

    SET_NAME_CALLBACK_DATA = r'set_name'
    SET_TITLE_TEMPLATE_CALLBACK_DATA = r'set_title_template'
    SET_BROADCASTER_CALLBACK_DATA = r'set_broadcaster_%s'
    SET_BROADCASTER_CALLBACK_DATA_PATTERN = r'set_broadcaster_(\d+)'
    CHOOSE_BROADCASTER_CALLBACK_DATA = r'choose_broadcaster'
    CHOOSE_CHAT_TO_BROADCAST_CALLBACK_DATA = r'choose_chat_to_broadcast'
    CHOOSE_CHAT_TO_DOWNLOAD_CALLBACK_DATA = r'choose_chat_to_download'
    MANAGE_QUEUE_CALLBACK_DATA = r'add_to_queue'
    BACK_CALLBACK_DATA = r'back'
    BACK_FROM_MANAGE_QUEUE_CALLBACK_DATA = r'back_from_add_to_queue'
    REFRESH_QUEUE_LIST_CALLBACK_DATA = r'refresh_queue_list_callback_data'
    EDIT_BACK_CALLBACK_DATA = r'edit_back'
    SAVE_CALLBACK_DATA = r'save'
    CREATE_CALLBACK_DATA = r'create'
    EDIT_CALLBACK_DATA = r'edit_%s'
    EDIT_CALLBACK_DATA_PATTERN = r'edit_(\d+)'
    BACK_FROM_CHOOSE_BROADCASTER_CALLBACK_DATA = r'back_from_choose_broadcaster'

    create_message_text = _('To create new object select field and set data.\nData:\n%s')
    edit_message_text = _('It\'s your radio *%s*.\n%s\nSelect some action.')
    list_message_text = _('Here is your radios. Select one to manage:')
    add_to_queue_message_text = _('Upload or forward audio files here to add them to queue.\n\nYour actual queue:\n%s')

    MANAGE_QUEUE_ITEMS_ON_PAGE = 5
    MANAGE_QUEUE_DEFAULT_PAGE = 0
    MANAGE_QUEUE_DEFAULT_POINTER = (0, 0,)

    UNSELECT_DOWN_CALLBACK_DATA = 'unselect_down'
    SELECT_DOWN_CALLBACK_DATA = 'select_down'
    UNSELECT_UP_CALLBACK_DATA = 'unselect_up'
    SELECT_UP_CALLBACK_DATA = 'select_up'
    DESELECT_CALLBACK_DATA = 'deselect'
    MOVE_POINTER_DOWN_CALLBACK_DATA = 'move_pointer_down'
    MOVE_POINTER_UP_CALLBACK_DATA = 'move_pointer_up'
    MOVE_DOWN_CALLBACK_DATA = 'move_down'
    MOVE_UP_CALLBACK_DATA = 'move_up'
    DELETE_CALLBACK_DATA = 'delete'
    NEXT_PAGE_CALLBACK_DATA = 'next_page'
    PREV_PAGE_CALLBACK_DATA = 'prev_page'
    STOP_AIR_CALLBACK_DATA = 'manage_queue_stop_air'
    START_AIR_CALLBACK_DATA = 'manage_queue_start_air'

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
                    CallbackQueryHandler(cls.set_title_template_start_action,
                                         pattern=cls.SET_TITLE_TEMPLATE_CALLBACK_DATA),
                    CallbackQueryHandler(cls.save_action, pattern=cls.SAVE_CALLBACK_DATA),
                    CallbackQueryHandler(cls.edit_back_action, pattern=cls.EDIT_BACK_CALLBACK_DATA),
                    CallbackQueryHandler(cls.manage_queue_action, pattern=cls.MANAGE_QUEUE_CALLBACK_DATA),
                    CallbackQueryHandler(cls.manage_queue_stop_air_action, pattern=cls.STOP_AIR_CALLBACK_DATA),
                    CallbackQueryHandler(cls.manage_queue_start_air_action, pattern=cls.START_AIR_CALLBACK_DATA),
                    CallbackQueryHandler(cls.choose_broadcaster_action, pattern=cls.CHOOSE_BROADCASTER_CALLBACK_DATA),
                    CallbackQueryHandler(cls.choose_chat_to_broadcast_action,
                                         pattern=cls.CHOOSE_CHAT_TO_BROADCAST_CALLBACK_DATA),
                    CallbackQueryHandler(cls.choose_chat_to_download_action,
                                         pattern=cls.CHOOSE_CHAT_TO_DOWNLOAD_CALLBACK_DATA),
                ],
                cls.MANAGE_QUEUE_CALLBACK_STATE: [
                    CallbackQueryHandler(cls.back_from_add_to_queue_action,
                                         pattern=cls.BACK_FROM_MANAGE_QUEUE_CALLBACK_DATA),
                    CallbackQueryHandler(cls.unselect_down_action, pattern=cls.UNSELECT_DOWN_CALLBACK_DATA),
                    CallbackQueryHandler(cls.select_down_action, pattern=cls.SELECT_DOWN_CALLBACK_DATA),
                    CallbackQueryHandler(cls.unselect_up_action, pattern=cls.UNSELECT_UP_CALLBACK_DATA),
                    CallbackQueryHandler(cls.select_up_action, pattern=cls.SELECT_UP_CALLBACK_DATA),
                    CallbackQueryHandler(cls.deselect_action, pattern=cls.DESELECT_CALLBACK_DATA),
                    CallbackQueryHandler(cls.move_pointer_down_action, pattern=cls.MOVE_POINTER_DOWN_CALLBACK_DATA),
                    CallbackQueryHandler(cls.move_pointer_up_action, pattern=cls.MOVE_POINTER_UP_CALLBACK_DATA),
                    CallbackQueryHandler(cls.move_down_action, pattern=cls.MOVE_DOWN_CALLBACK_DATA),
                    CallbackQueryHandler(cls.move_up_action, pattern=cls.MOVE_UP_CALLBACK_DATA),
                    CallbackQueryHandler(cls.delete_action, pattern=cls.DELETE_CALLBACK_DATA),
                    CallbackQueryHandler(cls.prev_page_action, pattern=cls.PREV_PAGE_CALLBACK_DATA),
                    CallbackQueryHandler(cls.next_page_action, pattern=cls.NEXT_PAGE_CALLBACK_DATA),
                    CallbackQueryHandler(cls.refresh_queue_list_action, pattern=cls.REFRESH_QUEUE_LIST_CALLBACK_DATA),
                    MessageHandler(Filters.all, cls.add_to_queue_upload_action),
                ],
                cls.CHOOSE_BROADCASTER_CALLBACK_STATE: [
                    CallbackQueryHandler(cls.set_broadcaster_action, pattern=cls.SET_BROADCASTER_CALLBACK_DATA_PATTERN),
                    CallbackQueryHandler(cls.back_from_choose_broadcaster_action,
                                         pattern=cls.BACK_FROM_CHOOSE_BROADCASTER_CALLBACK_DATA),
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

        context.bot.answer_callback_query(update.callback_query.id)
        return cls.LIST_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def back_action(cls, update: Update, context: CallbackContext):
        cls.bot_context.delete_list_message()

        context.bot.answer_callback_query(update.callback_query.id)
        return cls.BACK_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def back_from_choose_broadcaster_action(cls, update: Update, context: CallbackContext):
        cls.bot_context.delete_list_message()

        context.bot.answer_callback_query(update.callback_query.id)
        return cls.SET_FIELDS_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def back_from_add_to_queue_action(cls, update: Update, context: CallbackContext):
        cls.bot_context.delete_queue_messages()
        cls.bot_context.set_edit_action()
        cls.bot_context.set_manage_queue_pointer((0, 0,))

        context.bot.answer_callback_query(update.callback_query.id)
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

        context.bot.answer_callback_query(update.callback_query.id)
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

        context.bot.answer_callback_query(update.callback_query.id)
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

        context.bot.answer_callback_query(update.callback_query.id)
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

        context.bot.answer_callback_query(update.callback_query.id)
        return cls.MANAGE_QUEUE_CALLBACK_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def deselect_action(cls, update: Update, context: CallbackContext):
        (pointer_start, pointer_end) = cls.bot_context.get_manage_queue_pointer()
        pointer_end = pointer_start
        cls.bot_context.set_manage_queue_pointer((pointer_start, pointer_end,))
        cls.update_queue_message()

        context.bot.answer_callback_query(update.callback_query.id)
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

        context.bot.answer_callback_query(update.callback_query.id)
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

        context.bot.answer_callback_query(update.callback_query.id)
        return cls.MANAGE_QUEUE_CALLBACK_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def move_down_action(cls, update: Update, context: CallbackContext):
        (pointer_start, pointer_end) = cls.bot_context.get_manage_queue_pointer()
        page = cls.bot_context.get_manage_queue_page()

        queues = get_radio_queue(cls.bot_context.get_actual_object(),
                                 page=page,
                                 page_size=cls.MANAGE_QUEUE_ITEMS_ON_PAGE)

        item = list(queues)[pointer_start]
        cls.bot_context.set_manage_queue_pointer((pointer_start + 1, pointer_end + 1))
        move_down_queue_item(item)
        cls.update_queue_message()

        context.bot.answer_callback_query(update.callback_query.id)
        return cls.MANAGE_QUEUE_CALLBACK_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def move_up_action(cls, update: Update, context: CallbackContext):
        (pointer_start, pointer_end) = cls.bot_context.get_manage_queue_pointer()
        page = cls.bot_context.get_manage_queue_page()

        queues = get_radio_queue(cls.bot_context.get_actual_object(),
                                 page=page,
                                 page_size=cls.MANAGE_QUEUE_ITEMS_ON_PAGE)

        item = list(queues)[pointer_start]
        cls.bot_context.set_manage_queue_pointer((pointer_start - 1, pointer_end - 1))
        move_up_queue_item(item)
        cls.update_queue_message()

        context.bot.answer_callback_query(update.callback_query.id)
        return cls.MANAGE_QUEUE_CALLBACK_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def delete_action(cls, update: Update, context: CallbackContext):
        (pointer_start, pointer_end) = cls.bot_context.get_manage_queue_pointer()
        page = cls.bot_context.get_manage_queue_page()

        queues = get_radio_queue(cls.bot_context.get_actual_object(),
                                 page=page,
                                 page_size=cls.MANAGE_QUEUE_ITEMS_ON_PAGE)

        items = queues[pointer_start:pointer_end + 1]
        item: Queue
        for item in items:
            delete_queue_item(item)
        cls.update_queue_message()

        context.bot.answer_callback_query(update.callback_query.id)
        return cls.MANAGE_QUEUE_CALLBACK_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def next_page_action(cls, update: Update, context: CallbackContext):
        page = cls.bot_context.get_manage_queue_page()
        cls.bot_context.set_manage_queue_page(page + 1)
        cls.update_queue_message()

        context.bot.answer_callback_query(update.callback_query.id)
        return cls.MANAGE_QUEUE_CALLBACK_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def prev_page_action(cls, update: Update, context: CallbackContext):
        page = cls.bot_context.get_manage_queue_page()
        cls.bot_context.set_manage_queue_page(page - 1)
        cls.update_queue_message()

        context.bot.answer_callback_query(update.callback_query.id)
        return cls.MANAGE_QUEUE_CALLBACK_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def refresh_queue_list_action(cls, update: Update, context: CallbackContext):
        cls.update_queue_message()

        context.bot.answer_callback_query(update.callback_query.id)
        return cls.MANAGE_QUEUE_CALLBACK_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def manage_queue_stop_air_action(cls, update: Update, context: CallbackContext):
        radio = cls.bot_context.get_actual_object()
        radio.status = Radio.STATUS_ASKING_FOR_STOP_BROADCAST
        radio.save()
        cls.update_object_message()

        context.bot.answer_callback_query(update.callback_query.id)
        return cls.SET_FIELDS_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def manage_queue_start_air_action(cls, update: Update, context: CallbackContext):
        radio = cls.bot_context.get_actual_object()
        radio.status = Radio.STATUS_ASKING_FOR_BROADCAST
        radio.save()
        cls.update_object_message()

        context.bot.answer_callback_query(update.callback_query.id)
        return cls.SET_FIELDS_STATE

    @classmethod
    def get_queue_keyboard(cls):
        keyboard = []

        (pointer_start, pointer_end) = cls.bot_context.get_manage_queue_pointer()
        is_selected_few_items = pointer_start != pointer_end
        pointer_is_not_on_top = pointer_start > 0
        is_selected_one_item = pointer_start == pointer_end

        # move line
        move_pointer_line = []
        if cls.bot_context.get_manage_queue_actual_items_on_page() != cls.MANAGE_QUEUE_ITEMS_ON_PAGE:
            last_element_on_page = cls.bot_context.get_manage_queue_actual_items_on_page() - 1
        else:
            last_element_on_page = cls.MANAGE_QUEUE_ITEMS_ON_PAGE - 1
        pointer_is_not_on_bottom = pointer_end < last_element_on_page

        if is_selected_one_item:
            if pointer_is_not_on_top or pointer_is_not_on_bottom:
                keyboard.append([
                    InlineKeyboardButton(
                        _('Move pointer:'),
                        callback_data='blank'
                    )
                ])
            if pointer_is_not_on_top:
                move_pointer_line.append(
                    InlineKeyboardButton(
                        _('↑'),
                        callback_data=cls.MOVE_POINTER_UP_CALLBACK_DATA),
                )
            if pointer_is_not_on_bottom:
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

        # select line
        select_line = []
        if pointer_is_not_on_top or is_selected_few_items or pointer_is_not_on_bottom:
            keyboard.append([
                InlineKeyboardButton(
                    _('Select items:'),
                    callback_data='blank'
                )
            ])
        if pointer_is_not_on_top or is_selected_few_items:
            if is_selected_few_items:
                select_line.append(
                    InlineKeyboardButton(
                        _('⇣'),
                        callback_data=cls.UNSELECT_UP_CALLBACK_DATA),
                )
            if pointer_is_not_on_top:
                select_line.append(
                    InlineKeyboardButton(
                        _('↥'),
                        callback_data=cls.SELECT_UP_CALLBACK_DATA),
                )
        if pointer_is_not_on_bottom or is_selected_few_items:
            if pointer_is_not_on_bottom:
                select_line.append(
                    InlineKeyboardButton(
                        _('↧'),
                        callback_data=cls.SELECT_DOWN_CALLBACK_DATA),
                )
            if is_selected_few_items:
                select_line.append(
                    InlineKeyboardButton(
                        _('⇡'),
                        callback_data=cls.UNSELECT_DOWN_CALLBACK_DATA),
                )

        keyboard.append(select_line)

        # actions
        actions = []
        actions.append(
            InlineKeyboardButton(
                _('Delete'),
                callback_data=cls.DELETE_CALLBACK_DATA),
        )
        if is_selected_one_item:
            if pointer_is_not_on_top:
                actions.append(
                    InlineKeyboardButton(
                        _('Move Up'),
                        callback_data=cls.MOVE_UP_CALLBACK_DATA),
                )
            if pointer_is_not_on_bottom:
                actions.append(
                    InlineKeyboardButton(
                        _('Move Down'),
                        callback_data=cls.MOVE_DOWN_CALLBACK_DATA),
                )
        keyboard.append(actions)

        # page actions
        pages = []
        page = cls.bot_context.get_manage_queue_page()
        if page > BotLogicRadio.MANAGE_QUEUE_DEFAULT_PAGE:
            pages.append(
                InlineKeyboardButton(
                    _('<<'),
                    callback_data=cls.PREV_PAGE_CALLBACK_DATA),
            )

        total_in_queue = count_of_queue_items(cls.bot_context.get_actual_object())
        pages_float = total_in_queue / cls.MANAGE_QUEUE_ITEMS_ON_PAGE
        if page > BotLogicRadio.MANAGE_QUEUE_DEFAULT_PAGE or (pages_float) > 1:
            pages.append(
                InlineKeyboardButton(
                    _('%s') % (page + 1,),
                    callback_data='blank'),
            )

        if pages_float > 1 and page < ceil(pages_float) - 1:
            pages.append(
                InlineKeyboardButton(
                    _('>>'),
                    callback_data=cls.NEXT_PAGE_CALLBACK_DATA),
            )

        if len(pages):
            keyboard.append(pages)

        keyboard.append([
            InlineKeyboardButton(
                _('Back'),
                callback_data=cls.BACK_FROM_MANAGE_QUEUE_CALLBACK_DATA),
        ])

        keyboard.append([
            InlineKeyboardButton(
                _('\U0001F504'),
                callback_data=cls.REFRESH_QUEUE_LIST_CALLBACK_DATA),
        ])

        return keyboard

    @classmethod
    def get_queue_message_text(cls):
        page = cls.bot_context.get_manage_queue_page()
        (pointer_start, pointer_end,) = cls.bot_context.get_manage_queue_pointer()
        queues = get_radio_queue(cls.bot_context.get_actual_object(),
                                 page=page,
                                 page_size=cls.MANAGE_QUEUE_ITEMS_ON_PAGE)
        cls.bot_context.set_manage_queue_actual_items_on_page(len(queues))
        queue_list = []
        index = 0
        for queue in queues:
            audio_file: AudioFile = queue.audio_file

            if queue.status == Queue.STATUS_PROCESSING:
                full_title = '[%s-%s] [%s] %s' % (queue.id, queue.sort, _('Processing...'), audio_file.get_full_title())
            else:
                full_title = '%s' % (audio_file.get_full_title(),)
                full_title = '[%s-%s] %s' % (queue.id, queue.sort, audio_file.get_full_title(),)  # todo: delete
            if pointer_start <= index <= pointer_end:
                title = '*%s*' % (full_title,)
            else:
                title = full_title
            queue_list.append(title)
            index += 1

        queue_list_str = '\n'.join(queue_list)
        return cls.add_to_queue_message_text % (queue_list_str if queue_list_str else '[[empty]]',)

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def add_to_queue_upload_action(cls, update: Update, context: CallbackContext):
        message: Message = update.message
        # todo: find audio file in replay message
        if message.audio is not None:
            result = radio_user.add_audio_file_to_queue(message.audio, cls.bot_context.get_actual_object())
            if result:
                message = context.bot.send_message(
                    update.effective_chat.id,
                    text=_('Thanks, audio file is added, you can continue or press Back.'),
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                message = context.bot.send_message(
                    update.effective_chat.id,
                    text=_('There is internal error, please try again.'),
                    parse_mode=ParseMode.MARKDOWN
                )
            cls.bot_context.add_queue_message_to_delete(message.message_id)
            cls.update_queue_message()
        elif message.voice is not None:
            result = radio_user.add_voice_to_queue(message.voice, message.from_user, message.date,
                                                   cls.bot_context.get_actual_object())
            if result:
                message = context.bot.send_message(
                    update.effective_chat.id,
                    text=_('Thanks, voice is added, you can continue or press Back.'),
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                message = context.bot.send_message(
                    update.effective_chat.id,
                    text=_('There is internal error, please try again.'),
                    parse_mode=ParseMode.MARKDOWN
                )
            cls.bot_context.add_queue_message_to_delete(message.message_id)
            cls.update_queue_message()

        return cls.MANAGE_QUEUE_CALLBACK_STATE

    @classmethod
    def update_queue_message(cls):
        message_id = cls.bot_context.get_queue_message_id()
        try:
            cls.context.bot.edit_message_text(cls.get_queue_message_text(),
                                              cls.update.effective_chat.id,
                                              message_id,
                                              parse_mode=ParseMode.MARKDOWN,
                                              reply_markup=InlineKeyboardMarkup(cls.get_queue_keyboard())
                                              )
        except BadRequest as e:
            pass

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def manage_queue_action(cls, update: Update, context: CallbackContext):
        cls.bot_context.set_add_to_queue_action()
        cls.bot_context.set_manage_queue_pointer((0, 0))

        message = context.bot.send_message(
            update.effective_chat.id,
            text=cls.get_queue_message_text(),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(cls.get_queue_keyboard())
        )

        cls.bot_context.add_queue_message_to_delete(message.message_id)
        cls.bot_context.set_queue_message_id(message.message_id)

        context.bot.answer_callback_query(update.callback_query.id)
        return cls.MANAGE_QUEUE_CALLBACK_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def save_action(cls, update: Update, context: CallbackContext):
        radio = cls.bot_context.get_actual_object()
        radio_user = None

        if not hasattr(radio, 'telegram_account'):
            try:
                telegram_user = TelegramUser.objects.get(uid=update.effective_user.id)
            except TelegramUser.DoesNotExist:
                with transaction.atomic():
                    user = create_user(update.effective_user.username)
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

                context.bot.answer_callback_query(update.callback_query.id)
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

            context.bot.answer_callback_query(update.callback_query.id)
            return cls.LIST_STATE
        else:
            message = context.bot.send_message(
                update.effective_chat.id,
                text=_('Internal error. Please restart!'),
                parse_mode=ParseMode.MARKDOWN
            )
            cls.bot_context.add_message_to_delete(message.message_id)

            context.bot.answer_callback_query(update.callback_query.id)
            return ConversationHandler.END

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def create_action(cls, update: Update, context: CallbackContext):
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

        context.bot.answer_callback_query(update.callback_query.id)
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
        data_strings = [
            _('Name**: *%s*') % (radio.name if radio.name else r'—',),
            _('Title Template: *%s*') % (radio.title_template if radio.title_template else r'—',),
            _('Broadcaster: *%s*') % (radio.broadcast_user.uid if radio.broadcast_user else r'—',),
            _('Group/channel: *%s*') % (radio.chat_id if radio.chat_id else r'—',),
            _('Download chat: *%s*') % (radio.download_chat_id if radio.download_chat_id else r'—',),
        ]

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

        manage_queue_row = []
        if cls.bot_context.is_edit_action():
            manage_queue_row.append(
                InlineKeyboardButton(
                    _('Manage Queue'),
                    callback_data=cls.MANAGE_QUEUE_CALLBACK_DATA),
            )
        if len(manage_queue_row):
            keyboard.append(manage_queue_row)

        on_air_row = []
        if cls.bot_context.is_edit_action():
            if radio.status == Radio.STATUS_NOT_ON_AIR:
                on_air_row.append(
                    InlineKeyboardButton(
                        _('Start On-Air'),
                        callback_data=cls.START_AIR_CALLBACK_DATA),
                )
            elif radio.status == Radio.STATUS_ON_AIR:
                on_air_row.append(
                    InlineKeyboardButton(
                        _('%s On-Air (Stop)') % ("\U0001F534",),
                        callback_data=cls.STOP_AIR_CALLBACK_DATA),
                )
            elif radio.status == Radio.STATUS_ASKING_FOR_BROADCAST:
                on_air_row.append(
                    InlineKeyboardButton(
                        _('%s On-Air') % ("\U0001F7E0",),
                        callback_data='blank'),
                )
            elif radio.status == Radio.STATUS_ASKING_FOR_STOP_BROADCAST:
                on_air_row.append(
                    InlineKeyboardButton(
                        _('Stopping...'),
                        callback_data='blank'),
                )
        if len(on_air_row):
            keyboard.append(on_air_row)

        keyboard.append([
            InlineKeyboardButton(
                _('Choose Broadcaster'),
                callback_data=cls.CHOOSE_BROADCASTER_CALLBACK_DATA),
        ])

        if cls.bot_context.is_edit_action():
            if radio.broadcast_user.status == BroadcastUser.STATUS_IS_AUTH:
                keyboard.append([
                    InlineKeyboardButton(
                        _('Choose group/channel'),
                        callback_data=cls.CHOOSE_CHAT_TO_BROADCAST_CALLBACK_DATA),
                ])
                keyboard.append([
                    InlineKeyboardButton(
                        _('Choose group/channel to download'),
                        callback_data=cls.CHOOSE_CHAT_TO_DOWNLOAD_CALLBACK_DATA),
                ])

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
        cls.bot_context.set_actual_field('name')
        message = context.bot.send_message(
            update.effective_chat.id,
            text=_('Enter Name below:'),
            parse_mode=ParseMode.MARKDOWN,
        )
        cls.bot_context.add_message_to_delete(message.message_id)

        context.bot.answer_callback_query(update.callback_query.id)
        return cls.SET_FIELDS_TEXT_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def set_title_template_start_action(cls, update: Update, context: CallbackContext):
        cls.bot_context.set_actual_field('title_template')
        message = context.bot.send_message(
            update.effective_chat.id,
            text=_('Enter Title Template below:'),
            parse_mode=ParseMode.MARKDOWN,
        )
        cls.bot_context.add_message_to_delete(message.message_id)

        context.bot.answer_callback_query(update.callback_query.id)
        return cls.SET_FIELDS_TEXT_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def edit_action(cls, update: Update, context: CallbackContext):
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

            context.bot.answer_callback_query(update.callback_query.id)
            return cls.SET_FIELDS_STATE

        context.bot.answer_callback_query(update.callback_query.id)
        return cls.BACK_STATE

    @classmethod
    def get_list_keyboard(cls):
        radios = radio_user.get_user_radios(int(cls.telegram_user.user_id))
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
        keyboard_radios = cls.get_list_keyboard()

        message = context.bot.send_message(
            update.effective_chat.id,
            text=cls.list_message_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard_radios)
        )
        cls.bot_context.set_list_message(message.message_id)

        context.bot.answer_callback_query(update.callback_query.id)
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
                                              reply_markup=InlineKeyboardMarkup(keyboard),
                                              disable_web_page_preview=True)

    @classmethod
    def get_broadcaster_keyboard(cls):
        broadcasters = get_owned_broadcasters(cls.telegram_user, 1, 20)
        # todo: create pagination

        keyboard = []
        for broadcaster in broadcasters:
            keyboard.append([
                InlineKeyboardButton(
                    _(str(broadcaster.uid) if broadcaster.uid else str(broadcaster.id)),
                    callback_data=cls.SET_BROADCASTER_CALLBACK_DATA % (broadcaster.id,))
            ])

        keyboard.append([
            InlineKeyboardButton(
                _('Back'),
                callback_data=cls.BACK_FROM_CHOOSE_BROADCASTER_CALLBACK_DATA
            ),
        ])

        return keyboard

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def choose_broadcaster_action(cls, update: Update, context: CallbackContext):
        keyboard = cls.get_broadcaster_keyboard()

        message = context.bot.send_message(
            update.effective_chat.id,
            text=_('Choose broadcaster.'),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        cls.bot_context.set_list_message(message.message_id)

        context.bot.answer_callback_query(update.callback_query.id)
        return cls.CHOOSE_BROADCASTER_CALLBACK_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def set_broadcaster_action(cls, update: Update, context: CallbackContext):
        match = re.match(cls.SET_BROADCASTER_CALLBACK_DATA_PATTERN, update.callback_query.data)
        if match:
            broadcaster_id = int(match.group(1))
            broadcaster = BroadcastUser.objects.get(id=broadcaster_id)
            model = cls.bot_context.get_actual_object()
            model.broadcast_user = broadcaster
            saved = False
            with transaction.atomic():
                model.save()
                saved = True

            if saved:
                message = context.bot.send_message(
                    update.effective_chat.id,
                    text=_('Broadcaster is set.'),
                    parse_mode=ParseMode.MARKDOWN
                )
                cls.bot_context.set_object_message_id(message.message_id)
                cls.update_object_message()
            else:
                pass

            context.bot.answer_callback_query(update.callback_query.id)
            return cls.SET_FIELDS_STATE

        context.bot.answer_callback_query(update.callback_query.id)
        return cls.BACK_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def choose_chat_to_broadcast_action(cls, update: Update, context: CallbackContext):
        cls.bot_context.set_actual_field('chat_id')
        message = context.bot.send_message(
            update.effective_chat.id,
            text=_('Enter group/channel ID:'),
            parse_mode=ParseMode.MARKDOWN,
        )
        cls.bot_context.add_message_to_delete(message.message_id)

        context.bot.answer_callback_query(update.callback_query.id)
        return cls.SET_FIELDS_TEXT_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadio.wrapper
    def choose_chat_to_download_action(cls, update: Update, context: CallbackContext):
        cls.bot_context.set_actual_field('download_chat_id')
        message = context.bot.send_message(
            update.effective_chat.id,
            text=_('Enter group/channel ID there we will download audio files:'),
            parse_mode=ParseMode.MARKDOWN,
        )
        cls.bot_context.add_message_to_delete(message.message_id)

        context.bot.answer_callback_query(update.callback_query.id)
        return cls.SET_FIELDS_TEXT_STATE
