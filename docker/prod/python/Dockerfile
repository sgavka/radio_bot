FROM python:3.9

RUN mkdir /code
WORKDIR /code

# install packages
RUN apt-get update && apt-get install -y gettext libgettextpo-dev ffmpeg
RUN pip install --upgrade pip

# Install Postgresql client V12
RUN set -x; \
    echo "deb http://apt.postgresql.org/pub/repos/apt/ buster-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add - \
    && apt-get update \
    && apt-get install -y postgresql-client-12

# install requiremnts
COPY ./requirements /code/requirements
RUN pip install --upgrade pip
RUN pip install --upgrade setuptools
RUN pip install -r requirements/prod.txt
RUN pip install -r requirements/prod.txt --upgrade

COPY . /code/

COPY ./docker/prod/python/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

COPY ./docker/prod/python/.pgpass /root/.pgpass
RUN chmod 0600 /root/.pgpass

RUN chmod +x /code/pg_backup_rotated.sh
