"""
Catálogo de retos seleccionables (ver docs/dia-8-retos-owasp.md y
docs/dia-9-owasp-top-10-completo.md). Cubre las diez categorías del
OWASP Top 10 (2021), clasificadas por dificultad.

El cliente solo envía el `slug`; la imagen real vive acá, nunca en el
request, para que nadie pueda pedirle a la plataforma que arranque una
imagen arbitraria del host.

Todos los retos comparten el mismo patrón de aislamiento (ver
`challenges/_base/Dockerfile`): la consola corre como un usuario sin
privilegios (`retador`), y el dato sensible (flag, credenciales, base)
es de `root`, modo 600. La única forma de llegar a él es a través del
comando exacto que el `sudo` del reto permite ejecutar como root —
explotando la vulnerabilidad, no leyendo el archivo directo.
"""

DIFICULTADES = ("basico", "intermedio", "dificil")

CHALLENGES = {
    "injection-sqli": {
        "name": "Login vulnerable",
        "owasp": "A03:2021 - Injection",
        "difficulty": "basico",
        "image": "ctf-reto-injection-sqli:latest",
        "description": (
            "Un portal de acceso arma la consulta SQL concatenando texto "
            "sin sanitizar. Iniciá sesión como admin sin conocer su clave. "
            "Corré: sudo python3 /app/app.py"
        ),
    },
    "idor": {
        "name": "Pedidos sin control de acceso",
        "owasp": "A01:2021 - Broken Access Control",
        "difficulty": "basico",
        "image": "ctf-reto-idor:latest",
        "description": (
            "Un CLI de pedidos muestra cualquier pedido por ID sin "
            "comprobar que sea tuyo. Encontrá el que no te pertenece. "
            "Corré: sudo python3 /app/pedidos.py <id>"
        ),
    },
    "crypto-debil": {
        "name": "Credenciales con MD5 sin sal",
        "owasp": "A02:2021 - Cryptographic Failures",
        "difficulty": "basico",
        "image": "ctf-reto-crypto-debil:latest",
        "description": (
            "Las claves se guardan con MD5 sin sal. La de admin es débil "
            "y está en tu wordlist. Corré: "
            "sudo python3 /app/login.py admin <clave>"
        ),
    },
    "misconfig": {
        "name": "Backup de configuración olvidado",
        "owasp": "A05:2021 - Security Misconfiguration",
        "difficulty": "basico",
        "image": "ctf-reto-misconfig:latest",
        "description": (
            "Quedó un backup del config legible por cualquiera en tu "
            "carpeta. Encontralo y usá esas credenciales. Corré: "
            "sudo python3 /app/panel.py <usuario> <clave>"
        ),
    },
    "diseno-inseguro": {
        "name": "Cupón sin límite de usos",
        "owasp": "A04:2021 - Insecure Design",
        "difficulty": "intermedio",
        "image": "ctf-reto-diseno-inseguro:latest",
        "description": (
            "Un cupón de descuento se puede aplicar tantas veces como "
            "quieras en la misma compra: nadie diseñó un límite de uso. "
            "Corré: sudo python3 /app/tienda.py <codigo> <codigo> ..."
        ),
    },
    "componente-vulnerable": {
        "name": "Calculadora con eval() sin sandbox",
        "owasp": "A06:2021 - Vulnerable and Outdated Components",
        "difficulty": "intermedio",
        "image": "ctf-reto-componente-vulnerable:latest",
        "description": (
            "libcalc 1.4.2 evalúa expresiones sin sandbox (CVE público, "
            "corregido en 2.0.0). Corré: "
            "sudo python3 /app/calculadora.py '<expresion>'"
        ),
    },
    "auth-fallas": {
        "name": "Caja fuerte sin límite de intentos",
        "owasp": "A07:2021 - Identification and Authentication Failures",
        "difficulty": "intermedio",
        "image": "ctf-reto-auth-fallas:latest",
        "description": (
            "Un PIN de 4 dígitos protege la caja fuerte, sin bloqueo ni "
            "demora entre intentos. Corré: "
            "sudo python3 /app/caja_fuerte.py <pin>"
        ),
    },
    "logging-fallas": {
        "name": "Token filtrado en un log sin monitoreo",
        "owasp": "A09:2021 - Security Logging and Monitoring Failures",
        "difficulty": "intermedio",
        "image": "ctf-reto-logging-fallas:latest",
        "description": (
            "Hay tokens de sesión en texto plano en un log que nadie "
            "revisa ni rota. Encontrá el del admin. Corré: "
            "sudo python3 /app/portal.py <token>"
        ),
    },
    "integridad-datos": {
        "name": "Backup deserializado sin verificar",
        "owasp": "A08:2021 - Software and Data Integrity Failures",
        "difficulty": "dificil",
        "image": "ctf-reto-integridad-datos:latest",
        "description": (
            "Un revisor de backups deserializa con pickle cualquier "
            "archivo que dejes en /tmp/backup.dat, sin verificar nada. "
            "Corré: sudo python3 /app/revisar_backup.py"
        ),
    },
    "ssrf": {
        "name": "Vista previa con lista negra sensible a mayúsculas",
        "owasp": "A10:2021 - Server-Side Request Forgery",
        "difficulty": "dificil",
        "image": "ctf-reto-ssrf:latest",
        "description": (
            "Un generador de vistas previas bloquea un recurso interno, "
            "pero compara el host tal cual, sin normalizar mayúsculas. "
            "Corré: sudo python3 /app/previsualizar.py <url>"
        ),
    },
}

DEFAULT_CHALLENGE = "injection-sqli"


def get_challenge(slug: str) -> dict | None:
    return CHALLENGES.get(slug)


def list_challenges() -> list[dict]:
    return [{"slug": slug, **datos} for slug, datos in CHALLENGES.items()]
