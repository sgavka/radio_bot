import asyncio
import os
import re
import threading
from math import ceil

import pyrogram
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from pyrogram import Client, raw
from pyrogram.errors import AuthKeyUnregistered
from telegram import Update, ParseMode, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import BadRequest
from telegram.ext import ConversationHandler, CallbackQueryHandler, CallbackContext, MessageHandler, Filters
from django.utils.translation import ugettext as _
from bot.bot_logic.bot_logic import BotLogic, BotContext
from bot.helpers import handlers_wrapper
from bot.models import BroadcastUser, BroadcastUserOwner, BroadcasterAuthQueue
from bot.services.broadcast_user import get_count_of_owned_broadcasters, get_owned_broadcasters
from bot.services.radio_user import count_of_queue_items


class BotContextRadioTelegramAccount(BotContext):
    CONTEXT_NAME = 'radio_telegram_account'

    LIST_CONTEXT = 'list'
    LIST_PAGE_CONTEXT = 'list_page'
    LIST_MESSAGE_CONTEXT = 'list_message_id'
    ACTION_CONTEXT = 'action'
    NEW_OBJECT_CONTEXT = 'new_object'
    EDIT_CONTEXT = 'edit'
    ID_CONTEXT = 'id'
    EDIT_OBJECT_CONTEXT = 'edit_object'
    ACTUAL_FIELD_CONTEXT = 'actual_field'
    MESSAGES_TO_DELETE_CONTEXT = 'messages_to_delete'
    OBJECT_MESSAGE_CONTEXT = 'object_message'
    EDIT_AUTH_QUEUE_ID_CONTEXT = 'edit_auth_queue_id'

    CREATE_ACTION = 'create'
    EDIT_ACTION = 'edit'

    DEFAULT_PAGE = 1
    ITEMS_ON_PAGE = 20

    def __init__(self, bot_logic: BotLogic):
        super().__init__(bot_logic)

        self.list = None
        self.edit = None

        self.init_list_context()
        self.init_edit_context()

    def init_list_context(self):
        if self.LIST_CONTEXT not in self.context:
            self.context[self.LIST_CONTEXT] = {}
        self.list = self.context[self.LIST_CONTEXT]

    def set_page(self, page: int):
        self.list[self.LIST_PAGE_CONTEXT] = page

    def get_page(self) -> int:
        if self.LIST_PAGE_CONTEXT in self.list:
            return self.list[self.LIST_PAGE_CONTEXT]
        return self.DEFAULT_PAGE

    def set_list_message(self, message_id):
        self.list[self.LIST_MESSAGE_CONTEXT] = message_id

    def get_list_message(self):
        return self.list[self.LIST_MESSAGE_CONTEXT]

    def delete_list_message(self):
        if self.LIST_MESSAGE_CONTEXT in self.list:
            message_id = self.list[self.LIST_MESSAGE_CONTEXT]
            try:
                self.bot_logic.context.bot.delete_message(self.bot_logic.update.effective_chat.id, message_id)
            except BadRequest:
                pass

    def set_create_action(self):
        self.context[self.ACTION_CONTEXT] = self.CREATE_ACTION

    def set_edit_action(self):
        self.context[self.ACTION_CONTEXT] = self.EDIT_ACTION

    def init_new_object(self):
        if self.NEW_OBJECT_CONTEXT not in self.context:
            self.context[self.NEW_OBJECT_CONTEXT] = BroadcastUser()
        return self.context[self.NEW_OBJECT_CONTEXT]

    def get_action(self):
        return self.context[self.ACTION_CONTEXT]

    def is_edit_action(self):
        return self.context[self.ACTION_CONTEXT] is self.EDIT_ACTION

    def init_edit_context(self):
        if self.EDIT_CONTEXT not in self.context:
            self.context[self.EDIT_CONTEXT] = {}
        self.edit = self.context[self.EDIT_CONTEXT]

    def set_edited_id(self, edit_id: int):
        self.edit[self.ID_CONTEXT] = edit_id
        if self.EDIT_OBJECT_CONTEXT in self.edit:
            del self.edit[self.EDIT_OBJECT_CONTEXT]

    def get_edited_object(self) -> BroadcastUser:
        if self.ID_CONTEXT not in self.edit:
            raise Exception('Edited Broadcaster ID is not set!')
        if self.EDIT_OBJECT_CONTEXT not in self.edit:
            radio_object = BroadcastUser.objects.filter(id=self.edit[self.ID_CONTEXT]).get()
            self.edit[self.EDIT_OBJECT_CONTEXT] = radio_object
        return self.edit[self.EDIT_OBJECT_CONTEXT]

    def set_actual_auth_queue_id(self, auth_queue_id: int):
        self.edit[self.EDIT_AUTH_QUEUE_ID_CONTEXT] = auth_queue_id

    def get_actual_auth_queue_id(self):
        if self.EDIT_AUTH_QUEUE_ID_CONTEXT in self.edit:
            return self.edit[self.EDIT_AUTH_QUEUE_ID_CONTEXT]
        return False

    def get_actual_object(self) -> BroadcastUser:
        action = self.get_action()
        if action is self.EDIT_ACTION:
            return self.get_edited_object()
        elif action is self.CREATE_ACTION:
            return self.init_new_object()

    def has_actual_object(self):
        if self.get_actual_object():
            return True
        return False

    def set_actual_field(self, field_name):
        self.edit[self.ACTUAL_FIELD_CONTEXT] = field_name

    def get_actual_field(self):
        return self.edit[self.ACTUAL_FIELD_CONTEXT]

    def add_message_to_delete(self, message_id):
        if self.MESSAGES_TO_DELETE_CONTEXT not in self.context:
            self.context[self.MESSAGES_TO_DELETE_CONTEXT] = []
        self.context[self.MESSAGES_TO_DELETE_CONTEXT].append(message_id)

    def delete_messages(self):
        for message_id in self.context[self.MESSAGES_TO_DELETE_CONTEXT]:
            try:
                self.bot_logic.context.bot.delete_message(self.bot_logic.update.effective_chat.id, message_id)
            except BadRequest:
                pass
        del self.context[self.MESSAGES_TO_DELETE_CONTEXT]

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


