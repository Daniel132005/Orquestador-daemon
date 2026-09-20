from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('ctf', '0008_onboardingstate_tour_visto'),
    ]

    operations = [
        migrations.CreateModel(
            name='InstanceDestructionNotice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('motivo', models.CharField(choices=[('admin', 'Destruida por un administrador'), ('inactividad', 'Destruida por inactividad'), ('vida_maxima', 'Alcanzó su tiempo máximo')], max_length=20)),
                ('challenge_slug', models.CharField(blank=True, default='', max_length=64)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='destruction_notices', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
