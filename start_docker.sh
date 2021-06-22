#!/bin/sh

IP=$(ip route | grep docker | awk '{print $9}' | head -n 1);
export EXTERNAL_IP=$IP
export SERVER_PORT=8001

export PYTHONUNBUFFERED=1
export DJANGO_SETTINGS_MODULE=main.settings
export PYCHARM_DEBUG=True

exec docker-compose up --exit-code-from web --abort-on-container-exit web