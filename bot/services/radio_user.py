from django.db import transaction
from telegram import Audio

from bot.models import UserToRadio, Radio, Queue, AudioFile


def get_user_radios(user_id: int):
    radios_id = UserToRadio.objects.filter(user_id=user_id).values('radio_id').all()
    # radios_id = UserToRadio.objects.select_related('radio').filter(user_id=user_id).all()
    radios = Radio.objects.filter(id__in=radios_id).all()
    return radios


def get_radio_queue(radio: Radio):
    queues = Queue.objects.filter(radio=radio).select_related('audio_file').all()
    return queues


def add_file_to_queue(audio: Audio, radio: Radio):
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

    return queue
