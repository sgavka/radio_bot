from django.contrib.auth.models import User
from django.db import models
from django.utils.translation import ugettext as _


class Bot(models.Model):
    name = models.CharField(max_length=255, blank=False)
    username = models.CharField(max_length=255, blank=False)
    token = models.CharField(max_length=255, blank=False)


class BroadcastUser(models.Model):
    STATUS_NEED_TO_AUTH = 0
    STATUS_IS_AUTH = 1

    id = models.AutoField(primary_key=True)
    uid = models.BigIntegerField(blank=True, null=True, unique=True)
    api_id = models.BigIntegerField()
    api_hash = models.CharField(max_length=255, blank=False)
    phone_number = models.CharField(max_length=255, blank=False)
    status = models.IntegerField(default=STATUS_NEED_TO_AUTH, blank=True, null=True)

    def has_all_data_to_auth(self) -> bool:
        if self.api_id and self.api_hash and self.phone_number:
            return True
        return False


class TelegramUser(models.Model):
    uid = models.BigIntegerField(primary_key=True)
    user = models.ForeignKey(User, models.CASCADE)

    def is_admin(self) -> bool:
        return self.user.is_superuser


class BroadcastUserOwner(models.Model):
    ROLE_OWNER = 1
    ROLE_HAVE_ACCESS = 2
    ROLES = {
        ROLE_OWNER: _('Owner'),
        ROLE_HAVE_ACCESS: _('Have Access'),
    }
    role = models.IntegerField(default=ROLE_OWNER)

    broadcast_user = models.ForeignKey(BroadcastUser, models.CASCADE)
    telegram_user = models.ForeignKey(TelegramUser, models.CASCADE)


class BroadcasterAuthQueue(models.Model):
    STATUS_NEED_TO_AUTH = 0
    STATUS_NEED_PASSWORD = 1
    STATUS_NEED_TO_AUTH_WITH_PASSWORD = 2
    STATUS_NEED_CODE = 3
    STATUS_NEED_TO_AUTH_WITH_CODE = 4
    STATUS_SUCCESS = 5
    STATUS_ACCOUNT_IS_NOT_REGISTERED = 6
    STATUS_PHONE_IS_INVALID = 7
    STATUS_CODE_IS_INVALID = 8
    STATUS_CODE_EXPIRED = 9
    STATUS_PASSWORD_IS_INVALID = 10
    STATUS_UNKNOWN_ERROR = 11
    STATUS_END_AUTH_PROCESS = 12
    STATUS_CANCELED = 13

    id = models.AutoField(primary_key=True)
    broadcast_user = models.ForeignKey(BroadcastUser, models.CASCADE)
    status = models.IntegerField(default=STATUS_NEED_TO_AUTH)
    password = models.CharField(max_length=255, blank=True, null=True)
    code = models.CharField(max_length=255, blank=True, null=True)
    phone_hash = models.CharField(max_length=255, blank=True, null=True)


