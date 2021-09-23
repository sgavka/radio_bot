from django.db import transaction, IntegrityError, DatabaseError
from django.db.models import Q
from telegram import Audio

from bot.models import UserToRadio, Radio, Queue, AudioFile


def get_user_radios(user_id: int):
    radios_id = UserToRadio.objects.filter(user_id=user_id).values('radio_id').all()
    radios = Radio.objects.filter(id__in=radios_id).all()
    return radios


def get_radio_queue(radio: Radio, page: int, page_size: int):
    queues = Queue.objects.filter(
        ~Q(status=Queue.STATUS_DELETED),
        radio=radio
    ).select_related('audio_file').order_by('sort').all()[page * page_size:page_size]
    return queues


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


def add_file_to_queue(audio: Audio, radio: Radio) -> bool:
    success = True
    try:
        with transaction.atomic():
            try:
                audio_file = AudioFile.objects.filter(telegram_file_id=audio.file_unique_id).get()
            except AudioFile.DoesNotExist:
                audio_file = AudioFile()
                audio_file.title = audio.title
                audio_file.author = audio.performer
                audio_file.duration_seconds = audio.duration
                audio_file.telegram_file_id = audio.file_unique_id
                audio_file.file_name = audio.file_name
                audio_file.size = audio.file_size

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
            queue.type = Queue.FILE_TYPE

            audio_file.save()
            queue.save()
    except DatabaseError as e:
        success = False

    return success
