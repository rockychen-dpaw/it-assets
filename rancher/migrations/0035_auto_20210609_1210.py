# Generated by Django 2.2.21 on 2021-06-09 04:10

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rancher', '0034_auto_20210608_0846'),
    ]

    operations = [
        migrations.AddField(
            model_name='containerimage',
            name='unknowns',
            field=models.SmallIntegerField(default=0, editable=False),
        ),
        migrations.AddField(
            model_name='operatingsystem',
            name='unknowns',
            field=models.SmallIntegerField(default=0, editable=False),
        ),
        migrations.AlterField(
            model_name='containerimage',
            name='scan_status',
            field=models.SmallIntegerField(choices=[(0, 'Not Scan'), (-1, 'Scan Failed'), (-2, 'Parse Failed'), (1, 'No Risk'), (2, 'Low Risk'), (4, 'Medium Risk'), (8, 'High Risk'), (16, 'Critical Risk'), (32, 'Unknown Risk')], db_index=True, default=0, editable=False),
        ),
        migrations.AlterField(
            model_name='vulnerability',
            name='severity',
            field=models.SmallIntegerField(choices=[(2, 'Low'), (4, 'Medium'), (8, 'High'), (16, 'Critical'), (32, 'Unknown')], db_index=True, editable=False),
        ),
    ]
