# Generated by Django 2.2.9 on 2020-01-27 23:37

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('github', '0012_auto_20200124_1506'),
    ]

    operations = [
        migrations.AddField(
            model_name='leakrule',
            name='content_match',
            field=models.BooleanField(default=True),
        ),
    ]
