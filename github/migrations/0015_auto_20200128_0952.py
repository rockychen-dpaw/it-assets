# Generated by Django 2.2.9 on 2020-01-28 01:52

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('github', '0014_leakrule_risk_level'),
    ]

    operations = [
        migrations.AlterField(
            model_name='leak',
            name='line_number',
            field=models.IntegerField(editable=False, null=True),
        ),
    ]
