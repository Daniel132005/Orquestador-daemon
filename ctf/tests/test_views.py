"""
Pruebas unitarias de la API HTTP.

Cubren el ciclo de vida de una instancia y la validacion de banderas.
Todas las llamadas al motor Docker estan sustituidas por dobles de
prueba: lo que se verifica aqui es la logica del orquestador.
"""

import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from ctf import challenges, docker_client
from ctf.models import Instance, SolvedChallenge


class AutenticacionRequeridaTest(TestCase):
    """Ningun endpoint de la API debe responder a un anonimo."""

    ENDPOINTS_GET = [
        "/api/challenges/",
        "/api/instance/status/",
    ]
    ENDPOINTS_POST = [
        "/api/instance/start/",
        "/api/instance/stop/",
        "/api/challenges/submit/",
    ]

    def test_get_sin_sesion_no_devuelve_datos(self):
        for url in self.ENDPOINTS_GET:
            with self.subTest(url=url):
                respuesta = self.client.get(url)
                self.assertIn(respuesta.status_code, (302, 401, 403))

    def test_post_sin_sesion_no_ejecuta_nada(self):
        for url in self.ENDPOINTS_POST:
            with self.subTest(url=url):
                respuesta = self.client.post(url, content_type="application/json")
                self.assertIn(respuesta.status_code, (302, 401, 403))

    def test_la_terminal_no_es_publica(self):
        respuesta = self.client.get("/")
        self.assertIn(respuesta.status_code, (302, 401, 403))


