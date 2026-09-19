"""
Catálogo de retos seleccionables (ver docs/dia-8-retos-owasp.md,
docs/dia-9-owasp-top-10-completo.md y docs/dia-10-guia-de-reto.md).
Cubre las diez categorías del OWASP Top 10 (2021), clasificadas por
dificultad.

El cliente solo envía el `slug`; la imagen real vive acá, nunca en el
request, para que nadie pueda pedirle a la plataforma que arranque una
imagen arbitraria del host.

Todos los retos comparten el mismo patrón de aislamiento (ver
`challenges/_base/Dockerfile`): la consola corre como un usuario sin
privilegios (`retador`), y el dato sensible (flag, credenciales, base)
es de `root`, modo 600. La única forma de llegar a él es a través del
comando exacto que el `sudo` del reto permite ejecutar como root —
explotando la vulnerabilidad, no leyendo el archivo directo.

Cada entrada tiene, además de la descripción de la falla:
- `objective`: qué hay que lograr (el objetivo concreto, no la teoría).
- `first_step`: el comando exacto para arrancar y ver el comportamiento
  normal de la app, antes de intentar explotar nada.
- `expected_result`: qué se ve al correr `first_step` sin explotar
  todavía nada, para que quien lo use sepa si va por buen camino o si
  algo salió distinto a lo esperado.
"""

DIFICULTADES = ("basico", "intermedio", "dificil")

XP_VALUES = {
    "basico": 100,
    "intermedio": 250,
    "dificil": 500,
}

# Vida máxima absoluta según la dificultad del reto (ver Día 15): un
# reto básico no necesita las mismas dos horas que uno difícil, así que
# el techo de tiempo (ver ctf/watchdog.py) ahora depende de cuál sea.
TIME_LIMITS = {
    "basico": 5 * 60,
    "intermedio": 10 * 60,
    "dificil": 15 * 60,
}

