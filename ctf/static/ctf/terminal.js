/*
 * Frontend de la consola (ver SDD 4.5).
 *
 * Protocolo del WebSocket: las pulsaciones del usuario viajan como frames
 * BINARIOS (bytes crudos hacia el exec) y los mensajes de control como
 * frames de TEXTO en JSON (por ahora solo `resize`). Así el servidor
 * distingue datos de control sin inventar secuencias de escape.
 *
 * Los indicadores de los rieles reflejan estado real (conexión, protocolo,
 * tamaño del TTY), nunca valores decorativos.
 */

const API = {
  status: "/api/instance/status/",
  start: "/api/instance/start/",
  stop: "/api/instance/stop/",
};

const el = {
  linkDot: document.getElementById("link-dot"),
  linkText: document.getElementById("link-text"),
  protocolNote: document.getElementById("protocol-note"),
  sessionInfo: document.getElementById("session-info"),
  dot: document.getElementById("status-dot"),
  statusText: document.getElementById("status-text"),
  start: document.getElementById("btn-start"),
  stop: document.getElementById("btn-stop"),
  terminal: document.getElementById("terminal"),
  empty: document.getElementById("terminal-empty"),
  state: document.getElementById("info-state"),
  container: document.getElementById("info-container"),
  network: document.getElementById("info-network"),
  created: document.getElementById("info-created"),
  memory: document.getElementById("info-memory"),
  cpu: document.getElementById("info-cpu"),
  pids: document.getElementById("info-pids"),
  timeout: document.getElementById("info-timeout"),
};

let socket = null;
// Distingue un cierre pedido por el usuario (al destruir) de una caída,
// para que el mensaje final no lo pise el handler de `onclose`.
let closingOnPurpose = false;

const term = new Terminal({
  cursorBlink: true,
  convertEol: true,
  fontFamily: '"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
  fontSize: 13,
  theme: {
    background: "#050807",
    foreground: "#d9e6e0",
    cursor: "#3ef0a5",
    selectionBackground: "#1c3830",
    black: "#070a09",
    brightBlack: "#566761",
    green: "#3ef0a5",
    brightGreen: "#5ff7ba",
    red: "#ff6b7a",
    yellow: "#f5b544",
    blue: "#6bb6ff",
    cyan: "#4fd6d2",
    white: "#d9e6e0",
  },
});

const fitAddon = new FitAddon.FitAddon();
term.loadAddon(fitAddon);
term.open(el.terminal);

/*
 * Ctrl+V y Ctrl+Shift+V pegan, como espera cualquiera en un navegador.
 *
 * Hay que interceptarlos a mano porque en una terminal Ctrl+V significa
 * otra cosa: es `quoted-insert` de readline, "insertá el siguiente
 * carácter sin interpretarlo". Sin esta intercepción se comía el marcador
 * de inicio del pegado y el texto aparecía literal, con un `^[[200~`
 * delante.
 *
 * `term.paste()` respeta el modo bracketed paste, así que lo pegado queda
 * esperando a que la persona pulse Enter en lugar de ejecutarse solo.
 */
term.attachCustomKeyEventHandler((evento) => {
  const esPegar =
    evento.type === "keydown" &&
    (evento.ctrlKey || evento.metaKey) &&
    evento.key.toLowerCase() === "v";

  if (!esPegar) return true;

  navigator.clipboard
    .readText()
    .then((texto) => {
      if (texto) term.paste(texto);
    })
    .catch(() => {
      setStatus("El navegador bloqueó el acceso al portapapeles", "warn");
    });

  return false; // no reenviar la tecla al shell
});

function getCookie(name) {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

async function callApi(path, method = "POST") {
  const options = { method };
  if (method === "POST") {
    options.headers = { "X-CSRFToken": getCookie("csrftoken") };
  }
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.error || `Error ${response.status}`);
  }
  return body;
}

function setStatus(text, variant) {
  el.statusText.textContent = text;
  el.dot.className = variant ? `rail-dot is-${variant}` : "rail-dot";
}

function setLink(ok) {
  el.linkDot.className = ok ? "rail-dot is-ok" : "rail-dot is-down";
  el.linkText.textContent = ok ? "Enlace activo" : "Sin enlace";
}

function renderProtocol() {
  el.protocolNote.textContent =
    window.location.protocol === "https:"
      ? "TLS activo // sesión cifrada"
      : "HTTP local // sin cifrar";
}

function renderSessionInfo() {
  el.sessionInfo.textContent = socket
    ? `TTY: ${term.cols}x${term.rows}`
    : "TTY: sin sesión";
}

function formatDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("es", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatTimeout(seconds) {
  const minutes = Math.round(seconds / 60);
  return minutes >= 60
    ? `${(minutes / 60).toFixed(minutes % 60 ? 1 : 0)} h`
    : `${minutes} min`;
}

function renderInfo(status) {
  el.state.innerHTML = status.active
    ? '<span class="chip">Activa</span>'
    : '<span class="chip is-idle">Inactiva</span>';
  el.container.textContent = status.container_id
    ? status.container_id.slice(0, 12)
    : "—";
  el.network.textContent = status.network_name || "—";
  el.created.textContent = formatDate(status.created_at);
  el.memory.textContent = `${status.limits.memory_mb} MB`;
  el.cpu.textContent = `${status.limits.cpus} núcleo${status.limits.cpus === 1 ? "" : "s"}`;
  el.pids.textContent = status.limits.pids;
  el.timeout.textContent = formatTimeout(status.inactivity_timeout_seconds);
}

function showTerminal(visible) {
  el.empty.hidden = visible;
  el.terminal.classList.toggle("is-visible", visible);
  if (visible) {
    fitAddon.fit();
    term.focus();
  }
  renderSessionInfo();
}

function sendResize() {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(
      JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows })
    );
    renderSessionInfo();
  }
}

async function resincronizar() {
  /*
   * La consola se cortó sin que el usuario lo pidiera: o escribió `exit`,
   * o el watchdog destruyó su instancia. Hay que volver a preguntarle al
   * servidor, porque si no la interfaz seguiría mostrando un contenedor
   * inexistente con el botón de desplegar bloqueado, sin salida posible.
   *
   * Se consulta dos veces: al destruir una instancia, el contenedor muere
   * antes de que se borre su fila, así que la primera consulta puede
   * llegar cuando el servidor todavía la reporta activa.
   */
  for (const espera of [0, 3000]) {
    if (espera) await new Promise((r) => setTimeout(r, espera));
    try {
      const status = await refresh();
      if (!status.active) {
        term.reset();
        showTerminal(false);
        setStatus("La instancia ya no existe", null);
        return;
      }
      setStatus("Consola cerrada — recargá para reabrirla", "warn");
    } catch {
      setStatus("Consola desconectada", null);
      return;
    }
  }
}

function connectWebSocket() {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${scheme}://${window.location.host}/ws/terminal/`);
  socket.binaryType = "arraybuffer";

  socket.onopen = () => {
    setStatus("Consola conectada", "ok");
    showTerminal(true);
    sendResize();
  };

  socket.onmessage = (event) => {
    term.write(new Uint8Array(event.data));
  };

  socket.onclose = () => {
    socket = null;
    renderSessionInfo();
    if (closingOnPurpose) return;

    resincronizar();
  };

  socket.onerror = () => setStatus("Error de conexión", "down");
}

term.onData((data) => {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(new TextEncoder().encode(data));
  }
});

window.addEventListener("resize", () => {
  if (!el.empty.hidden) return;
  fitAddon.fit();
  sendResize();
});

el.start.addEventListener("click", async () => {
  el.start.disabled = true;
  setStatus("Creando contenedor", "warn");
  try {
    await callApi(API.start);
    await refresh();
    connectWebSocket();
  } catch (err) {
    setStatus(err.message, "down");
    el.start.disabled = false;
  }
});

el.stop.addEventListener("click", async () => {
  el.stop.disabled = true;
  setStatus("Destruyendo contenedor", "warn");
  closingOnPurpose = true;
  if (socket) {
    socket.close();
    socket = null;
  }
  try {
    await callApi(API.stop);
    term.reset();
    showTerminal(false);
    setStatus("Instancia destruida", null);
    await refresh();
  } catch (err) {
    setStatus(err.message, "down");
    el.stop.disabled = false;
  } finally {
    closingOnPurpose = false;
  }
});

async function refresh() {
  const status = await callApi(API.status, "GET");
  renderInfo(status);
  el.start.disabled = status.active;
  el.stop.disabled = !status.active;
  setLink(true);
  return status;
}

(async function init() {
  renderProtocol();
  renderSessionInfo();
  try {
    const status = await refresh();
    if (status.active) {
      setStatus("Instancia activa — conectando", "warn");
      connectWebSocket();
    } else {
      setStatus("Sin instancia", null);
    }
  } catch (err) {
    setLink(false);
    setStatus(`Sin estado: ${err.message}`, "down");
  }
})();