class BotLogicRadioTelegramAccount(BotLogic):
    create_message_text = _('To create new object select field and set data.\nData:\n%s')
    edit_message_text = _('It\'s your Broadcast Account.\n%s\nData:\n%s')

    BACK_STATE = r'back'
    SET_FIELDS_STATE = r'set_fields'
    LIST_STATE = r'state'
    SET_FIELDS_TEXT_STATE = r'set_fields_text'
    SET_FIELDS_FOR_AUTH_STATE = r'set_fields_for_auth'

    BACK_CALLBACK_DATA = r'back'
    CREATE_CALLBACK_DATA = r'create'
    EDIT_CALLBACK_DATA = r'edit_%s'
    EDIT_CALLBACK_DATA_PATTERN = r'edit_(\d+)'
    PREV_PAGE_CALLBACK_DATA = r'list_prev_page'
    NEXT_PAGE_CALLBACK_DATA = r'list_next_page'
    SET_API_HASH_CALLBACK_DATA = r'set_api_hash'
    SET_PHONE_NUMBER_CALLBACK_DATA = r'set_phone_number'
    SET_API_ID_CALLBACK_DATA = r'set_api_id'
    EDIT_BACK_CALLBACK_DATA = r'edit_back'
    SAVE_CALLBACK_DATA = r'save'
    AUTH_CALLBACK_DATA = r'auth'
    END_AUTH_PROCESS_CALLBACK_DATA = r'end_auth_process'

    bot_context: BotContextRadioTelegramAccount

    @classmethod
    def get_conversation_handler(cls) -> ConversationHandler:
        from bot.bot_logic.main import BotLogicMain
        list_handler = CallbackQueryHandler(cls.show_list_action, pattern=BotLogicMain.TELEGRAM_ACCOUNT_CALLBACK_DATA)
        create_handler = CallbackQueryHandler(cls.create_action, pattern=cls.CREATE_CALLBACK_DATA)
        edit_handler = CallbackQueryHandler(cls.edit_action, pattern=cls.EDIT_CALLBACK_DATA_PATTERN)
        conversation_handler = ConversationHandler(
            entry_points=[list_handler],
            states={
                cls.LIST_STATE: [list_handler, create_handler, edit_handler],
                cls.SET_FIELDS_STATE: [
                    CallbackQueryHandler(cls.set_api_hash_action, pattern=cls.SET_API_HASH_CALLBACK_DATA),
                    CallbackQueryHandler(cls.set_api_id_action, pattern=cls.SET_API_ID_CALLBACK_DATA),
                    CallbackQueryHandler(cls.set_phone_number_action, pattern=cls.SET_PHONE_NUMBER_CALLBACK_DATA),
                    CallbackQueryHandler(cls.auth_action, pattern=cls.AUTH_CALLBACK_DATA),
                    CallbackQueryHandler(cls.end_auth_process_action, pattern=cls.END_AUTH_PROCESS_CALLBACK_DATA),
                    CallbackQueryHandler(cls.save_action, pattern=cls.SAVE_CALLBACK_DATA),
                    CallbackQueryHandler(cls.edit_back_action, pattern=cls.EDIT_BACK_CALLBACK_DATA),
                    # todo: need delete action
                ],
                cls.SET_FIELDS_FOR_AUTH_STATE: [MessageHandler(Filters.text, cls.set_fields_for_auth_action)],
                cls.SET_FIELDS_TEXT_STATE: [MessageHandler(Filters.text, cls.set_fields_text_action)],
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
    @BotContextRadioTelegramAccount.wrapper
    def show_list_action(cls, update: Update, context: CallbackContext):
        keyboard_radios = cls.get_list_keyboard()

        message = context.bot.send_message(
            update.effective_chat.id,
            text=_('There is your list of Telegram Account to use to broadcast.'),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard_radios)
        )

        cls.bot_context.set_list_message(message.message_id)
        return cls.LIST_STATE

    @classmethod
    def update_list_message(cls, update: Update, context: CallbackContext):
        keyboard_radios = cls.get_list_keyboard()

        try:
            context.bot.edit_message_reply_markup(
                update.effective_chat.id,
                cls.bot_context.get_list_message(),
                reply_markup=InlineKeyboardMarkup(keyboard_radios)
            )
        except BadRequest:
            pass
        return cls.LIST_STATE

    @classmethod
    def get_list_keyboard(cls):
        keyboard = []

        pages = []
        page = cls.bot_context.get_page()
        if page > BotContextRadioTelegramAccount.DEFAULT_PAGE:
            pages.append(
                InlineKeyboardButton(
                    _('<<'),
                    callback_data=cls.PREV_PAGE_CALLBACK_DATA),
            )

        broadcasters = get_owned_broadcasters(cls.telegram_user, page, BotContextRadioTelegramAccount.ITEMS_ON_PAGE)
        for broadcaster in broadcasters:
            keyboard.append([
                InlineKeyboardButton(
                    str(broadcaster.uid if broadcaster.uid else broadcaster.id),
                    callback_data=cls.EDIT_CALLBACK_DATA % (str(broadcaster.id),)
                ),
            ])

        total_in_list = get_count_of_owned_broadcasters(cls.telegram_user)
        pages_float = total_in_list / BotContextRadioTelegramAccount.ITEMS_ON_PAGE
        if page > BotContextRadioTelegramAccount.DEFAULT_PAGE or pages_float > 1:
            pages.append(
                InlineKeyboardButton(
                    _('%s') % (page + 1,),
                    callback_data='blank'
                ),
            )

        if pages_float > 1 and page < ceil(pages_float) - 1:
            pages.append(
                InlineKeyboardButton(
                    _('>>'),
                    callback_data=cls.NEXT_PAGE_CALLBACK_DATA
                ),
            )

        if len(pages):
            keyboard.append(pages)

        keyboard.append([
            InlineKeyboardButton(
                _('Create New'),
                callback_data=cls.CREATE_CALLBACK_DATA
            ),
        ])

        keyboard.append([
            InlineKeyboardButton(
                _('Back'),
                callback_data=cls.BACK_CALLBACK_DATA
            ),
        ])

        return keyboard

    @classmethod
    @handlers_wrapper
    @BotContextRadioTelegramAccount.wrapper
    def next_page_action(cls, update: Update, context: CallbackContext):
        page = cls.bot_context.get_page()
        cls.bot_context.set_page(page + 1)
        cls.update_list_message(update, context)
        return cls.LIST_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadioTelegramAccount.wrapper
    def prev_page_action(cls, update: Update, context: CallbackContext):
        page = cls.bot_context.get_page()
        cls.bot_context.set_page(page - 1)
        cls.update_list_message(update, context)
        return cls.LIST_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadioTelegramAccount.wrapper
    def create_action(cls, update: Update, context: CallbackContext):
        cls.bot_context.set_create_action()
        broadcast_user = cls.bot_context.init_new_object()
        keyboard = cls.get_object_keyboard()
        data_strings = cls.get_data_strings(broadcast_user)

        message = context.bot.send_message(
            update.effective_chat.id,
            text=cls.create_message_text % ('\n'.join(data_strings),),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        cls.bot_context.set_object_message_id(message.message_id)

        return cls.SET_FIELDS_STATE

    @classmethod
    def get_data_strings(cls, model: BroadcastUser):
        data_strings = [
            _('API ID**: *%s*') % (model.api_id if model.api_id else r'—',),
            _('API Hash**: *%s*') % (model.api_hash if model.api_hash else r'—',),
            _('API Phone Number**: *%s*') % (model.phone_number if model.phone_number else r'—',),
        ]
        return data_strings

    @classmethod
    def get_object_keyboard(cls):
        broadcast_user = cls.bot_context.get_actual_object()
        if broadcast_user.api_id:
            set_api_id_text = _('Change API ID')
        else:
            set_api_id_text = _('Add API ID')

        if broadcast_user.api_hash:
            set_api_hash_text = _('Change API Hash')
        else:
            set_api_hash_text = _('Add API Hash')

        if broadcast_user.phone_number:
            set_phone_number_text = _('Change Phone Number')
        else:
            set_phone_number_text = _('Add Phone Number')

        keyboard = [[
            InlineKeyboardButton(
                set_api_id_text,
                callback_data=cls.SET_API_ID_CALLBACK_DATA),
            InlineKeyboardButton(
                set_api_hash_text,
                callback_data=cls.SET_API_HASH_CALLBACK_DATA),
            InlineKeyboardButton(
                set_phone_number_text,
                callback_data=cls.SET_PHONE_NUMBER_CALLBACK_DATA),
        ]]

        # todo: show Auth only if BroadcastUser is not authorized
        if broadcast_user.has_all_data_to_auth() and broadcast_user.id is not None:
            keyboard.append([
                InlineKeyboardButton(
                    _('Auth'),
                    callback_data=cls.AUTH_CALLBACK_DATA),
            ])
        # todo: dont show for saved & dont changed models
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
    def update_object_message(cls):
        message_id = cls.bot_context.get_object_message_id()

        model = cls.bot_context.get_actual_object()
        keyboard = cls.get_object_keyboard()
        text = cls.get_edit_message_text(model)

        if text:
            cls.context.bot.edit_message_text(text,
                                              cls.update.effective_chat.id,
                                              message_id,
                                              parse_mode=ParseMode.MARKDOWN,
                                              disable_web_page_preview=True)
        cls.context.bot.edit_message_reply_markup(cls.update.effective_chat.id,
                                                  message_id, reply_markup=InlineKeyboardMarkup(keyboard))

    @classmethod
    def get_edit_message_text(cls, model: BroadcastUser):
        data_strings = cls.get_data_strings(model)
        # todo: show auth status
        if model.id is None:
            text = cls.edit_message_text % (_('Before Auth you mast save Broadcaster.'), '\n'.join(data_strings))
        elif model.id is not None:
            text = cls.edit_message_text % (_('You need to press Auth now.'), '\n'.join(data_strings))
        else:
            text = cls.edit_message_text % (_('Please fill all required data!'), '\n'.join(data_strings))
        return text

    @classmethod
    @handlers_wrapper
    @BotContextRadioTelegramAccount.wrapper
    def set_api_id_action(cls, update: Update, context: CallbackContext):
        context.bot.answer_callback_query(update.callback_query.id)

        cls.bot_context.set_actual_field('api_id')
        message = context.bot.send_message(
            update.effective_chat.id,
            text=_('Enter API ID below:'),
            parse_mode=ParseMode.MARKDOWN,
        )
        cls.bot_context.add_message_to_delete(message.message_id)

        return cls.SET_FIELDS_TEXT_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadioTelegramAccount.wrapper
    def set_api_hash_action(cls, update: Update, context: CallbackContext):
        context.bot.answer_callback_query(update.callback_query.id)

        cls.bot_context.set_actual_field('api_hash')
        message = context.bot.send_message(
            update.effective_chat.id,
            text=_('Enter API Hash below:'),
            parse_mode=ParseMode.MARKDOWN,
        )
        cls.bot_context.add_message_to_delete(message.message_id)

        return cls.SET_FIELDS_TEXT_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadioTelegramAccount.wrapper
    def set_phone_number_action(cls, update: Update, context: CallbackContext):
        context.bot.answer_callback_query(update.callback_query.id)

        cls.bot_context.set_actual_field('phone_number')
        message = context.bot.send_message(
            update.effective_chat.id,
            text=_('Enter Phone Number below:'),
            parse_mode=ParseMode.MARKDOWN,
        )
        cls.bot_context.add_message_to_delete(message.message_id)

        return cls.SET_FIELDS_TEXT_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadioTelegramAccount.wrapper
    def set_fields_text_action(cls, update: Update, context: CallbackContext):
        field = cls.bot_context.get_actual_field()
        broadcast_user = cls.bot_context.get_actual_object()

        valid = True

        if valid:
            setattr(broadcast_user, field, update.message.text)
            cls.update_object_message()

        return cls.SET_FIELDS_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadioTelegramAccount.wrapper
    def auth_action(cls, update: Update, context: CallbackContext):
        model = cls.bot_context.get_actual_object()

        # add to Auth Queue
        auth_queue = BroadcasterAuthQueue()
        auth_queue.broadcast_user = model
        auth_queue.save()
        auth_queue_id = auth_queue.id

        message = context.bot.send_message(
            update.effective_chat.id,
            text=_('Auth process starts. Wait...'),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(_('End auth process'), callback_data=cls.END_AUTH_PROCESS_CALLBACK_DATA), ]
            ])
        )
        cls.bot_context.add_message_to_delete(message.message_id)
        cls.bot_context.set_actual_auth_queue_id(auth_queue_id)

        return cls.wait_auth_worker(auth_queue_id, context, update)

    @classmethod
    @handlers_wrapper
    @BotContextRadioTelegramAccount.wrapper
    def end_auth_process_action(cls, update: Update, context: CallbackContext):
        auth_queue_id = cls.bot_context.get_actual_auth_queue_id()
        auth_queue = BroadcasterAuthQueue.objects.get(id=auth_queue_id)
        auth_queue.status = BroadcasterAuthQueue.STATUS_CANCELED
        auth_queue.save()

        message = context.bot.send_message(
            update.effective_chat.id,
            text=_('Auth process is canceled.'),
            parse_mode=ParseMode.MARKDOWN
        )
        cls.bot_context.add_message_to_delete(message.message_id)

        return cls.SET_FIELDS_STATE

    @classmethod
    def wait_auth_worker(cls, auth_queue_id, context, update):
        while True:
            auth_queue = BroadcasterAuthQueue.objects.filter(id=auth_queue_id).first()
            if auth_queue.status == BroadcasterAuthQueue.STATUS_NEED_CODE:
                # todo: add button 'i dont receive code'
                message = context.bot.send_message(
                    update.effective_chat.id,
                    text=_('Telegram send you verification code, send it there:'),
                    parse_mode=ParseMode.MARKDOWN
                )
                cls.bot_context.add_message_to_delete(message.message_id)

                return cls.SET_FIELDS_FOR_AUTH_STATE
            elif auth_queue.status == BroadcasterAuthQueue.STATUS_NEED_PASSWORD:
                message = context.bot.send_message(
                    update.effective_chat.id,
                    text=_('Telegram need your password to auth, send it there:'),
                    parse_mode=ParseMode.MARKDOWN
                )
                cls.bot_context.add_message_to_delete(message.message_id)

                return cls.SET_FIELDS_FOR_AUTH_STATE
            elif auth_queue.status == BroadcasterAuthQueue.STATUS_SUCCESS:
                message = context.bot.send_message(
                    update.effective_chat.id,
                    text=_('Auth is successful!'),
                    parse_mode=ParseMode.MARKDOWN
                )
                cls.bot_context.add_message_to_delete(message.message_id)
                # todo: update model message

                return cls.SET_FIELDS_STATE
            elif auth_queue.status == BroadcasterAuthQueue.STATUS_ACCOUNT_IS_NOT_REGISTERED:
                message = context.bot.send_message(
                    update.effective_chat.id,
                    text=_('Your account is not registered! First register after your can auth there.'),
                    parse_mode=ParseMode.MARKDOWN
                )
                cls.bot_context.add_message_to_delete(message.message_id)

                return cls.SET_FIELDS_STATE
            elif auth_queue.status == BroadcasterAuthQueue.STATUS_CODE_EXPIRED:
                message = context.bot.send_message(
                    update.effective_chat.id,
                    text=_('Your SMS code is expired. Telegram send you another verification code, send it there:'),
                    parse_mode=ParseMode.MARKDOWN
                )
                cls.bot_context.add_message_to_delete(message.message_id)

                auth_queue.status = BroadcasterAuthQueue.STATUS_NEED_TO_AUTH
                auth_queue.save()

                return cls.SET_FIELDS_FOR_AUTH_STATE
            elif auth_queue.status == BroadcasterAuthQueue.STATUS_CODE_IS_INVALID:
                message = context.bot.send_message(
                    update.effective_chat.id,
                    text=_('Your SMS code is invalid. Type it again:'),
                    parse_mode=ParseMode.MARKDOWN
                )
                cls.bot_context.add_message_to_delete(message.message_id)

                auth_queue.status = BroadcasterAuthQueue.STATUS_NEED_CODE
                auth_queue.save()

                return cls.SET_FIELDS_FOR_AUTH_STATE
            elif auth_queue.status == BroadcasterAuthQueue.STATUS_PHONE_IS_INVALID:
                message = context.bot.send_message(
                    update.effective_chat.id,
                    text=_('The phone number you entered is invalid! Please change phone number and press Auth again.'),
                    parse_mode=ParseMode.MARKDOWN
                )
                cls.bot_context.add_message_to_delete(message.message_id)

                return cls.SET_FIELDS_STATE
            elif auth_queue.status == BroadcasterAuthQueue.STATUS_UNKNOWN_ERROR:
                message = context.bot.send_message(
                    update.effective_chat.id,
                    text=_(
                        'There is unknown error, check your data and try Auth again. If there is steel error please write '
                        'to @sgavka.'),
                    parse_mode=ParseMode.MARKDOWN
                )
                cls.bot_context.add_message_to_delete(message.message_id)

                return cls.SET_FIELDS_STATE
            elif auth_queue.status == BroadcasterAuthQueue.STATUS_PASSWORD_IS_INVALID:
                message = context.bot.send_message(
                    update.effective_chat.id,
                    text=_('Your password is invalid, please try again:'),
                    parse_mode=ParseMode.MARKDOWN
                )
                cls.bot_context.add_message_to_delete(message.message_id)

                return cls.SET_FIELDS_FOR_AUTH_STATE
            elif auth_queue.status == BroadcasterAuthQueue.STATUS_END_AUTH_PROCESS:
                return cls.SET_FIELDS_STATE
            # todo: send another code

    @classmethod
    @handlers_wrapper
    @BotContextRadioTelegramAccount.wrapper
    def set_fields_for_auth_action(cls, update: Update, context: CallbackContext):
        model = cls.bot_context.get_actual_object()
        broadcaster_queue = BroadcasterAuthQueue.objects.filter(~Q(status=BroadcasterAuthQueue.STATUS_SUCCESS),
                                                                broadcast_user=model).get()
        if broadcaster_queue:
            if broadcaster_queue.status == BroadcasterAuthQueue.STATUS_NEED_CODE:
                broadcaster_queue.code = update.message.text
                message = context.bot.send_message(
                    update.effective_chat.id,
                    text=_('There is your code.'),
                    parse_mode=ParseMode.MARKDOWN
                )
                cls.bot_context.add_message_to_delete(message.message_id)

                broadcaster_queue.status = BroadcasterAuthQueue.STATUS_NEED_TO_AUTH_WITH_CODE
                broadcaster_queue.save()

                return cls.wait_auth_worker(broadcaster_queue.id, context, update)
            elif broadcaster_queue.status == BroadcasterAuthQueue.STATUS_NEED_PASSWORD:
                broadcaster_queue.password = update.message.text
                message = context.bot.send_message(
                    update.effective_chat.id,
                    text=_('There is your password.'),
                    parse_mode=ParseMode.MARKDOWN
                )
                cls.bot_context.add_message_to_delete(message.message_id)

                broadcaster_queue.status = BroadcasterAuthQueue.STATUS_NEED_TO_AUTH_WITH_PASSWORD
                broadcaster_queue.save()

                return cls.wait_auth_worker(broadcaster_queue.id, context, update)

    @classmethod
    @handlers_wrapper
    @BotContextRadioTelegramAccount.wrapper
    def save_action(cls, update: Update, context: CallbackContext):
        context.bot.answer_callback_query(update.callback_query.id)
        model = cls.bot_context.get_actual_object()

        saved = False
        try:
            model.full_clean()
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
            model.save()
            owner = BroadcastUserOwner()
            owner.broadcast_user = model
            owner.telegram_user = cls.telegram_user
            owner.save()
            saved = True

        if saved:
            context.bot.answer_callback_query(update.callback_query.id, _('Broadcaster was saved!'))  # todo: dont work

            cls.update_list_message(update, context)
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
    @BotContextRadioTelegramAccount.wrapper
    def edit_action(cls, update: Update, context: CallbackContext):
        context.bot.answer_callback_query(update.callback_query.id)

        match = re.match(cls.EDIT_CALLBACK_DATA_PATTERN, update.callback_query.data)
        if match:
            edit_id = int(match.group(1))
            cls.bot_context.set_edited_id(edit_id)
            model = cls.bot_context.get_edited_object()
            cls.bot_context.set_edit_action()

            keyboard = cls.get_object_keyboard()
            text = cls.get_edit_message_text(model)

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
    @handlers_wrapper
    @BotContextRadioTelegramAccount.wrapper
    def back_action(cls, update: Update, context: CallbackContext):
        cls.bot_context.delete_list_message()
        return cls.BACK_STATE

    @classmethod
    @handlers_wrapper
    @BotContextRadioTelegramAccount.wrapper
    def edit_back_action(cls, update: Update, context: CallbackContext):
        cls.bot_context.clear_after_save()
        context.bot.answer_callback_query(update.callback_query.id, _('Back! Changes was cleared.'))
        return cls.LIST_STATE
