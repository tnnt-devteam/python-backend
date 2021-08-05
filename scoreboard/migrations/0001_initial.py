# Generated by Django 3.2.3 on 2021-08-04 17:33

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='GameRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('player_name', models.CharField(max_length=128)),
                ('win', models.BooleanField(default=False)),
                ('variant', models.CharField(max_length=128)),
                ('version', models.CharField(max_length=128)),
            ],
        ),
    ]