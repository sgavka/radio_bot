import datetime as datetime
import random

from django.db import transaction, DatabaseError
from django.db.models import Q, Sum
from telegram import Audio, Voice, User
from django.utils.translation import ugettext as _
from bot.models import UserToRadio, Radio, Queue, AudioFile


def get_user_radios(user_id: int):
    radios_id = UserToRadio.objects.filter(user_id=user_id).values('radio_id').all()
    radios = Radio.objects.filter(id__in=radios_id).order_by('id').all()
    return radios


def get_radio_queue(radio: Radio, page: int, page_size: int):
    queues = Queue.objects.filter(
        ~Q(status=Queue.STATUS_DELETED),
        radio=radio
    ).select_related('audio_file').order_by('sort').all()[page * page_size:(page + 1) * page_size]
    return queues


def get_queue_duration_total(radio: Radio):
    seconds = AudioFile.objects.filter(queue__radio=radio).aggregate(Sum('duration_seconds'))
    return seconds


def get_queue_duration_in_queue(radio: Radio):
    seconds = AudioFile.objects.filter(queue__radio=radio, queue__status=Queue.STATUS_IN_QUEUE)\
        .aggregate(Sum('duration_seconds'))
    return seconds


def delete_queue_item(item: Queue):
    item.status = Queue.STATUS_DELETED
    item.save()


@transaction.atomic
def move_down_queue_item(item: Queue):
    next_item = Queue.objects.filter(
        ~Q(status=Queue.STATUS_DELETED),
        sort__gt=item.sort,
        radio=item.radio
    ).order_by('sort').first()
    item.sort, next_item.sort = next_item.sort, item.sort
    next_item.save()
    item.save()


@transaction.atomic
def move_up_queue_item(item: Queue):
    prev_item = Queue.objects.filter(
        ~Q(status=Queue.STATUS_DELETED),
        sort__lt=item.sort,
        radio=item.radio
    ).order_by('-sort').first()
    item.sort, prev_item.sort = prev_item.sort, item.sort
    prev_item.save()
    item.save()


def count_of_queue_items(radio: Radio):
    return Queue.objects.filter(
        ~Q(status=Queue.STATUS_DELETED),
        radio=radio
    ).count()


def add_audio_file_to_queue(audio: Audio, radio: Radio) -> bool:
    success = True
    try:
        with transaction.atomic():
            try:
                # todo: if download for each radio is necessary to has unique file in AudioFile?
                audio_file = AudioFile.objects.filter(telegram_file_id=audio.file_unique_id).get()
            except AudioFile.DoesNotExist:
                audio_file = AudioFile()
                audio_file.title = audio.title
                audio_file.author = audio.performer
                audio_file.duration_seconds = audio.duration
                audio_file.telegram_file_id = audio.file_id
                audio_file.telegram_unique_id = audio.file_unique_id
                audio_file.file_name = audio.file_name
                audio_file.size = audio.file_size

            _put_audio_file_to_queue(audio_file, radio)
    except DatabaseError as e:
        success = False

    return success


def add_voice_to_queue(voice: Voice, user: User, datetime: datetime, radio: Radio) -> bool:
    success = True
    try:
        with transaction.atomic():
            try:
                audio_file = AudioFile.objects.filter(telegram_file_id=voice.file_unique_id).get()
            except AudioFile.DoesNotExist:
                audio_file = AudioFile()
                title = _('Voice at %s', ) % (datetime.strftime('%H:%M, %d.%m.%Y'),)
                audio_file.title = title
                author = _('%s %s') % (user.last_name, user.first_name)
                audio_file.author = author
                audio_file.duration_seconds = voice.duration
                audio_file.telegram_file_id = voice.file_id
                audio_file.telegram_unique_id = voice.file_unique_id
                audio_file.file_name = _('%s ??? %s') % (author, title)
                audio_file.size = voice.file_size

            _put_voice_to_queue(audio_file, radio)
    except DatabaseError as e:
        success = False

    return success


def _put_audio_file_to_queue(audio_file, radio):
    queue = Queue()
    queue.radio = radio
    queue.audio_file = audio_file
    last_sort = Queue.objects.filter(radio=radio).order_by('-sort').values('sort').first()
    if last_sort:
        last_sort = last_sort['sort'] + 1
    else:
        last_sort = 0
    queue.sort = last_sort
    queue.datetime_is_automatic = True
    queue.on_air_always = False
    queue.type = Queue.AUDIO_FILE_TYPE
    audio_file.save()
    queue.save()


def _put_voice_to_queue(audio_file, radio):
    # todo: re-use
    queue = Queue()
    queue.radio = radio
    queue.audio_file = audio_file
    last_sort = Queue.objects.filter(radio=radio).order_by('-sort').values('sort').first()
    if last_sort:
        last_sort = last_sort['sort'] + 1
    else:
        last_sort = 0
    queue.sort = last_sort
    queue.datetime_is_automatic = True
    queue.on_air_always = False
    queue.type = Queue.VOICE_TYPE
    audio_file.save()
    queue.save()


def shuffle_all(radio: Radio):
    queues = Queue.objects.filter(radio=radio).all()
    random_queues = sorted(queues, key=lambda x: random.random())
    with transaction.atomic():
        i = 0
        for queue in random_queues:
            queue.sort = i
            queue.save()
            i += 1
        queues.update(status=Queue.STATUS_IN_QUEUE)


def shuffle_unplayed(radio: Radio):
    last_queue = Queue.objects.filter(radio=radio).filter(~Q(status=Queue.STATUS_IN_QUEUE)).order_by('-sort').first()
    if last_queue:
        i = last_queue.sort + 1
    else:
        i = 0
    queues = Queue.objects.filter(radio=radio, status=Queue.STATUS_IN_QUEUE).all()
    random_queues = sorted(queues, key=lambda x: random.random())
    with transaction.atomic():
        for queue in random_queues:
            queue.sort = i
            queue.save()
            i += 1
