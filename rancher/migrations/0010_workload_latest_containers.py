# Generated by Django 2.2.14 on 2020-09-03 03:30

import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rancher', '0009_auto_20200903_1102'),
    ]

    operations = [
        migrations.AddField(
            model_name='workload',
            name='latest_containers',
            field=django.contrib.postgres.fields.ArrayField(base_field=models.IntegerField(), editable=False, null=True, size=None),
        ),
    ]
