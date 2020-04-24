# Generated by Django 2.2.9 on 2020-02-03 02:37

import datetime
from django.db import migrations, models
import django.db.models.deletion
from django.utils.timezone import utc


class Migration(migrations.Migration):

    dependencies = [
        ('github', '0035_auto_20200203_0906'),
    ]

    operations = [
        migrations.AddField(
            model_name='branch',
            name='active',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='branch',
            name='last_actived',
            field=models.DateTimeField(auto_now_add=True, default=datetime.datetime(2020, 2, 3, 2, 37, 37, 284995, tzinfo=utc)),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='repository',
            name='active',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='repository',
            name='last_actived',
            field=models.DateTimeField(auto_now_add=True, default=datetime.datetime(2020, 2, 3, 2, 37, 53, 4978, tzinfo=utc)),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='repository',
            name='managed',
            field=models.BooleanField(default=True, editable=False),
        ),
        migrations.AlterField(
            model_name='repository',
            name='account',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='repositories', to='github.Account'),
        ),
    ]
