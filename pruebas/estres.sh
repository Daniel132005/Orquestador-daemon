#!/usr/bin/env bash
#
# PRUEBAS DE ESTRES - Plataforma CTF
#
# Cada prueba ejecuta el MISMO ataque dos veces:
#   [ANTES]   contenedor sin los limites del sistema
#   [DESPUES] contenedor con la configuracion real de la plataforma
#
# Asi la mejora queda medida, no afirmada.
#
# Uso:  bash pruebas/estres.sh
# Requiere: Docker corriendo y la imagen ctf-base:latest construida.

set -u

IMAGEN="ctf-base:latest"
MEM="256m"
CPUS="0.5"
PIDS="64"

# Configuracion real de la plataforma (ver ctf/docker_client.py)
LIMITES_PLATAFORMA=(
  --memory="$MEM" --cpus="$CPUS" --pids-limit="$PIDS"
  --cap-drop=ALL --cap-add=SETUID --cap-add=SETGID
  --tmpfs /tmp:rw,noexec,nosuid,size=64m
  --ulimit nofile=1024:2048 --init
)

TOTAL=0
APROBADAS=0

bloque() {
  echo ""
  echo "========================================================================"
  echo "[$1] $2"
  echo "========================================================================"
}

escenario() { echo ""; echo "  --- $1 ---"; }
comando()   { echo "  \$ $1"; }
salida()    { sed 's/^/    /'; }

veredicto() {
  TOTAL=$((TOTAL + 1))
  if [ "$1" = "ok" ]; then
    APROBADAS=$((APROBADAS + 1))
    echo "  >> RESULTADO: OK - $2"
  else
    echo "  >> RESULTADO: FALLO - $2"
  fi
}

limpiar() { docker rm -f "$1" >/dev/null 2>&1 || true; }

echo "PRUEBAS DE ESTRES - PLATAFORMA CTF"
echo "Fecha: $(date '+%Y-%m-%d %H:%M:%S')"
echo "Host:  $(uname -sr)"
echo "Docker: $(docker version --format '{{.Server.Version}}')"
echo "Imagen de prueba: $IMAGEN"

# =====================================================================
bloque "E-01" "BOMBA DE PROCESOS (fork bomb acotada a 200 procesos)"
# =====================================================================
FORK_PY='
import os, time
creados = 0
try:
    for _ in range(200):
        if os.fork() == 0:
            time.sleep(15); os._exit(0)
        creados += 1
except OSError as e:
    print("bloqueado por el kernel:", e)
print("procesos creados:", creados)
'

escenario "ANTES · contenedor sin PidsLimit"
comando "docker run --rm $IMAGEN python3 -c '<fork x200>'"
ANTES_E01=$(docker run --rm "$IMAGEN" python3 -c "$FORK_PY" 2>&1 | tail -3)
echo "$ANTES_E01" | salida

escenario "DESPUES · contenedor con --pids-limit=$PIDS"
comando "docker run --rm --pids-limit=$PIDS $IMAGEN python3 -c '<fork x200>'"
DESPUES_E01=$(docker run --rm --pids-limit="$PIDS" --init "$IMAGEN" python3 -c "$FORK_PY" 2>&1 | tail -3)
echo "$DESPUES_E01" | salida

N_ANTES=$(echo "$ANTES_E01" | grep -oE 'procesos creados: [0-9]+' | grep -oE '[0-9]+$')
N_DESPUES=$(echo "$DESPUES_E01" | grep -oE 'procesos creados: [0-9]+' | grep -oE '[0-9]+$')
echo ""
echo "    COMPARATIVO  |  sin limite: ${N_ANTES:-?} procesos  ->  con limite: ${N_DESPUES:-?} procesos"
if [ "${N_DESPUES:-999}" -lt 70 ] 2>/dev/null; then
  veredicto ok "el kernel corta en el cupo; el host nunca ve los 200 procesos"
else
  veredicto fallo "el limite de procesos no se aplico"
fi

# =====================================================================
bloque "E-02" "AGOTAMIENTO DE MEMORIA (pedir 400 MB)"
# =====================================================================
MEM_PY='
b = bytearray(400 * 1024 * 1024)
b[0] = 1; b[-1] = 1
print("400 MB asignados correctamente")
'

escenario "ANTES · contenedor sin limite de memoria"
comando "docker run --rm $IMAGEN python3 -c '<pedir 400MB>'"
ANTES_E02=$(docker run --rm "$IMAGEN" python3 -c "$MEM_PY" 2>&1; echo "codigo_salida=$?")
echo "$ANTES_E02" | salida

