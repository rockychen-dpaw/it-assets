# Generated by Django 2.2.9 on 2020-02-13 02:26

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('github', '0045_excludedvalue_repositories'),
    ]

    operations = [
        migrations.AlterField(
            model_name='leakrule',
            name='category',
            field=models.SmallIntegerField(choices=[(1, 'Database URL'), (2, 'Env File'), (3, 'Credential'), (4, 'File'), (4, 'Useless File')]),
        ),
    ]
