# Generated by Django 3.2.3 on 2021-08-04 21:22

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scoreboard', '0007_auto_20210804_2041'),
    ]

    operations = [
        migrations.AddField(
            model_name='gamerecord',
            name='wallclock',
            field=models.DurationField(null=True),
        ),
        migrations.AlterField(
            model_name='gamerecord',
            name='realtime',
            field=models.DurationField(null=True),
        ),
    ]