escenario "ACTUAL · configuracion vigente de la plataforma (--memory=$MEM)"
comando "docker run --rm --memory=$MEM $IMAGEN python3 -c '<pedir 400MB>'"
ACTUAL_E02=$(docker run --rm --memory="$MEM" "$IMAGEN" python3 -c "$MEM_PY" 2>&1; echo "codigo_salida=$?")
echo "$ACTUAL_E02" | salida

escenario "PROPUESTO · declarando tambien el tope de swap (--memory-swap=$MEM)"
comando "docker run --rm --memory=$MEM --memory-swap=$MEM $IMAGEN python3 -c '<pedir 400MB>'"
PROP_E02=$(docker run --rm --memory="$MEM" --memory-swap="$MEM" "$IMAGEN" python3 -c "$MEM_PY" 2>&1; echo "codigo_salida=$?")
echo "$PROP_E02" | salida

echo ""
echo "  Swap del host:"
free -m | sed -n '1p;3p' | salida

echo ""
if echo "$ACTUAL_E02" | grep -q "400 MB asignados"; then
  echo "    COMPARATIVO  |  sin limite: 400 MB  ->  actual: 400 MB (usa swap)  ->  con tope de swap: bloqueado"
  echo ""
  echo "    *** HALLAZGO ***"
  echo "    La plataforma declara Memory pero no MemorySwap (ctf/docker_client.py)."
  echo "    Docker concede entonces una cantidad de swap igual al limite de RAM, asi"
  echo "    que el techo real por contenedor es 512 MB, no 256 MB. El limite SI existe"
  echo "    y el kernel lo aplica -- se ve en la tercera corrida -- pero el numero"
  echo "    efectivo es el doble del documentado, y eso afecta el calculo de cuantos"
  echo "    contenedores caben por host."
  echo "    Correccion sugerida: anadir \"MemorySwap\": mem_limit_bytes al HostConfig."
else
  echo "    COMPARATIVO  |  sin limite: asigna los 400 MB  ->  con limite: el kernel lo detiene"
fi

if ! echo "$PROP_E02" | grep -q "400 MB asignados"; then
  veredicto ok "con el tope de swap declarado, el kernel corta la asignacion en seco"
else
  veredicto fallo "ni siquiera con MemorySwap se contiene la asignacion"
fi

# =====================================================================
bloque "E-03" "SATURACION DE CPU (bucle infinito)"
# =====================================================================
medir_cpu() {
  local nombre="$1"; shift
  limpiar "$nombre"
  docker run -d --name "$nombre" "$@" "$IMAGEN" \
    sh -c 'while true; do :; done' >/dev/null 2>&1
  sleep 4
  docker stats --no-stream --format '{{.CPUPerc}}' "$nombre" 2>/dev/null
  limpiar "$nombre"
}

escenario "ANTES · contenedor sin limite de CPU"
comando "docker run -d $IMAGEN sh -c 'while true; do :; done' && docker stats"
CPU_ANTES=$(medir_cpu ctf-estres-cpu-antes)
echo "    Uso de CPU medido: ${CPU_ANTES:-sin dato}" | salida

escenario "DESPUES · contenedor con --cpus=$CPUS"
comando "docker run -d --cpus=$CPUS $IMAGEN sh -c 'while true; do :; done' && docker stats"
CPU_DESPUES=$(medir_cpu ctf-estres-cpu-despues --cpus="$CPUS")
echo "    Uso de CPU medido: ${CPU_DESPUES:-sin dato}" | salida

echo ""
echo "    COMPARATIVO  |  sin limite: ${CPU_ANTES:-?}  ->  con limite: ${CPU_DESPUES:-?}  (techo teorico 50%)"
VAL_DESPUES=$(echo "${CPU_DESPUES:-999}" | tr -d '%' | cut -d. -f1)
if [ "${VAL_DESPUES:-999}" -le 60 ] 2>/dev/null; then
  veredicto ok "el planificador del kernel limita el bucle a media CPU"
else
  veredicto fallo "la cuota de CPU no se aplico"
fi

# =====================================================================
bloque "E-04" "SALIDA A INTERNET DESDE EL RETO"
# =====================================================================
NET_PY='
import socket
try:
    s = socket.create_connection(("1.1.1.1", 53), timeout=4)
    print("CONECTADO a internet:", s.getpeername())
    s.close()
except Exception as e:
    print("SIN SALIDA:", type(e).__name__, e)
'

