from typing import List


def get_count_of_owned_broadcasters(telegram_user: 'TelegramUser') -> int:
    from bot.models import BroadcastUser, BroadcastUserOwner
    count = BroadcastUser.objects.filter(
        uid__in=BroadcastUserOwner.objects.filter(telegram_user=telegram_user,
                                                  role=BroadcastUserOwner.ROLE_OWNER).values('telegram_user'),
    ).count()

    return count


def get_owned_broadcasters(telegram_user: 'TelegramUser', page: int, page_size: int) -> List['BroadcastUser']:
    from bot.models import BroadcastUser, BroadcastUserOwner
    page -= 1
    broadcasters = BroadcastUser.objects.filter(
        id__in=BroadcastUserOwner.objects.filter(telegram_user=telegram_user,
                                                  role=BroadcastUserOwner.ROLE_OWNER).values('broadcast_user'),
    ).all()[page * page_size:(page + 1) * page_size]

    return broadcasters
