from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ctf', '0007_onboardingstate'),
    ]

    operations = [
        migrations.AddField(
            model_name='onboardingstate',
            name='tour_visto',
            field=models.BooleanField(default=False),
        ),
    ]