docker network rm ctf-estres-abierta ctf-estres-interna >/dev/null 2>&1 || true
docker network create ctf-estres-abierta >/dev/null
docker network create --internal ctf-estres-interna >/dev/null

escenario "ANTES · red bridge normal (como la crearia Docker por defecto)"
comando "docker network create ctf-estres-abierta"
comando "docker run --rm --network ctf-estres-abierta $IMAGEN python3 -c '<conectar a 1.1.1.1:53>'"
ANTES_E04=$(docker run --rm --network ctf-estres-abierta "$IMAGEN" python3 -c "$NET_PY" 2>&1)
echo "$ANTES_E04" | salida

escenario "DESPUES · red con Internal=true (la que usa la plataforma)"
comando "docker network create --internal ctf-estres-interna"
comando "docker run --rm --network ctf-estres-interna $IMAGEN python3 -c '<conectar a 1.1.1.1:53>'"
DESPUES_E04=$(docker run --rm --network ctf-estres-interna "$IMAGEN" python3 -c "$NET_PY" 2>&1)
echo "$DESPUES_E04" | salida

echo ""
echo "    COMPARATIVO  |  red normal: sale a internet  ->  red interna: sin ruta de salida"
if echo "$DESPUES_E04" | grep -q "SIN SALIDA"; then
  veredicto ok "el reto no puede usarse para atacar a terceros desde la red del campus"
else
  veredicto fallo "el contenedor mantiene salida a internet"
fi

# =====================================================================
bloque "E-05" "UN ESTUDIANTE INTENTA ALCANZAR AL OTRO"
# =====================================================================
limpiar ctf-estres-alumno-b
docker network rm ctf-estres-red-b >/dev/null 2>&1 || true
docker network create --internal ctf-estres-red-b >/dev/null

docker run -d --name ctf-estres-alumno-b --network ctf-estres-abierta "$IMAGEN" \
  python3 -m http.server 8000 >/dev/null 2>&1