class CatalogoAPITest(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user("alumno1", password="secreta123")
        self.client.force_login(self.usuario)

    def test_devuelve_los_diez_retos(self):
        respuesta = self.client.get("/api/challenges/")
        self.assertEqual(respuesta.status_code, 200)
        datos = respuesta.json()
        self.assertEqual(len(datos["challenges"]), 10)

    def test_no_filtra_ninguna_bandera_al_frontend(self):
        respuesta = self.client.get("/api/challenges/")
        self.assertNotIn("FLAG{", respuesta.content.decode("utf-8"))


class DespliegueInstanciaTest(TestCase):
    """POST /api/instance/start/ con Docker sustituido."""

    def setUp(self):
        self.usuario = User.objects.create_user("alumno1", password="secreta123")
        self.client.force_login(self.usuario)

    def _arrancar(self, slug="injection-sqli"):
        return self.client.post(
            "/api/instance/start/",
            data=json.dumps({"challenge": slug}),
            content_type="application/json",
        )

    @patch("ctf.views.docker_client")
    def test_despliega_y_registra_la_instancia(self, docker):
        docker.create_network.return_value = "net123"
        docker.create_container.return_value = "cont456"

        respuesta = self._arrancar()

        self.assertEqual(respuesta.status_code, 201)
        self.assertEqual(Instance.objects.count(), 1)
        instancia = Instance.objects.get()
        self.assertEqual(instancia.container_id, "cont456")
        self.assertEqual(instancia.user, self.usuario)
        docker.start_container.assert_called_once_with("cont456")

    @patch("ctf.views.docker_client")
    def test_inyecta_la_bandera_del_estudiante_en_el_contenedor(self, docker):
        docker.create_network.return_value = "net123"
        docker.create_container.return_value = "cont456"

        self._arrancar("idor")

        esperada = challenges.generate_dynamic_flag(self.usuario.id, "idor")
        docker.inject_challenge_flag.assert_called_once_with(
            "cont456", "idor", esperada
        )

    @patch("ctf.views.docker_client")
    def test_la_red_es_exclusiva_del_usuario(self, docker):
        docker.create_network.return_value = "net123"
        docker.create_container.return_value = "cont456"

        self._arrancar()

        nombre_red = docker.create_network.call_args[0][0]
        self.assertTrue(nombre_red.startswith("ctf-net-%d-" % self.usuario.pk))

    @patch("ctf.views.docker_client")
    def test_rechaza_una_segunda_instancia_del_mismo_usuario(self, docker):
        docker.create_network.return_value = "net123"
        docker.create_container.return_value = "cont456"
        self._arrancar()

        respuesta = self._arrancar()

        self.assertEqual(respuesta.status_code, 409)
        self.assertEqual(Instance.objects.count(), 1)

    @patch("ctf.views.docker_client")
    def test_rechaza_un_reto_inexistente(self, docker):
        respuesta = self._arrancar("reto-fantasma")

        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(Instance.objects.count(), 0)
        docker.create_network.assert_not_called()

    @patch("ctf.views.docker_client")
    def test_si_docker_falla_no_deja_recursos_colgados(self, docker):
        """Sin limpieza, quedarian red y contenedor sin fila que los reclame."""
        docker.DockerClientError = docker_client.DockerClientError
        docker.create_network.return_value = "net123"
        docker.create_container.return_value = "cont456"
        docker.start_container.side_effect = docker_client.DockerClientError("boom")

        respuesta = self._arrancar()

        self.assertEqual(respuesta.status_code, 502)
        self.assertEqual(Instance.objects.count(), 0)
        docker.remove_container.assert_called_once_with("cont456")
        docker.remove_network.assert_called_once_with("net123")


class DetenerInstanciaTest(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user("alumno1", password="secreta123")
        self.client.force_login(self.usuario)

    def _crear_instancia(self):
        return Instance.objects.create(
            user=self.usuario,
            challenge="injection-sqli",
            container_id="cont456",
            network_id="net123",
            network_name="ctf-net-1-abc",
        )

    @patch("ctf.views.docker_client")
    def test_destruye_contenedor_red_y_fila(self, docker):
        self._crear_instancia()

        respuesta = self.client.post("/api/instance/stop/")

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(Instance.objects.count(), 0)
        docker.destroy_instance.assert_called_once_with("cont456", "net123")

    @patch("ctf.views.docker_client")
    def test_sin_instancia_activa_responde_404(self, docker):
        respuesta = self.client.post("/api/instance/stop/")

        self.assertEqual(respuesta.status_code, 404)
        docker.destroy_instance.assert_not_called()

    @patch("ctf.views.docker_client")
    def test_si_docker_falla_conserva_la_fila(self, docker):
        docker.DockerClientError = docker_client.DockerClientError
        docker.destroy_instance.side_effect = docker_client.DockerClientError("caido")
        self._crear_instancia()

        respuesta = self.client.post("/api/instance/stop/")

        self.assertEqual(respuesta.status_code, 502)
        self.assertEqual(Instance.objects.count(), 1)


class EnvioBanderaTest(TestCase):
    """POST /api/challenges/submit/ - validacion, XP y limite de intentos."""

    SLUG = "injection-sqli"

    def setUp(self):
        self.usuario = User.objects.create_user("alumno1", password="secreta123")
        self.client.force_login(self.usuario)
        self.instancia = Instance.objects.create(
            user=self.usuario,
            challenge=self.SLUG,
            container_id="cont456",
            network_id="net123",
            network_name="ctf-net-1-abc",
        )

    def _enviar(self, flag, slug=None):
        cuerpo = {"flag": flag}
        if slug:
            cuerpo["slug"] = slug
        return self.client.post(
            "/api/challenges/submit/",
            data=json.dumps(cuerpo),
            content_type="application/json",
        )

    def _mi_flag(self, slug=None):
        return challenges.generate_dynamic_flag(self.usuario.id, slug or self.SLUG)

    def test_bandera_correcta_registra_el_reto_resuelto(self):
        respuesta = self._enviar(self._mi_flag())

        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(
            SolvedChallenge.objects.filter(
                user=self.usuario, challenge_slug=self.SLUG
            ).exists()
        )

    def test_bandera_de_otro_estudiante_no_sirve(self):
        otro = User.objects.create_user("alumno2", password="x")
        flag_ajena = challenges.generate_dynamic_flag(otro.id, self.SLUG)

        respuesta = self._enviar(flag_ajena)

        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(SolvedChallenge.objects.count(), 0)

    def test_bandera_vacia_se_rechaza_sin_gastar_intento(self):
        respuesta = self._enviar("")

        self.assertEqual(respuesta.status_code, 400)
        self.instancia.refresh_from_db()
        self.assertEqual(self.instancia.failed_flag_attempts, 0)

    def test_resolver_dos_veces_no_duplica_el_progreso(self):
        self._enviar(self._mi_flag())
        self._enviar(self._mi_flag())

        self.assertEqual(SolvedChallenge.objects.count(), 1)

    def test_cada_fallo_descuenta_un_intento(self):
        respuesta = self._enviar("FLAG{incorrecta}")

        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(respuesta.json()["attempts_left"], 4)
        self.instancia.refresh_from_db()
        self.assertEqual(self.instancia.failed_flag_attempts, 1)

    @patch("ctf.views.docker_client")
    def test_al_quinto_fallo_destruye_la_instancia(self, docker):
        """Corta la fuerza bruta de banderas y libera el contenedor."""
        for _ in range(4):
            self._enviar("FLAG{incorrecta}")

        self.assertEqual(Instance.objects.count(), 1)

        respuesta = self._enviar("FLAG{incorrecta}")

        self.assertEqual(respuesta.status_code, 400)
        self.assertTrue(respuesta.json()["instance_destroyed"])
        self.assertEqual(Instance.objects.count(), 0)
        docker.destroy_instance.assert_called_once_with("cont456", "net123")

    @patch("ctf.views.docker_client")
    def test_redesplegar_reinicia_el_contador_de_intentos(self, docker):
        docker.create_network.return_value = "net999"
        docker.create_container.return_value = "cont999"
        for _ in range(3):
            self._enviar("FLAG{incorrecta}")
        self.instancia.refresh_from_db()
        self.assertEqual(self.instancia.failed_flag_attempts, 3)

        self.client.post("/api/instance/stop/")
        self.client.post(
            "/api/instance/start/",
            data=json.dumps({"challenge": self.SLUG}),
            content_type="application/json",
        )

        nueva = Instance.objects.get()
        self.assertEqual(nueva.failed_flag_attempts, 0)

    def test_reto_inexistente_responde_404(self):
        respuesta = self._enviar("FLAG{x}", slug="reto-fantasma")
        self.assertEqual(respuesta.status_code, 404)

    def test_json_invalido_se_rechaza(self):
        respuesta = self.client.post(
            "/api/challenges/submit/",
            data="esto no es json",
            content_type="application/json",
        )
        self.assertEqual(respuesta.status_code, 400)
