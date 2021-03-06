# Generated by Django 2.2.21 on 2021-05-14 03:45

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('registers', '0001_squashed_0035_auto_20210210_1343'),
    ]

    operations = [
        migrations.AlterField(
            model_name='itsystem',
            name='owner',
            field=models.ForeignKey(blank=True, help_text='IT system owner', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='systems_owned', to='organisation.DepartmentUser', verbose_name='system owner'),
        ),
    ]
