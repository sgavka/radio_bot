import os


def get_session_directory():
    sessions_directory = 'data/sessions'
    if not os.path.exists(sessions_directory):
        os.mkdir(sessions_directory)
    return sessions_directory


def get_tmp_session_name(broadcast_auth_id):
    return str(broadcast_auth_id) + '_queue_add_new'


def get_session_name(broadcast_user_uid, broadcaster_id):
    return str(broadcast_user_uid) + '_account_' + str(broadcaster_id) + '_broadcaster'
