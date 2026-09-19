from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ctf', '0005_platformsettings_time_limit_basico_seconds_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='instance',
            name='failed_flag_attempts',
            field=models.PositiveIntegerField(default=0),
        ),
    ]
