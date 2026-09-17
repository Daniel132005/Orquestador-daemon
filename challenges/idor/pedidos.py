#!/usr/bin/env python3
"""
CLI de pedidos deliberadamente vulnerable (OWASP A01:2021 - Broken Access
Control / IDOR). Quien lo usa está autenticado como "invitado", pero el
programa nunca comprueba que el pedido consultado le pertenezca: alcanza
con adivinar o incrementar el ID para leer pedidos de otras personas.

Los pedidos viven en un archivo aparte (`pedidos.json`, solo legible por
root) para que la fuente de este script -- que sí es legible -- no
revele el flag con un simple `cat`. Solo se llega al archivo corriendo
esto vía el `sudo` restringido del Dockerfile.
"""

import json
import sys

USUARIO_ACTUAL = "invitado"
PEDIDOS_PATH = "/app/pedidos.json"


def main():
    if len(sys.argv) != 2:
        print(f"uso: {sys.argv[0]} <id_pedido>")
        print(f"(autenticado como: {USUARIO_ACTUAL})")
        sys.exit(1)

    with open(PEDIDOS_PATH) as f:
        pedidos = json.load(f)

    pedido_id = sys.argv[1]
    pedido = pedidos.get(pedido_id)
    if pedido is None:
        print(f"Pedido {pedido_id} no encontrado.")
        return

    # BUG intencional: nunca se compara pedido["cliente"] contra
    # USUARIO_ACTUAL antes de mostrar el contenido.
    print(json.dumps(pedido, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
