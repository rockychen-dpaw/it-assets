# Generated by Django 2.2.9 on 2020-01-24 01:13

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('github', '0010_auto_20200124_0906'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='leakrule',
            name='modified',
        ),
    ]
