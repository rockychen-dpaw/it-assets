# Generated by Django 2.2.21 on 2021-05-25 06:46

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rancher', '0027_auto_20210525_1437'),
    ]

    operations = [
        migrations.AlterField(
            model_name='vulnerability',
            name='description',
            field=models.TextField(editable=False, null=True),
        ),
    ]