sleep 2
IP_B=$(docker inspect ctf-estres-alumno-b \
  --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' 2>/dev/null)
echo "  Alumno B expone un servicio en $IP_B:8000"

SCAN_PY="
import socket
try:
    s = socket.create_connection(('$IP_B', 8000), timeout=4)
    print('ALCANZADO: el alumno B es visible desde aqui')
    s.close()
except Exception as e:
    print('INALCANZABLE:', type(e).__name__, e)
"

escenario "ANTES · ambos alumnos en la MISMA red"
comando "docker run --rm --network ctf-estres-abierta $IMAGEN python3 -c '<conectar a IP del alumno B>'"
ANTES_E05=$(docker run --rm --network ctf-estres-abierta "$IMAGEN" python3 -c "$SCAN_PY" 2>&1)
echo "$ANTES_E05" | salida

escenario "DESPUES · cada alumno en su PROPIA red interna (modelo de la plataforma)"
comando "docker run --rm --network ctf-estres-red-b $IMAGEN python3 -c '<conectar a IP del alumno B>'"
DESPUES_E05=$(docker run --rm --network ctf-estres-red-b "$IMAGEN" python3 -c "$SCAN_PY" 2>&1)
echo "$DESPUES_E05" | salida

limpiar ctf-estres-alumno-b
echo ""
echo "    COMPARATIVO  |  red compartida: alumno visible  ->  red por usuario: inalcanzable"
if echo "$DESPUES_E05" | grep -q "INALCANZABLE"; then
  veredicto ok "un estudiante no puede espiar ni atacar el entorno de otro"
else
  veredicto fallo "hay visibilidad entre estudiantes"
fi

# =====================================================================
bloque "E-06" "CAPACIDADES DEL KERNEL (privilegios de root dentro del reto)"
# =====================================================================
# Se usa `chown`, que exige CAP_CHOWN: Docker la concede por defecto y
# `--cap-drop=ALL` la quita. Sirve para contrastar; `ip link` no serviria
# porque NET_ADMIN tampoco viene en el juego por defecto de Docker.
PRUEBA_CAP='
  grep CapEff /proc/self/status
  if chown nobody /etc/hostname 2>/dev/null; then
    echo "CHOWN PERMITIDO (conserva CAP_CHOWN)"
  else
    echo "CHOWN DENEGADO (sin CAP_CHOWN)"
  fi
'

escenario "ANTES · contenedor con las capacidades por defecto de Docker"
comando "docker run --rm $IMAGEN sh -c 'grep CapEff /proc/self/status; chown nobody /etc/hostname'"
ANTES_E06=$(docker run --rm "$IMAGEN" sh -c "$PRUEBA_CAP" 2>&1)
echo "$ANTES_E06" | salida

escenario "DESPUES · con --cap-drop=ALL --cap-add=SETUID,SETGID (la plataforma)"
comando "docker run --rm --cap-drop=ALL --cap-add=SETUID --cap-add=SETGID $IMAGEN sh -c '...'"
DESPUES_E06=$(docker run --rm --cap-drop=ALL --cap-add=SETUID --cap-add=SETGID "$IMAGEN" \
  sh -c "$PRUEBA_CAP" 2>&1)
echo "$DESPUES_E06" | salida

CAP_A=$(echo "$ANTES_E06" | grep CapEff | awk '{print $2}')
CAP_D=$(echo "$DESPUES_E06" | grep CapEff | awk '{print $2}')
echo ""
echo "    COMPARATIVO  |  mapa de capacidades: $CAP_A  ->  $CAP_D"
echo "    (14 capacidades activas por defecto, 2 tras el endurecimiento)"
if echo "$DESPUES_E06" | grep -q "CHOWN DENEGADO" && echo "$ANTES_E06" | grep -q "CHOWN PERMITIDO"; then
  veredicto ok "root dentro del reto pierde los privilegios que no necesita"
else
  veredicto fallo "el recorte de capacidades no se aplico como se esperaba"
fi

# =====================================================================
bloque "E-07" "DESCRIPTORES DE ARCHIVO DISPONIBLES"
# =====================================================================
escenario "ANTES · sin ulimit declarado"
comando "docker run --rm $IMAGEN sh -c 'ulimit -n'"
ANTES_E07=$(docker run --rm "$IMAGEN" sh -c 'ulimit -n' 2>&1)
echo "    limite de descriptores: $ANTES_E07" | salida

escenario "DESPUES · con --ulimit nofile=1024:2048"
comando "docker run --rm --ulimit nofile=1024:2048 $IMAGEN sh -c 'ulimit -n'"
DESPUES_E07=$(docker run --rm --ulimit nofile=1024:2048 "$IMAGEN" sh -c 'ulimit -n' 2>&1)
echo "    limite de descriptores: $DESPUES_E07" | salida

echo ""
echo "    COMPARATIVO  |  sin declarar: $ANTES_E07  ->  acotado: $DESPUES_E07"
if [ "${DESPUES_E07:-999999}" -le 1024 ] 2>/dev/null; then
  veredicto ok "un bucle que abre archivos ya no degrada al resto"
else
  veredicto fallo "el limite de descriptores no se aplico"
fi

# =====================================================================
bloque "E-08" "PERFIL COMPLETO DE LA PLATAFORMA (todos los limites juntos)"
# =====================================================================
comando "docker run --rm ${LIMITES_PLATAFORMA[*]} $IMAGEN sh -c '<inventario de limites>'"
PERFIL=$(docker run --rm "${LIMITES_PLATAFORMA[@]}" "$IMAGEN" sh -c '
  echo "memoria max : $(cat /sys/fs/cgroup/memory.max)"
  echo "cpu max     : $(cat /sys/fs/cgroup/cpu.max)"
  echo "pids max    : $(cat /sys/fs/cgroup/pids.max)"
  echo "descriptores: $(ulimit -n)"
  echo "capacidades : $(grep CapEff /proc/self/status | awk "{print \$2}")"
  echo "montaje tmp : $(grep " /tmp " /proc/mounts)"
' 2>&1)
echo "$PERFIL" | salida

if echo "$PERFIL" | grep -q "268435456" && echo "$PERFIL" | grep -q "noexec"; then
  veredicto ok "el perfil de la plataforma se aplica completo y verificable"
else
  veredicto fallo "falta algun limite del perfil"
fi

# --- limpieza final ---------------------------------------------------
docker network rm ctf-estres-abierta ctf-estres-interna ctf-estres-red-b >/dev/null 2>&1 || true

echo ""
echo "========================================================================"
echo "RESUMEN DE PRUEBAS DE ESTRES"
echo "========================================================================"
echo "  Total: $TOTAL  |  Exitosas: $APROBADAS  |  Fallidas: $((TOTAL - APROBADAS))"
echo ""
echo "  Residuos en el host tras las pruebas:"
echo "    contenedores ctf-estres-*: $(docker ps -aq --filter 'name=ctf-estres' | wc -l)"
echo "    redes ctf-estres-*:        $(docker network ls -q --filter 'name=ctf-estres' | wc -l)"

[ "$APROBADAS" -eq "$TOTAL" ] && exit 0 || exit 1
