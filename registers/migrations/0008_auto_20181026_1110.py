# Generated by Django 2.0.9 on 2018-10-26 03:10

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('registers', '0007_auto_20181023_1338'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='changeapproval',
            name='approver',
        ),
        migrations.RemoveField(
            model_name='changeapproval',
            name='change_request',
        ),
        migrations.AlterField(
            model_name='changerequest',
            name='status',
            field=models.SmallIntegerField(choices=[(0, 'Draft'), (1, 'Submitted for endorsement'), (2, 'Scheduled for CAB'), (3, 'Ready'), (4, 'Complete'), (5, 'Rolled back')], db_index=True, default=0),
        ),
        migrations.DeleteModel(
            name='ChangeApproval',
        ),
    ]
