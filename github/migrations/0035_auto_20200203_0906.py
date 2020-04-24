# Generated by Django 2.2.9 on 2020-02-03 01:06

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('github', '0034_auto_20200203_0827'),
    ]

    operations = [
        migrations.RenameField(
            model_name='branch',
            old_name='last_history_scaned',
            new_name='last_scaned',
        ),
        migrations.RenameField(
            model_name='branch',
            old_name='last_scaned_history_commit',
            new_name='last_scaned_commit',
        ),
        migrations.RenameField(
            model_name='branch',
            old_name='history_scaned',
            new_name='scaned',
        ),
        migrations.RemoveField(
            model_name='repository',
            name='last_scaned',
        ),
        migrations.RemoveField(
            model_name='repository',
            name='scaned',
        ),
        migrations.AlterUniqueTogether(
            name='scanstatus',
            unique_together={('rule', 'repository', 'branch', 'start_commit')},
        ),
    ]
