# Generated by Django 2.2.14 on 2020-07-06 04:09

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('assets', '0004_auto_20180810_1320'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='hardwareasset',
            name='tracked_computer',
        ),
        migrations.RemoveField(
            model_name='softwareasset',
            name='installations',
        ),
    ]
