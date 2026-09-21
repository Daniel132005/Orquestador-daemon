"""
Pruebas unitarias del catalogo de retos y del sistema de banderas dinamicas.

Cubre el requisito de que cada estudiante reciba una bandera propia,
infalsificable y no reutilizable por otro estudiante.
"""

from django.test import TestCase

from ctf import challenges


class CatalogoRetosTest(TestCase):
    """El catalogo debe cubrir el OWASP Top 10 completo y estar bien formado."""

    CAMPOS_OBLIGATORIOS = (
        "name",
        "owasp",
        "difficulty",
        "image",
        "description",
        "objective",
        "first_step",
        "expected_result",
    )

    def test_el_catalogo_tiene_diez_retos(self):
        self.assertEqual(len(challenges.CHALLENGES), 10)

    def test_cada_reto_cubre_una_categoria_owasp_distinta(self):
        categorias = [r["owasp"] for r in challenges.CHALLENGES.values()]
        self.assertEqual(
            len(set(categorias)),
            10,
            "Hay categorias OWASP repetidas: el Top 10 no queda cubierto entero",
        )

    def test_todos_los_retos_declaran_los_campos_obligatorios(self):
        for slug, reto in challenges.CHALLENGES.items():
            for campo in self.CAMPOS_OBLIGATORIOS:
                with self.subTest(reto=slug, campo=campo):
                    self.assertIn(campo, reto)
                    self.assertTrue(str(reto[campo]).strip())

    def test_todas_las_dificultades_son_validas(self):
        validas = set(challenges.XP_VALUES)
        for slug, reto in challenges.CHALLENGES.items():
            with self.subTest(reto=slug):
                self.assertIn(reto["difficulty"], validas)

    def test_el_reto_por_defecto_existe_en_el_catalogo(self):
        self.assertIn(challenges.DEFAULT_CHALLENGE, challenges.CHALLENGES)

    def test_get_challenge_devuelve_none_si_no_existe(self):
        self.assertIsNone(challenges.get_challenge("reto-inexistente"))


class BanderaDinamicaTest(TestCase):
    """
    La bandera se deriva de SECRET_KEY + user_id + slug. Dos propiedades
    criticas: es estable para el mismo estudiante y es distinta entre
    estudiantes.
    """

    SLUG = "injection-sqli"

    def test_la_bandera_es_determinista_para_el_mismo_usuario(self):
        primera = challenges.generate_dynamic_flag(1, self.SLUG)
        segunda = challenges.generate_dynamic_flag(1, self.SLUG)
        self.assertEqual(primera, segunda)

    def test_la_bandera_cambia_entre_usuarios(self):
        self.assertNotEqual(
            challenges.generate_dynamic_flag(1, self.SLUG),
            challenges.generate_dynamic_flag(2, self.SLUG),
        )

    def test_la_bandera_cambia_entre_retos_del_mismo_usuario(self):
        self.assertNotEqual(
            challenges.generate_dynamic_flag(1, "injection-sqli"),
            challenges.generate_dynamic_flag(1, "ssrf"),
        )

    def test_la_bandera_respeta_el_formato_publicado(self):
        flag = challenges.generate_dynamic_flag(7, self.SLUG)
        self.assertTrue(flag.startswith("FLAG{"))
        self.assertTrue(flag.endswith("}"))
        self.assertIn(self.SLUG, flag)

    def test_todos_los_retos_generan_banderas_distintas_entre_si(self):
        flags = {
            challenges.generate_dynamic_flag(1, slug)
            for slug in challenges.CHALLENGES
        }
        self.assertEqual(len(flags), len(challenges.CHALLENGES))


class ValidacionBanderaTest(TestCase):
    """La validacion solo acepta la bandera propia del estudiante."""

    SLUG = "idor"

    def test_acepta_la_bandera_propia(self):
        flag = challenges.generate_dynamic_flag(42, self.SLUG)
        valida, _ = challenges.validate_flag(self.SLUG, flag, user_id=42)
        self.assertTrue(valida)

    def test_rechaza_la_bandera_de_otro_estudiante(self):
        """Compartir la bandera con un companero no debe servir de nada."""
        flag_ajena = challenges.generate_dynamic_flag(42, self.SLUG)
        valida, _ = challenges.validate_flag(self.SLUG, flag_ajena, user_id=99)
        self.assertFalse(valida)

    def test_rechaza_la_bandera_correcta_de_otro_reto(self):
        flag_otro_reto = challenges.generate_dynamic_flag(42, "ssrf")
        valida, _ = challenges.validate_flag(self.SLUG, flag_otro_reto, user_id=42)
        self.assertFalse(valida)

    def test_rechaza_si_no_se_identifica_al_usuario(self):
        flag = challenges.generate_dynamic_flag(42, self.SLUG)
        valida, _ = challenges.validate_flag(self.SLUG, flag, user_id=None)
        self.assertFalse(valida)

    def test_rechaza_bandera_vacia(self):
        self.assertFalse(challenges.validate_flag(self.SLUG, "", user_id=42)[0])
        self.assertFalse(challenges.validate_flag(self.SLUG, "   ", user_id=42)[0])

    def test_rechaza_reto_inexistente(self):
        self.assertFalse(
            challenges.validate_flag("no-existe", "FLAG{x}", user_id=42)[0]
        )

    def test_ignora_espacios_alrededor_de_la_bandera(self):
        flag = challenges.generate_dynamic_flag(42, self.SLUG)
        valida, _ = challenges.validate_flag(self.SLUG, f"  {flag}  ", user_id=42)
        self.assertTrue(valida)


class ExposicionDeDatosTest(TestCase):
    """El catalogo publico nunca debe filtrar la bandera."""

    def test_list_challenges_no_expone_ninguna_bandera(self):
        for reto in challenges.list_challenges():
            with self.subTest(reto=reto["slug"]):
                serializado = str(reto)
                self.assertNotIn("FLAG{", serializado)
                self.assertNotIn("flag", reto)

    def test_list_challenges_devuelve_todos_los_retos_con_xp(self):
        listado = challenges.list_challenges()
        self.assertEqual(len(listado), len(challenges.CHALLENGES))
        for reto in listado:
            with self.subTest(reto=reto["slug"]):
                self.assertGreater(reto["xp"], 0)
                self.assertGreater(reto["time_limit_seconds"], 0)
