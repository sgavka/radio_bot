#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'main.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    if os.environ.get('RUN_MAIN') == 'true':
        HOST_IP = os.environ['EXTERNAL_IP']
        import pydevd_pycharm

        pydevd_pycharm.settrace(HOST_IP, port=8001, stdoutToServer=True, stderrToServer=True)
    main()
