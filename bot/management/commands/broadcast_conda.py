# todo: broadcaster can broadcast as channel only if it owns the channel
# todo: catch error pyrogram.errors.exceptions.bad_request_400.BadRequest: [400 Bad Request]: [400 JOIN_AS_PEER_INVALID] (caused by "phone.JoinGroupCall")
from bot.management.commands.broadcast import Command as BaseCommand

class Command(BaseCommand):
    pass
