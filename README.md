# Allow to edit files
`sudo chown -R $USER:$USER .`

# Run command in container
`docker-compose run [container] [command]`

# Set up debug for django commands

Open Run/Config Configuration.
Set Script path to `manage.py`.
In Parameters set name of command.
Set up Work directory to project root.
Select new configuration and run Debug.

# Migrations

## Reverse to specific migration
`docker-compose run web python3 manage.py migrate [app] [last_migration]`

## Reverse all migrations
`docker-compose run web python3 manage.py migrate [app] zero`

## Create migration
`docker-compose run web python manage.py makemigrations`

## Migrate
`docker-compose run web python manage.py migrate`

## Create Admin superuser
`docker-compose run web python manage.py createsuperuser`

## Load fixtures
`docker-compose run web python manage.py loaddata <fixturename>`

## Create fixtures from database
`docker-compose run web python manage.py dumpdata <module.table> --format=yaml > <file.yml>`

# Translation

## Generate po file
`docker-compose run web django-admin makemessages -l <lang_code>`

## Compile messages
`docker-compose run web django-admin compilemessages`

# Run to develop
1. Config Django server (in files .run/);
2. Start Django server in debug mode;

# Production

## Build server
`docker-compose -f docker-compose-prod.yml build`

## Start server
`docker-compose -f docker-compose-prod.yml up -d`

## Create folders
`mkdir logs`
`mkdir data`

## Migrate
`docker-compose -f docker-compose-prod.yml run web python manage.py migrate`

## Create Admin superuser
`docker-compose -f docker-compose-prod.yml run web python manage.py createsuperuser`

## Load fixtures
`docker-compose -f docker-compose-prod.yml run web python manage.py loaddata <fixturename>`

## Start bot as a daemon
`docker-compose -f docker-compose-prod.yml run -d web nohup python3 manage.py start_bot &`

## Stop bot (do it if have multiple containers with bot)
`docker-compose -f docker-compose-prod.yml ps`
`docker stop <container_id>`

## Start DB backup
`docker-compose -f /root/gavka_assistant_bot/docker-compose-prod.yml run web ./pg_backup_rotated.sh`

## Start actions
`docker-compose -f /root/gavka_assistant_bot/docker-compose-prod.yml run web nohup python3 manage.py google_keep create_today_todo`
-- once a day, in morning.

`docker-compose -f /root/gavka_assistant_bot/docker-compose-prod.yml run web nohup python3 manage.py google_keep todo_reminder`
-- every 1-2 hours.

# ToDo
- make visible then model is not saved
- add validation for chat_id (is group or channel) & download_chat_id (is chat)
- create script to remove abandoned files from now-play-audio

# Develop

## Commands

### Start bot
> docker-compose run web python manage.py start_bot

### Format raw files
> docker-compose run web python manage.py format_raw_files

### Broadcast
> docker-compose run web python manage.py broadcast

# Production

## Commands

### Build server
> docker-compose -f docker-compose-prod.yml build

### Start server
> docker-compose -f docker-compose-prod.yml up -d

### Create folders
> mkdir logs
> mkdir data
> mkdir downloads

### Migrate
> docker-compose -f docker-compose-prod.yml run web python manage.py migrate

### Create Admin superuser
> docker-compose -f docker-compose-prod.yml run web python manage.py createsuperuser

### Load fixtures
> docker-compose -f docker-compose-prod.yml run web python manage.py loaddata <fixturename>
Data:
- auth (only if don't Create Admin superuser)
- data_init

### Start bot
> docker-compose -f docker-compose-prod.yml run web python manage.py start_bot

#### Start as a daemon:
> docker-compose -f docker-compose-prod.yml run -d web python manage.py start_bot &

### Format raw files
> docker-compose -f docker-compose-prod.yml run web python manage.py format_raw_files

#### Start as a daemon:
> docker-compose -f docker-compose-prod.yml run -d web python manage.py format_raw_files &

### Broadcast
> docker-compose -f docker-compose-prod.yml run web python manage.py broadcast

#### Start as a daemon:
> docker-compose -f docker-compose-prod.yml run -d web python manage.py broadcast &

## Stop bot (do it if have multiple containers with bot)
> docker-compose -f docker-compose-prod.yml ps
> docker stop <container_id>
> docker ps
> docker-compose -f docker-compose-prod.yml stop

## Start DB backup
> docker-compose -f /root/radio_bot/docker-compose-prod.yml run web ./pg_backup_rotated.sh

## SSH
> ssh root@185.65.245.119

## Devops

### Top
> top

Some other useful commands while top is running include:

    M – sort task list by memory usage
    P – sort task list by processor usage
    N – sort task list by process ID
    T – sort task list by run time
    m – visual mode change

### Docker stats
> docker stats --no-trunc

### Net stats

#### nload
> nload