CHALLENGES = {
    "injection-sqli": {
        "name": "Login vulnerable",
        "owasp": "A03:2021 - Injection",
        "difficulty": "basico",
        "xp": 100,
        "flag": "FLAG{injection_bypassa_el_login_sin_clave}",
        "image": "ctf-reto-injection-sqli:latest",
        "description": (
            "Un portal de acceso arma la consulta SQL concatenando texto "
            "sin sanitizar."
        ),
        "objective": "Iniciar sesión como admin sin conocer su clave.",
        "first_step": "sudo python3 /app/app.py",
        "expected_result": (
            "Te pide usuario y clave. Si pruebas con datos normales (por "
            "ejemplo invitado / invitado123) entras como invitado, sin "
            "flag. El truco está en qué escribes en el campo usuario."
        ),
    },
    "idor": {
        "name": "Pedidos sin control de acceso",
        "owasp": "A01:2021 - Broken Access Control",
        "difficulty": "basico",
        "xp": 100,
        "flag": "FLAG{idor_nunca_confies_en_el_id_del_cliente}",
        "image": "ctf-reto-idor:latest",
        "description": (
            "Un CLI de pedidos muestra cualquier pedido por ID sin "
            "comprobar que sea tuyo."
        ),
        "objective": "Encontrar un pedido que no es tuyo.",
        "first_step": "sudo python3 /app/pedidos.py 1001",
        "expected_result": (
            "Vas a ver TU pedido (el de \"invitado\"). Nada te impide "
            "pedir otros números de ID -- prueba algunos hasta encontrar "
            "uno que no sea de \"invitado\"."
        ),
    },
    "crypto-debil": {
        "name": "Credenciales con MD5 sin sal",
        "owasp": "A02:2021 - Cryptographic Failures",
        "difficulty": "basico",
        "xp": 100,
        "flag": "FLAG{md5_sin_sal_se_rompe_con_una_wordlist}",
        "image": "ctf-reto-crypto-debil:latest",
        "description": "Las claves se guardan con MD5 sin sal.",
        "objective": "Iniciar sesión como admin usando tu wordlist.",
        "first_step": "sudo python3 /app/login.py admin 123456",
        "expected_result": (
            "Dice \"Clave incorrecta\" (123456 no es la clave real). Tu "
            "wordlist está en ~/wordlist.txt -- prueba cada clave de ahí "
            "hasta que una funcione."
        ),
    },
    "misconfig": {
        "name": "Backup de configuración olvidado",
        "owasp": "A05:2021 - Security Misconfiguration",
        "difficulty": "basico",
        "xp": 100,
        "flag": "FLAG{el_backup_que_nadie_borro_tenia_las_claves}",
        "image": "ctf-reto-misconfig:latest",
        "description": "Quedó un backup del config legible por cualquiera.",
        "objective": "Encontrar credenciales filtradas y usarlas para entrar.",
        "first_step": "ls -la ~",
        "expected_result": (
            "Vas a ver un archivo en tu carpeta que no debería estar ahí "
            "(una copia de seguridad de una configuración). Ábrelo -- "
            "adentro están las credenciales que necesitas para el panel."
        ),
    },
    "diseno-inseguro": {
        "name": "Cupón sin límite de usos",
        "owasp": "A04:2021 - Insecure Design",
        "difficulty": "intermedio",
        "xp": 250,
        "flag": "FLAG{sin_limite_de_usos_el_cupon_se_aplica_infinito}",
        "image": "ctf-reto-diseno-inseguro:latest",
        "description": (
            "Un cupón de descuento se puede aplicar más de una vez en la "
            "misma compra: nadie diseñó un límite de uso."
        ),
        "objective": "Bajar el saldo pendiente a $0 o menos.",
        "first_step": "sudo python3 /app/tienda.py BIENVENIDA10",
        "expected_result": (
            "El saldo baja $10 (empieza en $50). El comando acepta más "
            "de un código en la misma línea, separados por espacio -- "
            "nada te impide repetir el mismo."
        ),
    },
    "componente-vulnerable": {
        "name": "Calculadora con eval() sin sandbox",
        "owasp": "A06:2021 - Vulnerable and Outdated Components",
        "difficulty": "intermedio",
        "xp": 250,
        "flag": "FLAG{un_eval_sin_sandbox_es_ejecucion_de_codigo_disfrazada}",
        "image": "ctf-reto-componente-vulnerable:latest",
        "description": (
            "libcalc 1.4.2 evalúa expresiones sin sandbox (CVE público, "
            "corregido en la versión 2.0.0)."
        ),
        "objective": "Conseguir que ejecute algo más que una cuenta matemática.",
        "first_step": "sudo python3 /app/calculadora.py '2+2'",
        "expected_result": (
            "Responde \"Resultado: 4\". La expresión no tiene por qué ser "
            "una cuenta -- es Python evaluado tal cual, sin restricción."
        ),
    },
    "auth-fallas": {
        "name": "Caja fuerte sin límite de intentos",
        "owasp": "A07:2021 - Identification and Authentication Failures",
        "difficulty": "intermedio",
        "xp": 250,
        "flag": "FLAG{sin_limite_de_intentos_10000_combinaciones_no_alcanzan}",
        "image": "ctf-reto-auth-fallas:latest",
        "description": (
            "Un PIN de 4 dígitos protege la caja fuerte, sin bloqueo ni "
            "demora entre intentos."
        ),
        "objective": "Encontrar el PIN correcto probando valores.",
        "first_step": "sudo python3 /app/caja_fuerte.py 0000",
        "expected_result": (
            "Dice \"PIN incorrecto\". Como no hay límite de intentos ni "
            "demora, un script que pruebe todas las combinaciones (0000 "
            "a 9999) lo va a encontrar tarde o temprano."
        ),
    },
    "logging-fallas": {
        "name": "Token filtrado en un log sin monitoreo",
        "owasp": "A09:2021 - Security Logging and Monitoring Failures",
        "difficulty": "intermedio",
        "xp": 250,
        "flag": "FLAG{un_token_en_texto_plano_en_un_log_que_nadie_revisa}",
        "image": "ctf-reto-logging-fallas:latest",
        "description": (
            "Hay tokens de sesión en texto plano en un log que nadie "
            "revisa ni rota."
        ),
        "objective": "Usar el token filtrado del admin para autenticarte.",
        "first_step": "cat ~/sesiones.log",
        "expected_result": (
            "Vas a ver líneas con tokens de distintos usuarios. Busca la "
            "línea de \"admin\" y usa ese token con la app."
        ),
    },
    "integridad-datos": {
        "name": "Backup deserializado sin verificar",
        "owasp": "A08:2021 - Software and Data Integrity Failures",
        "difficulty": "dificil",
        "xp": 500,
        "flag": "FLAG{deserializar_sin_verificar_integridad_es_ejecutar_lo_que_sea}",
        "image": "ctf-reto-integridad-datos:latest",
        "description": (
            "Un revisor de backups deserializa con pickle cualquier "
            "archivo que dejes en /tmp/backup.dat, sin verificar nada."
        ),
        "objective": "Conseguir que ejecute un comando tuyo al deserializar el backup.",
        "first_step": "sudo python3 /app/revisar_backup.py",
        "expected_result": (
            "Dice que no hay backup en /tmp/backup.dat todavía. Primero "
            "tienes que crear ese archivo tú mismo con Python, antes de "
            "correr este comando de nuevo."
        ),
    },
    "ssrf": {
        "name": "Vista previa con lista negra sensible a mayúsculas",
        "owasp": "A10:2021 - Server-Side Request Forgery",
        "difficulty": "dificil",
        "xp": 500,
        "flag": "FLAG{una_lista_negra_sensible_a_mayusculas_no_bloquea_nada}",
        "image": "ctf-reto-ssrf:latest",
        "description": (
            "Un generador de vistas previas bloquea un recurso interno, "
            "pero compara el host tal cual, sin normalizar mayúsculas."
        ),
        "objective": "Acceder al recurso interno bloqueado.",
        "first_step": "sudo python3 /app/previsualizar.py http://metadata.ctf.local/token",
        "expected_result": (
            "Dice \"Acceso bloqueado: es un recurso interno\". El bloqueo "
            "compara el texto tal cual como lo escribiste -- prueba "
            "escribir esa misma URL de otra forma."
        ),
    },
}