class Radio(models.Model):
    STATUS_ON_AIR = 0
    STATUS_NOT_ON_AIR = 1
    STATUS_ASKING_FOR_BROADCAST = 2
    STATUS_ASKING_FOR_STOP_BROADCAST = 3
    STATUS_STARTING_BROADCAST = 4
    STATUS_ASKING_FOR_PAUSE_BROADCAST = 5
    STATUS_ASKING_FOR_RESUME_BROADCAST = 6
    STATUS_ON_PAUSE = 7
    STATUS_ERROR_AUDIO_CHAT_IS_NOT_STARTED = 8
    STATUS_ERROR_BROADCASTER_IS_NOT_IN_BROADCAST_GROUP_OR_CHANNEL = 9
    STATUS_ERROR_UNEXPECTED = 10
    STATUS_ERROR_IS_NOT_AUTHORIZED = 11
    STATUS_ERROR_CANT_CONNECT = 12
    STATUS_ERROR_NETWORK = 13
    STATUS_ERROR_JOIN_AS_PEER_INVALID = 14
    STATUSES = {
        STATUS_ON_AIR: 'On air',
        STATUS_NOT_ON_AIR: 'Not on air',
        STATUS_ASKING_FOR_BROADCAST: 'Asking for broadcast',
        STATUS_STARTING_BROADCAST: 'Starting broadcast',
        STATUS_ASKING_FOR_PAUSE_BROADCAST: 'Asking to pause broadcast',
        STATUS_ASKING_FOR_STOP_BROADCAST: 'Asking to stop broadcast',
        STATUS_ASKING_FOR_RESUME_BROADCAST: 'Asking to resume broadcast',
        STATUS_ON_PAUSE: 'On pause',
        STATUS_ERROR_AUDIO_CHAT_IS_NOT_STARTED: 'Audio chat is not started!',
        STATUS_ERROR_BROADCASTER_IS_NOT_IN_BROADCAST_GROUP_OR_CHANNEL: 'Broadcaster is not in broadcast group or '
                                                                       'channel!',
        STATUS_ERROR_UNEXPECTED: 'unexpected error',
        STATUS_ERROR_IS_NOT_AUTHORIZED: 'Telegram Account is not authorized!',
        STATUS_ERROR_CANT_CONNECT: 'Telegram Account can\'t connect!',
        STATUS_ERROR_NETWORK: 'On server was network errors!',
    }

    name = models.CharField(max_length=255, blank=False)
    title_template = models.TextField(blank=True, null=True)
    status = models.IntegerField(default=STATUS_NOT_ON_AIR)

    broadcast_user = models.ForeignKey(BroadcastUser, models.CASCADE, blank=True, null=True)
    chat_id = models.BigIntegerField(blank=True, null=True)
    download_chat_id = models.BigIntegerField(blank=True, null=True)
    last_chat_id = models.BigIntegerField(blank=True, null=True)
    last_message_id = models.BigIntegerField(blank=True, null=True)


class RadioChat(models.Model):
    uid = models.BigIntegerField(primary_key=True)
    radio = models.ForeignKey(Radio, models.CASCADE)


class UserToRadio(models.Model):
    # user that create (or have access)
    user = models.ForeignKey(User, models.CASCADE)
    radio = models.ForeignKey(Radio, models.CASCADE)

    # todo: make unique key (user, radio)


class AudioFile(models.Model):
    telegram_file_id = models.TextField(blank=True, null=True)
    telegram_unique_id = models.TextField(blank=True, null=True)
    title = models.CharField(max_length=255, blank=True, null=True)
    author = models.CharField(max_length=255, blank=True, null=True)
    file_name = models.CharField(max_length=255, blank=True, null=True)
    duration_seconds = models.IntegerField(blank=True, null=True)
    size = models.IntegerField(blank=True, null=True)

    def get_full_title(self) -> str:
        return _('%s — %s') % (self.author, self.title)


class Queue(models.Model):
    AUDIO_FILE_TYPE = 0
    VOICE_TYPE = 1
    TYPES = {
        AUDIO_FILE_TYPE: _('File'),
        VOICE_TYPE: _('Voice'),
    }

    STATUS_IN_QUEUE = 0
    STATUS_HAS_ERRORS = 1
    STATUS_PLAYED = 2
    STATUS_WAIT_TO_CALCULATE_START_DATETIME = 3  # todo: this is really necessary?
    STATUS_DELETED = 4
    STATUS_PROCESSING = 5
    STATUS_ERROR_CANT_DOWNLOAD = 6
    STATUS_PLAYING = 7  # todo: deal with abandoned queue with this status
    STATUSES = {
        STATUS_IN_QUEUE: _('In queue'),
        STATUS_HAS_ERRORS: _('Has errors'),
        STATUS_PLAYED: _('Played'),
        STATUS_WAIT_TO_CALCULATE_START_DATETIME: _('Wait to calculate start date time'),
        STATUS_DELETED: _('Deleted'),
        STATUS_PROCESSING: _('Processing...'),
        STATUS_ERROR_CANT_DOWNLOAD: _('Can\'t download'),
    }

    radio = models.ForeignKey(Radio, models.CASCADE)
    audio_file = models.ForeignKey(AudioFile, models.CASCADE)
    sort = models.IntegerField()
    datetime_start = models.DateTimeField(blank=True, null=True)
    datetime_is_automatic = models.BooleanField()
    on_air_always = models.BooleanField()  # only for streams
    type = models.IntegerField()
    status = models.IntegerField(default=STATUS_PROCESSING)


class QueueDownloadSoundCloud(models.Model):
    sound_cloud_id = models.BigIntegerField(primary_key=True)
    audio_file = models.ForeignKey(AudioFile, models.CASCADE, blank=True, null=True)
    status = models.IntegerField()
