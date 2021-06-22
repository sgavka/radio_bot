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
    },
    'root': {
        'handlers': ['file'],
        'level': 'ERROR',
    },
    # 'loggers': {
    #     'django': {
    #         'handlers': ['file', 'mail_admins'],
    #         'propagate': True,
    #     },
    #     'django.request': {
    #         'handlers': ['file', 'mail_admins'],
    #         'level': 'ERROR',
    #         'propagate': False,
    #     },
    #     'admin_bot': {
    #         'handlers': ['file', 'mail_admins'],
    #         'level': 'INFO',
    #     }
    # }
}
