"""
Pruebas unitarias de las defensas del sistema.

Dos frentes:

1. Que el orquestador PIDA al kernel el aislamiento correcto. Estas
   pruebas interceptan la peticion que sale hacia el socket de Docker y
   comprueban que lleva todos los limites. Son una red de seguridad
   contra regresiones: si alguien quita PidsLimit o la red interna, la
   suite falla antes de llegar a produccion.
2. Que los endpoints de administracion no sean accesibles para un
   estudiante normal.
"""

import json
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase

from ctf import docker_client


class RespuestaFalsa:
    """Doble de prueba de una respuesta de la Docker Engine API."""

    def __init__(self, status_code=201, payload=None):
        self.status_code = status_code
        self._payload = payload or {"Id": "contenedor-de-prueba"}
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


class CapturaHostConfig:
    """
    Utilidad compartida, NO es un caso de prueba.

    Vive fuera de `TestCase` a proposito: si fuera una clase de prueba, toda
    clase que la heredara volveria a ejecutar sus casos y el total de la
    suite contaria dos veces las mismas verificaciones.
    """

    def _crear_y_capturar(self, **kwargs):
        parametros = {
            "image": "ctf-reto-idor:latest",
            "network_name": "ctf-net-1-abc",
            "mem_limit_bytes": 256 * 1024 * 1024,
            "nano_cpus": 500_000_000,
            "pids_limit": 64,
        }
        parametros.update(kwargs)

        sesion = MagicMock()
        sesion.post.return_value = RespuestaFalsa()
        with patch.object(docker_client, "_session", return_value=sesion):
            docker_client.create_container(**parametros)

        return sesion.post.call_args.kwargs["json"]["HostConfig"]


class LimitesDeRecursosTest(CapturaHostConfig, TestCase):
    """
    El contenedor debe nacer con los limites que el kernel hace cumplir.
    Se captura el JSON enviado al daemon sin necesidad de Docker.
    """

    def test_declara_limite_de_memoria(self):
        host_config = self._crear_y_capturar()
        self.assertEqual(host_config["Memory"], 256 * 1024 * 1024)

    def test_declara_limite_de_cpu(self):
        host_config = self._crear_y_capturar()
        self.assertEqual(host_config["NanoCpus"], 500_000_000)

    def test_declara_limite_de_procesos(self):
        """Sin PidsLimit una fork bomb del estudiante alcanza al host."""
        host_config = self._crear_y_capturar()
        self.assertEqual(host_config["PidsLimit"], 64)

    def test_declara_limite_de_descriptores_de_archivo(self):
        host_config = self._crear_y_capturar()
        ulimits = {u["Name"]: u for u in host_config["Ulimits"]}
        self.assertIn("nofile", ulimits)
        self.assertEqual(ulimits["nofile"]["Soft"], 1024)

    def test_el_contenedor_usa_la_red_del_usuario(self):
        host_config = self._crear_y_capturar(network_name="ctf-net-7-xyz")
        self.assertEqual(host_config["NetworkMode"], "ctf-net-7-xyz")


class EndurecimientoContenedorTest(CapturaHostConfig, TestCase):
    """Privilegios, filesystem y contencion de procesos zombis."""

    def test_descarta_todas_las_capacidades_del_kernel(self):
        host_config = self._crear_y_capturar()
        self.assertEqual(host_config["CapDrop"], ["ALL"])

    def test_solo_devuelve_las_capacidades_minimas_para_sudo(self):
        """
        El diseno de los retos necesita sudo. Se devuelven SETUID y SETGID
        y nada mas: en particular NO se devuelven NET_RAW ni NET_ADMIN.
        """
        host_config = self._crear_y_capturar()
        self.assertEqual(sorted(host_config["CapAdd"]), ["SETGID", "SETUID"])
        self.assertNotIn("NET_RAW", host_config["CapAdd"])
        self.assertNotIn("NET_ADMIN", host_config["CapAdd"])
        self.assertNotIn("SYS_ADMIN", host_config["CapAdd"])

    def test_tmp_esta_en_memoria_sin_ejecucion_ni_setuid(self):
        host_config = self._crear_y_capturar()
        opciones = host_config["Tmpfs"]["/tmp"]
        self.assertIn("noexec", opciones)
        self.assertIn("nosuid", opciones)

    def test_usa_un_init_que_cosecha_procesos_zombis(self):
        """
        Sin esto, una fork bomb deja zombis pegados contra PidsLimit y el
        estudiante no puede volver a usar su propia consola.
        """
        host_config = self._crear_y_capturar()
        self.assertTrue(host_config["Init"])

    def test_acota_el_tamano_de_los_logs_en_disco(self):
        host_config = self._crear_y_capturar()
        self.assertEqual(host_config["LogConfig"]["Config"]["max-size"], "10m")


class AislamientoDeRedTest(TestCase):
    """La red de cada estudiante no debe tener salida ni vecinos."""

    def _crear_red_y_capturar(self, nombre="ctf-net-1-abc"):
        sesion = MagicMock()
        sesion.post.return_value = RespuestaFalsa(payload={"Id": "red-de-prueba"})
        with patch.object(docker_client, "_session", return_value=sesion):
            docker_client.create_network(nombre)
        return sesion.post.call_args.kwargs["json"]

    def test_la_red_es_interna_sin_salida_a_internet(self):
        payload = self._crear_red_y_capturar()
        self.assertTrue(
            payload["Internal"],
            "Sin Internal:true el contenedor sale a internet y ve a otros alumnos",
        )

    def test_la_red_es_de_tipo_bridge(self):
        payload = self._crear_red_y_capturar()
        self.assertEqual(payload["Driver"], "bridge")


class PanelAdministracionTest(TestCase):
    """Los endpoints de staff no pueden quedar expuestos a un estudiante."""

    ENDPOINTS = [
        "/api/platform-settings/",
        "/api/platform-settings/instances/",
        "/api/platform-settings/users/",
    ]

    def setUp(self):
        self.estudiante = User.objects.create_user("alumno1", password="secreta123")
        self.profesor = User.objects.create_user(
            "profe", password="secreta123", is_staff=True
        )

    def test_un_estudiante_no_accede_a_la_configuracion(self):
        self.client.force_login(self.estudiante)
        for url in self.ENDPOINTS:
            with self.subTest(url=url):
                respuesta = self.client.get(url)
                self.assertIn(
                    respuesta.status_code,
                    (302, 401, 403),
                    "Un estudiante no debe leer la configuracion de la plataforma",
                )

    def test_un_estudiante_no_puede_destruir_instancias_ajenas(self):
        self.client.force_login(self.estudiante)
        respuesta = self.client.post(
            "/api/platform-settings/instances/destroy/",
            data=json.dumps({"container_id": "cualquiera"}),
            content_type="application/json",
        )
        self.assertIn(respuesta.status_code, (302, 401, 403))

    def test_un_anonimo_tampoco_accede(self):
        for url in self.ENDPOINTS:
            with self.subTest(url=url):
                respuesta = self.client.get(url)
                self.assertIn(respuesta.status_code, (302, 401, 403))

    def test_el_profesor_si_accede_a_la_configuracion(self):
        self.client.force_login(self.profesor)
        respuesta = self.client.get("/api/platform-settings/")
        self.assertEqual(respuesta.status_code, 200)
