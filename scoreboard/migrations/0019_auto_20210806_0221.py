# Generated by Django 3.2.3 on 2021-08-06 02:21

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scoreboard', '0018_auto_20210806_0158'),
    ]

    operations = [
        migrations.AddField(
            model_name='gamerecord',
            name='bonesless',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='gamerecord',
            name='mode',
            field=models.CharField(choices=[('normal', 'Normal'), ('explore', 'Explore'), ('polyinit', 'Polyinit'), ('hah', 'Hah'), ('wizard', 'Wizard')], default='normal', max_length=16),
        ),
        migrations.AddField(
            model_name='gamerecord',
            name='won',
            field=models.BooleanField(default=False),
        ),
    ]