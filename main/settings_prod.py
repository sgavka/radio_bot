import os
from main.settings import *

DEBUG = False
SECRET_KEY = os.getenv('SECRET_KEY')

STATIC_URL = '/static/'
STATIC_ROOT = '/static_files/'

ALLOWED_HOSTS = [
    os.getenv('HOST')
]

# Database
# https://docs.djangoproject.com/en/3.0/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'postgres',
        'USER': os.getenv('POSTGRES_USER'),
        'PASSWORD': os.getenv('POSTGRES_PASSWORD'),
        'HOST': os.getenv('DATABASE_HOST'),
        'PORT': 5432,
    }
}

ADMINS = [('Gavka Serhiy', 'sgavka@gmail.com'),]

# Logging configuration

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'filters': {
        'require_debug_true': {
            '()': 'django.utils.log.RequireDebugTrue',
        },
    },
    'handlers': {
        'mail_admins': {
            'level': 'DEBUG',
            'class': 'django.utils.log.AdminEmailHandler',
            'formatter': 'verbose',
        },
        'file': {
            'level': 'DEBUG',
            'class': 'logging.FileHandler',
            'filename': os.path.join(BASE_DIR, 'logs/debug.log'),
            'formatter': 'verbose',
        },
        'file_download_actual_queue': {
            'level': 'DEBUG',
            'class': 'logging.FileHandler',
            'filename': os.path.join(BASE_DIR, 'logs/errors_download_actual_queue.log'),
            'formatter': 'verbose',
        },
        'file_format_raw_files': {
            'level': 'DEBUG',
            'class': 'logging.FileHandler',
            'filename': os.path.join(BASE_DIR, 'logs/errors_format_raw_files.log'),
            'formatter': 'verbose',
        },
        'file_broadcaster_auth': {
            'level': 'DEBUG',
            'class': 'logging.FileHandler',
            'filename': os.path.join(BASE_DIR, 'logs/errors_broadcaster_auth.log'),
            'formatter': 'verbose',
        },
        'file_start_bot': {
            'level': 'DEBUG',
            'class': 'logging.FileHandler',
            'filename': os.path.join(BASE_DIR, 'logs/errors_start_bot.log'),
            'formatter': 'verbose',
        },
        'file_broadcast': {
            'level': 'DEBUG',
            'class': 'logging.FileHandler',
            'filename': os.path.join(BASE_DIR, 'logs/errors_broadcast.log'),
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['file'],
        'level': 'ERROR',
    },
    'loggers': {
        'django': {
            'handlers': ['file', 'mail_admins'],
            'propagate': True,
        },
        'django.request': {
            'handlers': ['file', 'mail_admins'],
            'level': 'ERROR',
            'propagate': False,
        },
        'admin_bot': {
            'handlers': ['file', 'mail_admins'],
            'level': 'INFO',
        },
        'download_actual_queue': {
            'handlers': ['file_download_actual_queue', 'mail_admins'],
            'level': 'ERROR',
        },
        'format_raw_files': {
            'handlers': ['file_format_raw_files', 'mail_admins'],
            'level': 'ERROR',
        },
        'broadcaster_auth': {
            'handlers': ['file_broadcaster_auth', 'mail_admins'],
            'level': 'ERROR',
        },
        'start_bot': {
            'handlers': ['file_start_bot', 'mail_admins'],
            'level': 'ERROR',
        },
        'broadcast': {
            'handlers': ['file_broadcast', 'mail_admins'],
            'level': 'ERROR',
        },
    }
}
