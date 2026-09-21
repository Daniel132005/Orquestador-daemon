"""
Pruebas unitarias de los modelos de datos.

Verifican las invariantes que el sistema delega a la base de datos:
una instancia por usuario, configuracion unica (singleton) y progreso
sin duplicados.
"""

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase

from ctf.models import (
    Instance,
    InstanceDestructionNotice,
    PlatformSettings,
    SolvedChallenge,
)


class InstanceTest(TestCase):
    """La regla de negocio 'una instancia activa por estudiante'."""

    def setUp(self):
        self.usuario = User.objects.create_user("alumno1", password="x")

    def _crear_instancia(self, usuario):
        return Instance.objects.create(
            user=usuario,
            challenge="injection-sqli",
            container_id="c" * 64,
            network_id="n" * 64,
            network_name="ctf-net-1-abc",
        )

    def test_un_usuario_no_puede_tener_dos_instancias(self):
        self._crear_instancia(self.usuario)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._crear_instancia(self.usuario)

    def test_dos_usuarios_distintos_pueden_tener_instancia_a_la_vez(self):
        otro = User.objects.create_user("alumno2", password="x")
        self._crear_instancia(self.usuario)
        self._crear_instancia(otro)
        self.assertEqual(Instance.objects.count(), 2)

    def test_el_contador_de_intentos_arranca_en_cero(self):
        instancia = self._crear_instancia(self.usuario)
        self.assertEqual(instancia.failed_flag_attempts, 0)

    def test_borrar_el_usuario_borra_su_instancia(self):
        self._crear_instancia(self.usuario)
        self.usuario.delete()
        self.assertEqual(Instance.objects.count(), 0)


class PlatformSettingsTest(TestCase):
    """Configuracion editable en caliente, con fila unica."""

    def test_actual_crea_la_fila_si_no_existe(self):
        self.assertEqual(PlatformSettings.objects.count(), 0)
        config = PlatformSettings.actual()
        self.assertIsNotNone(config.pk)
        self.assertEqual(PlatformSettings.objects.count(), 1)

    def test_actual_devuelve_siempre_la_misma_fila(self):
        primera = PlatformSettings.actual()
        segunda = PlatformSettings.actual()
        self.assertEqual(primera.pk, segunda.pk)
        self.assertEqual(PlatformSettings.objects.count(), 1)

    def test_limite_de_tiempo_por_dificultad(self):
        config = PlatformSettings.actual()
        config.time_limit_basico_seconds = 300
        config.time_limit_intermedio_seconds = 600
        config.time_limit_dificil_seconds = 900
        config.save()

        self.assertEqual(config.time_limit_for_difficulty("basico"), 300)
        self.assertEqual(config.time_limit_for_difficulty("intermedio"), 600)
        self.assertEqual(config.time_limit_for_difficulty("dificil"), 900)

    def test_dificultad_desconocida_usa_el_limite_basico(self):
        config = PlatformSettings.actual()
        config.time_limit_basico_seconds = 300
        config.save()
        self.assertEqual(config.time_limit_for_difficulty("imposible"), 300)

    def test_el_cambio_se_persiste_sin_reiniciar(self):
        """Simula el ajuste en caliente desde el panel oculto."""
        PlatformSettings.actual()
        config = PlatformSettings.actual()
        config.inactivity_timeout_seconds = 60
        config.save()

        releido = PlatformSettings.actual()
        self.assertEqual(releido.inactivity_timeout_seconds, 60)


class SolvedChallengeTest(TestCase):
    """Progreso y XP acumulado."""

    def setUp(self):
        self.usuario = User.objects.create_user("alumno1", password="x")

    def test_no_se_puede_registrar_dos_veces_el_mismo_reto(self):
        SolvedChallenge.objects.create(
            user=self.usuario, challenge_slug="idor", xp_awarded=100
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SolvedChallenge.objects.create(
                    user=self.usuario, challenge_slug="idor", xp_awarded=100
                )

    def test_dos_usuarios_pueden_resolver_el_mismo_reto(self):
        otro = User.objects.create_user("alumno2", password="x")
        SolvedChallenge.objects.create(
            user=self.usuario, challenge_slug="idor", xp_awarded=100
        )
        SolvedChallenge.objects.create(
            user=otro, challenge_slug="idor", xp_awarded=100
        )
        self.assertEqual(SolvedChallenge.objects.count(), 2)


class InstanceDestructionNoticeTest(TestCase):
    """Aviso de un solo uso sobre por que murio la instancia."""

    def test_los_tres_motivos_estan_disponibles(self):
        motivos = set(InstanceDestructionNotice.Motivo.values)
        self.assertEqual(motivos, {"admin", "inactividad", "vida_maxima"})

    def test_se_puede_registrar_un_aviso(self):
        usuario = User.objects.create_user("alumno1", password="x")
        aviso = InstanceDestructionNotice.objects.create(
            user=usuario,
            motivo=InstanceDestructionNotice.Motivo.INACTIVIDAD,
            challenge_slug="idor",
        )
        self.assertEqual(aviso.motivo, "inactividad")