DEFAULT_CHALLENGE = "injection-sqli"


def get_challenge(slug: str) -> dict | None:
    return CHALLENGES.get(slug)


def time_limit_for(slug: str) -> int:
    """
    Vida máxima absoluta (segundos) para un reto, según su dificultad --
    leída de `PlatformSettings` (editable en `/admin/` o en el panel
    oculto, ver Día 15), no de `TIME_LIMITS` acá arriba (eso solo presta
    los valores por defecto de esos campos, para no repetir los números
    en dos lugares).

    Si el slug no está en el catálogo (ej. una instancia vieja de un
    reto que ya no existe), usa `max_lifetime_seconds` como respaldo.

    Import acá adentro, no arriba del archivo, para no crear un ciclo
    entre `challenges.py` y `models.py` (que a su vez importa de acá).
    """
    from .models import PlatformSettings

    config = PlatformSettings.actual()
    challenge = CHALLENGES.get(slug)
    if challenge:
        return config.time_limit_for_difficulty(challenge["difficulty"])

    return config.max_lifetime_seconds


def validate_flag(slug: str, submitted_flag: str) -> tuple[bool, int]:
    """
    Valida si la bandera entregada coincide con la esperada para el reto.
    Devuelve (es_valida, xp_otorgado).
    """
    challenge = CHALLENGES.get(slug)
    if not challenge:
        return False, 0
    expected = challenge.get("flag", "").strip()
    submitted = (submitted_flag or "").strip()
    if submitted and submitted == expected:
        return True, challenge.get("xp", 100)
    return False, 0


def list_challenges() -> list[dict]:
    # Exponemos toda la metadata y puntos XP, pero NUNCA la flag secreta al frontend
    return [
        {
            "slug": slug,
            "name": datos["name"],
            "owasp": datos["owasp"],
            "difficulty": datos["difficulty"],
            "xp": datos.get("xp", XP_VALUES.get(datos["difficulty"], 100)),
            "time_limit_seconds": time_limit_for(slug),
            "image": datos["image"],
            "description": datos["description"],
            "objective": datos["objective"],
            "first_step": datos["first_step"],
            "expected_result": datos["expected_result"],
        }
        for slug, datos in CHALLENGES.items()
    ]
