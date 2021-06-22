from django.contrib.auth.models import User
from django.db import models


class Bot(models.Model):
    name = models.CharField(max_length=255)
    username = models.CharField(max_length=255)
    token = models.CharField(max_length=255)


class TelegramAccount(models.Model):
    uid = models.BigIntegerField(primary_key=True)
    app_api_id = models.BigIntegerField()
    app_api_hash = models.CharField(max_length=255)
    app_title = models.CharField(max_length=255, blank=True, null=True)
    app_short_name = models.CharField(max_length=255, blank=True, null=True)


class Radio(models.Model):
    name = models.CharField(max_length=255)
    telegram_account = models.ForeignKey(User, models.CASCADE)
    google_table_id = models.CharField(max_length=255, blank=True, null=True)
    title_template = models.TextField(blank=True, null=True)


class RadioChat(models.Model):
    uid = models.BigIntegerField(primary_key=True)
    radio = models.ForeignKey(Radio, models.CASCADE)


class TelegramUser(models.Model):
    uid = models.BigIntegerField(primary_key=True)
    user = models.ForeignKey(User, models.CASCADE)


class UserToRadio(models.Model):
    user = models.ForeignKey(User, models.CASCADE)
    radio = models.ForeignKey(Radio, models.CASCADE)


class AudioFile(models.Model):
    telegram_file_id = models.BigIntegerField(blank=True, null=True)
    title = models.CharField(max_length=255, blank=True, null=True)
    author = models.CharField(max_length=255, blank=True, null=True)
    file_name = models.CharField(max_length=255, blank=True, null=True)
    duration_seconds = models.IntegerField(blank=True, null=True)


class Queue(models.Model):
    radio = models.ForeignKey(Radio, models.CASCADE)
    audio_file = models.ForeignKey(AudioFile, models.CASCADE)
    sort = models.IntegerField()
    datetime_start = models.DateTimeField(blank=True, null=True)


class QueueDownloadSoundCloud(models.Model):
    sound_cloud_id = models.BigIntegerField(primary_key=True)
    audio_file = models.ForeignKey(AudioFile, models.CASCADE, blank=True, null=True)
    status = models.IntegerField()
