"""
Pruebas unitarias del watchdog (destruccion automatica de instancias).

Es la pieza que libera recursos sin intervencion humana. Docker se
sustituye por un doble de prueba: aqui se valida la DECISION de destruir,
no la destruccion fisica (eso lo cubren las pruebas de humo).
"""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from ctf import docker_client, watchdog
from ctf.models import Instance, InstanceDestructionNotice, PlatformSettings


class WatchdogTest(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user("alumno1", password="x")
        config = PlatformSettings.actual()
        config.inactivity_timeout_seconds = 900          # 15 min
        config.time_limit_basico_seconds = 300           # 5 min
        config.time_limit_intermedio_seconds = 600       # 10 min
        config.time_limit_dificil_seconds = 900          # 15 min
        config.save()

    def _crear_instancia(self, usuario=None, challenge="injection-sqli",
                         antiguedad_seg=0, inactividad_seg=0):
        """
        Crea una instancia y reescribe sus marcas de tiempo.

        created_at y last_activity usan auto_now_add, asi que hay que
        forzarlos con un UPDATE directo: asignarlos antes de guardar no
        tendria efecto.
        """
        instancia = Instance.objects.create(
            user=usuario or self.usuario,
            challenge=challenge,
            container_id="c" * 64,
            network_id="n" * 64,
            network_name="ctf-net-test",
        )
        ahora = timezone.now()
        Instance.objects.filter(pk=instancia.pk).update(
            created_at=ahora - timedelta(seconds=antiguedad_seg),
            last_activity=ahora - timedelta(seconds=inactividad_seg),
        )
        return Instance.objects.get(pk=instancia.pk)

    # --- Instancias que deben sobrevivir -----------------------------------

    @patch("ctf.watchdog.docker_client.destroy_instance")
    def test_no_destruye_una_instancia_activa_y_reciente(self, destruir):
        self._crear_instancia(antiguedad_seg=60, inactividad_seg=10)
        destruidas = watchdog.sweep_stale_instances()

        self.assertEqual(destruidas, 0)
        destruir.assert_not_called()
        self.assertEqual(Instance.objects.count(), 1)

    @patch("ctf.watchdog.docker_client.destroy_instance")
    def test_no_destruye_justo_antes_del_umbral(self, destruir):
        """Frontera: 299 s de vida con limite de 300 s todavia sobrevive."""
        self._crear_instancia(antiguedad_seg=299, inactividad_seg=5)
        self.assertEqual(watchdog.sweep_stale_instances(), 0)
        destruir.assert_not_called()

    # --- Destruccion por inactividad ---------------------------------------

    @patch("ctf.watchdog.docker_client.destroy_instance")
    def test_destruye_por_inactividad(self, destruir):
        """
        Aisla la condicion de inactividad: el umbral se baja a 60 s para
        que la instancia muera por abandono y NO por vida maxima (el reto
        dificil tiene 900 s de techo y aqui solo lleva 120 s viva).
        """
        config = PlatformSettings.actual()
        config.inactivity_timeout_seconds = 60
        config.save()

        self._crear_instancia(
            challenge="integridad-datos", antiguedad_seg=120, inactividad_seg=90
        )
        destruidas = watchdog.sweep_stale_instances()

        self.assertEqual(destruidas, 1)
        destruir.assert_called_once()
        self.assertEqual(Instance.objects.count(), 0)

    @patch("ctf.watchdog.docker_client.destroy_instance")
    def test_el_aviso_por_inactividad_lleva_ese_motivo(self, destruir):
        """El motivo registrado debe distinguir abandono de vida maxima."""
        config = PlatformSettings.actual()
        config.inactivity_timeout_seconds = 60
        config.save()

        self._crear_instancia(
            challenge="integridad-datos", antiguedad_seg=120, inactividad_seg=90
        )
        watchdog.sweep_stale_instances()

        aviso = InstanceDestructionNotice.objects.get()
        self.assertEqual(aviso.motivo, InstanceDestructionNotice.Motivo.INACTIVIDAD)

    # --- Destruccion por vida maxima ---------------------------------------

    @patch("ctf.watchdog.docker_client.destroy_instance")
    def test_destruye_por_vida_maxima_aunque_este_activa(self, destruir):
        """
        Caso que motivo el limite absoluto: un bucle que imprime cada
        segundo mantiene last_activity fresco para siempre. La vida
        maxima lo corta igual.
        """
        self._crear_instancia(antiguedad_seg=400, inactividad_seg=2)
        destruidas = watchdog.sweep_stale_instances()

        self.assertEqual(destruidas, 1)
        destruir.assert_called_once()

    @patch("ctf.watchdog.docker_client.destroy_instance")
    def test_la_vida_maxima_depende_de_la_dificultad(self, destruir):
        """350 s mata a un reto basico (300 s) pero no a uno intermedio (600 s)."""
        otro = User.objects.create_user("alumno2", password="x")
        self._crear_instancia(
            challenge="injection-sqli", antiguedad_seg=350, inactividad_seg=5
        )
        self._crear_instancia(
            usuario=otro, challenge="diseno-inseguro",
            antiguedad_seg=350, inactividad_seg=5,
        )

        self.assertEqual(watchdog.sweep_stale_instances(), 1)
        self.assertEqual(Instance.objects.count(), 1)
        self.assertEqual(Instance.objects.first().challenge, "diseno-inseguro")

    @patch("ctf.watchdog.docker_client.destroy_instance")
    def test_reto_fuera_del_catalogo_usa_el_limite_global(self, destruir):
        """Instancia de un reto ya eliminado: no debe quedar viva para siempre."""
        config = PlatformSettings.actual()
        config.max_lifetime_seconds = 100
        config.save()

        self._crear_instancia(
            challenge="reto-que-ya-no-existe", antiguedad_seg=200, inactividad_seg=5
        )
        self.assertEqual(watchdog.sweep_stale_instances(), 1)

    # --- Avisos al estudiante ----------------------------------------------

    @patch("ctf.watchdog.docker_client.destroy_instance")
    def test_deja_aviso_con_el_motivo_correcto(self, destruir):
        self._crear_instancia(antiguedad_seg=400, inactividad_seg=2)
        watchdog.sweep_stale_instances()

        aviso = InstanceDestructionNotice.objects.get()
        self.assertEqual(aviso.motivo, InstanceDestructionNotice.Motivo.VIDA_MAXIMA)
        self.assertEqual(aviso.user, self.usuario)

    # --- Resistencia a fallos de Docker ------------------------------------

    @patch("ctf.watchdog.docker_client.destroy_instance")
    def test_si_docker_falla_no_borra_la_fila(self, destruir):
        """
        Regla critica: borrar la fila con el contenedor aun vivo lo
        convertiria en un huerfano que nadie volveria a reclamar.
        """
        destruir.side_effect = docker_client.DockerClientError("daemon caido")
        self._crear_instancia(antiguedad_seg=400, inactividad_seg=2)

        destruidas = watchdog.sweep_stale_instances()

        self.assertEqual(destruidas, 0)
        self.assertEqual(
            Instance.objects.count(), 1, "La fila debe sobrevivir para reintentar"
        )
        self.assertEqual(InstanceDestructionNotice.objects.count(), 0)

    @patch("ctf.watchdog.docker_client.destroy_instance")
    def test_un_fallo_no_impide_limpiar_las_demas(self, destruir):
        otro = User.objects.create_user("alumno2", password="x")
        destruir.side_effect = [
            docker_client.DockerClientError("fallo puntual"),
            None,
        ]
        self._crear_instancia(antiguedad_seg=400, inactividad_seg=2)
        self._crear_instancia(usuario=otro, antiguedad_seg=400, inactividad_seg=2)

        destruidas = watchdog.sweep_stale_instances()

        self.assertEqual(destruidas, 1)
        self.assertEqual(Instance.objects.count(), 1)

    # --- Barrido masivo ----------------------------------------------------

    @patch("ctf.watchdog.docker_client.destroy_instance")
    def test_barre_varias_instancias_en_una_pasada(self, destruir):
        for i in range(5):
            usuario = User.objects.create_user("masivo%d" % i, password="x")
            self._crear_instancia(usuario=usuario, antiguedad_seg=400, inactividad_seg=2)

        self.assertEqual(watchdog.sweep_stale_instances(), 5)
        self.assertEqual(Instance.objects.count(), 0)
        self.assertEqual(destruir.call_count, 5)

    @patch("ctf.watchdog.docker_client.destroy_instance")
    def test_barrido_sin_instancias_no_falla(self, destruir):
        self.assertEqual(watchdog.sweep_stale_instances(), 0)
        destruir.assert_not_called()
