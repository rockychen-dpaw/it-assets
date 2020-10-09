# Generated by Django 2.2.16 on 2020-09-16 02:22

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('rancher', '0013_auto_20200911_1532'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='containerlog',
            unique_together=set(),
        ),
        migrations.AlterIndexTogether(
            name='containerlog',
            index_together={('container', 'level'), ('archiveid',), ('container', 'logtime', 'level')},
        ),
    ]