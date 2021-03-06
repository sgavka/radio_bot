# Generated by Django 3.2.8 on 2021-11-06 12:29

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AudioFile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('telegram_file_id', models.TextField(blank=True, null=True)),
                ('telegram_unique_id', models.TextField(blank=True, null=True)),
                ('title', models.CharField(blank=True, max_length=255, null=True)),
                ('author', models.CharField(blank=True, max_length=255, null=True)),
                ('file_name', models.CharField(blank=True, max_length=255, null=True)),
                ('duration_seconds', models.IntegerField(blank=True, null=True)),
                ('size', models.IntegerField(blank=True, null=True)),
            ],
        ),
        migrations.CreateModel(
            name='Bot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('username', models.CharField(max_length=255)),
                ('token', models.CharField(max_length=255)),
            ],
        ),
        migrations.CreateModel(
            name='BroadcastUser',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('uid', models.BigIntegerField(blank=True, null=True, unique=True)),
                ('api_id', models.BigIntegerField()),
                ('api_hash', models.CharField(max_length=255)),
                ('phone_number', models.CharField(max_length=255)),
                ('status', models.IntegerField(blank=True, default=0, null=True)),
            ],
        ),
        migrations.CreateModel(
            name='Radio',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('title_template', models.TextField(blank=True, null=True)),
                ('status', models.IntegerField(default=1)),
                ('chat_id', models.BigIntegerField(blank=True, null=True)),
                ('download_chat_id', models.BigIntegerField(blank=True, null=True)),
                ('last_chat_id', models.BigIntegerField(blank=True, null=True)),
                ('last_message_id', models.BigIntegerField(blank=True, null=True)),
                ('broadcast_user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='bot.broadcastuser')),
            ],
        ),
        migrations.CreateModel(
            name='UserToRadio',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('radio', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='bot.radio')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='TelegramUser',
            fields=[
                ('uid', models.BigIntegerField(primary_key=True, serialize=False)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='RadioChat',
            fields=[
                ('uid', models.BigIntegerField(primary_key=True, serialize=False)),
                ('radio', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='bot.radio')),
            ],
        ),
        migrations.CreateModel(
            name='QueueDownloadSoundCloud',
            fields=[
                ('sound_cloud_id', models.BigIntegerField(primary_key=True, serialize=False)),
                ('status', models.IntegerField()),
                ('audio_file', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='bot.audiofile')),
            ],
        ),
        migrations.CreateModel(
            name='Queue',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sort', models.IntegerField()),
                ('datetime_start', models.DateTimeField(blank=True, null=True)),
                ('datetime_is_automatic', models.BooleanField()),
                ('on_air_always', models.BooleanField()),
                ('type', models.IntegerField()),
                ('status', models.IntegerField(default=5)),
                ('audio_file', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='bot.audiofile')),
                ('radio', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='bot.radio')),
            ],
        ),
        migrations.CreateModel(
            name='BroadcastUserOwner',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role', models.IntegerField(default=1)),
                ('broadcast_user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='bot.broadcastuser')),
                ('telegram_user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='bot.telegramuser')),
            ],
        ),
        migrations.CreateModel(
            name='BroadcasterAuthQueue',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('status', models.IntegerField(default=0)),
                ('password', models.CharField(blank=True, max_length=255, null=True)),
                ('code', models.CharField(blank=True, max_length=255, null=True)),
                ('phone_hash', models.CharField(blank=True, max_length=255, null=True)),
                ('broadcast_user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='bot.broadcastuser')),
            ],
        ),
    ]
