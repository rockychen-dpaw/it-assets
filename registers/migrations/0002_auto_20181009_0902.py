# Generated by Django 2.0.8 on 2018-10-09 01:02

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('registers', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='itsystemevent',
            name='it_systems',
        ),
        migrations.RemoveField(
            model_name='itsystemevent',
            name='locations',
        ),
        migrations.DeleteModel(
            name='ITSystemEvent',
        ),
    ]