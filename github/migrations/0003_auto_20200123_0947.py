# Generated by Django 2.2.9 on 2020-01-23 01:47

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('github', '0002_auto_20200123_0907'),
    ]

    operations = [
        migrations.RenameField(
            model_name='commit',
            old_name='identity',
            new_name='commit_id',
        ),
        migrations.AlterField(
            model_name='account',
            name='parent',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='children', to='github.Account'),
        ),
        migrations.AlterUniqueTogether(
            name='commit',
            unique_together={('repository', 'branch', 'commit_id')},
        ),
    ]
