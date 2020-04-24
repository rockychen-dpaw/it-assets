# Generated by Django 2.2.9 on 2020-02-04 04:24

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('github', '0040_repository_scaned'),
    ]

    operations = [
        migrations.AddField(
            model_name='branch',
            name='base_commit',
            field=models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='github.Commit'),
        ),
    ]
