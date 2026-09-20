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
  challenges: "/api/challenges/",
  submitFlag: "/api/challenges/submit/",
  platformSettings: "/api/platform-settings/",
  liveInstances: "/api/platform-settings/instances/",
  destroyContainer: "/api/platform-settings/instances/destroy/",
  manageUsers: "/api/platform-settings/users/",
  tutorialVisto: "/api/tutorial-visto/",
  tourVisto: "/api/tour-visto/",
};

const el = {
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
  maxLifetime: document.getElementById("info-max-lifetime"),
  challenge: document.getElementById("info-challenge"),
  image: document.getElementById("info-image"),
  picker: document.getElementById("challenge-picker"),
  pickerNote: document.getElementById("challenge-picker-note"),
  briefing: document.getElementById("challenge-briefing"),
  briefingObjective: document.getElementById("briefing-objective"),
  briefingFirstStep: document.getElementById("briefing-first-step"),
  briefingExpected: document.getElementById("briefing-expected"),
  briefingCopy: document.getElementById("briefing-copy"),
  guideBar: document.getElementById("guide-bar"),
  guideToggle: document.getElementById("guide-toggle"),
  guideBody: document.getElementById("guide-body"),
  guideObjective: document.getElementById("guide-objective"),
  guideFirstStep: document.getElementById("guide-first-step"),
  guideExpected: document.getElementById("guide-expected"),
  guideCopy: document.getElementById("guide-copy"),
  flagBar: document.getElementById("flag-bar"),
  flagForm: document.getElementById("flag-form"),
  flagInput: document.getElementById("flag-input"),
  flagSubmitBtn: document.getElementById("btn-submit-flag"),
  flagStatusBadge: document.getElementById("flag-status-badge"),
  flagFeedback: document.getElementById("flag-feedback"),
  victoryModal: document.getElementById("victory-modal"),
  victoryChallengeName: document.getElementById("victory-challenge-name"),
  victoryMessage: document.getElementById("victory-message"),
  victoryCloseBtn: document.getElementById("btn-victory-close"),
  countdownBadge: document.getElementById("countdown-badge"),
  destroyedToast: document.getElementById("destroyed-toast"),
  destroyedToastText: document.getElementById("destroyed-toast-text"),
  destroyedToastClose: document.getElementById("destroyed-toast-close"),
  userChip: document.getElementById("user-chip"),
  settingsModal: document.getElementById("settings-modal"),
  welcomeModal: document.getElementById("welcome-modal"),
  welcomeCloseBtn: document.getElementById("btn-welcome-close"),
  helpBtn: document.getElementById("btn-help"),
  tourOverlay: document.getElementById("tour-overlay"),
  tourRing: document.getElementById("tour-ring"),
  tourCallout: document.getElementById("tour-callout"),
  tourStep: document.getElementById("tour-step"),
  tourTitle: document.getElementById("tour-title"),
  tourText: document.getElementById("tour-text"),
  tourSkip: document.getElementById("tour-skip"),
  tourPrev: document.getElementById("tour-prev"),
  tourNext: document.getElementById("tour-next"),
  tourReplayBtn: document.getElementById("btn-tour"),
  settingsInactivity: document.getElementById("settings-inactivity"),
  settingsLifetime: document.getElementById("settings-lifetime"),
  settingsTimeBasico: document.getElementById("settings-time-basico"),
  settingsTimeIntermedio: document.getElementById("settings-time-intermedio"),
  settingsTimeDificil: document.getElementById("settings-time-dificil"),
  settingsFeedback: document.getElementById("settings-feedback"),
  settingsTabBtnConfig: document.getElementById("settings-tab-btn-config"),
  settingsTabBtnInstances: document.getElementById("settings-tab-btn-instances"),
  settingsTabBtnUsers: document.getElementById("settings-tab-btn-users"),
  settingsTabConfig: document.getElementById("settings-tab-config"),
  settingsTabInstances: document.getElementById("settings-tab-instances"),
  settingsTabUsers: document.getElementById("settings-tab-users"),
  instancesTbody: document.getElementById("instances-tbody"),
  instancesFeedback: document.getElementById("instances-feedback"),
  instancesRefreshBtn: document.getElementById("btn-instances-refresh"),
  instancesCloseBtn: document.getElementById("btn-instances-close"),
  newUserUsername: document.getElementById("new-user-username"),
  newUserPassword: document.getElementById("new-user-password"),
  newUserIsStaff: document.getElementById("new-user-is-staff"),
  generatePasswordBtn: document.getElementById("btn-generate-password"),
  usersFeedback: document.getElementById("users-feedback"),
  createUserBtn: document.getElementById("btn-create-user"),
  usersCloseBtn: document.getElementById("btn-users-close"),
  usersTbody: document.getElementById("users-tbody"),
  userFormTitle: document.getElementById("user-form-title"),
  newUserPasswordLabel: document.getElementById("new-user-password-label"),
  cancelEditUserBtn: document.getElementById("btn-cancel-edit-user"),
  settingsSaveBtn: document.getElementById("btn-settings-save"),
  settingsCancelBtn: document.getElementById("btn-settings-cancel"),
};

let socket = null;
let selectedChallenge = null;
let todosLosRetos = [];
let filtroDificultad = "todos";
// Distingue un cierre pedido por el usuario (al destruir) de una caída,
// para que el mensaje final no lo pise el handler de `onclose`.
let closingOnPurpose = false;
// Reintentos de reconexión automática tras una caída no intencional (ej.
// parpadeo de red en un hotspot). Se resetea a 0 en cada `onopen`.
let reconnectAttempts = 0;
const MAX_RECONNECT = 4;

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

  if (esPegar) {
    // Sin esto, el navegador igual dispara su evento nativo de "paste"
    // sobre el textarea interno de xterm, que tiene SU PROPIO manejador
    // de pegado -- y el texto termina pegado dos veces, una por acá y
    // otra por ese.
    evento.preventDefault();
    navigator.clipboard
      .readText()
      .then((texto) => {
        if (texto) term.paste(texto);
      })
      .catch(() => {
        setStatus("El navegador bloqueó el acceso al portapapeles", "warn");
      });
    return false; // no reenviar la tecla al shell
  }

  /*
   * Ctrl+C es ambiguo en cualquier terminal: con texto seleccionado casi
   * todo el mundo espera que copie, pero sin selección tiene que seguir
   * siendo la interrupción normal (Ctrl+C corta el proceso en curso).
   * Se distingue por si hay algo seleccionado en este momento.
   */
  const esCopiar =
    evento.type === "keydown" &&
    (evento.ctrlKey || evento.metaKey) &&
    evento.key.toLowerCase() === "c" &&
    term.hasSelection();

  if (esCopiar) {
    navigator.clipboard
      .writeText(term.getSelection())
      .then(() => setStatus("Copiado al portapapeles", "ok"))
      .catch(() => setStatus("El navegador bloqueó el acceso al portapapeles", "warn"));
    return false; // no mandar SIGINT: hay selección, la intención es copiar
  }

  return true;
});

function getCookie(name) {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

async function callApi(path, method = "POST", body = null) {
  const options = { method };
  if (method === "POST") {
    options.headers = { "X-CSRFToken": getCookie("csrftoken") };
    if (body !== null) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
  }
  const response = await fetch(path, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    // Se adjunta el payload y el status al error para que quien llame
    // pueda inspeccionar campos extra (ej. instance_destroyed) además del
    // mensaje.
    const err = new Error(payload.error || `Error ${response.status}`);
    err.payload = payload;
    err.status = response.status;
    throw err;
  }
  return payload;
}

function setStatus(text, variant) {
  el.statusText.textContent = text;
  el.dot.className = variant ? `rail-dot is-${variant}` : "rail-dot";
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
  el.maxLifetime.textContent = formatTimeout(status.max_lifetime_seconds);

  if (el.flagBar) {
    el.flagBar.hidden = !status.active;
    if (status.active) {
      if (status.challenge_solved) {
        el.flagStatusBadge.textContent = "✓ Resuelto";
        el.flagStatusBadge.className = "flag-bar-status is-solved";
      } else {
        el.flagStatusBadge.textContent = "Reto en curso";
        el.flagStatusBadge.className = "flag-bar-status";
      }
    }
  }

  if (status.challenge) {
    const dificultad = NOMBRE_DIFICULTAD[status.challenge.difficulty] || status.challenge.difficulty;
    const resueltoTag = status.challenge.solved ? " — ✓ Resuelto" : "";
    el.challenge.textContent = `${status.challenge.name} (${status.challenge.owasp}) — ${dificultad}${resueltoTag}`;
    if (el.image) el.image.textContent = status.challenge.image || "—";
    fillBriefing(
      { root: el.guideBar, objective: el.guideObjective, firstStep: el.guideFirstStep, expected: el.guideExpected },
      status.challenge
    );
    // Si ya venía resuelto de antes (no recién ahora), no hace falta
    // mostrar la guía ocupando espacio -- se colapsa una sola vez, al
    // primer estado que se recibe, sin pelearle a un toggle manual
    // posterior.
    if (status.challenge.solved && !guideAutoCollapseHecho && el.guideToggle) {
      guideAutoCollapseHecho = true;
      guideCollapsed = true;
      el.guideBody.hidden = true;
      el.guideToggle.classList.add("is-collapsed");
    }
  } else {
    el.challenge.textContent = "—";
    if (el.image) el.image.textContent = "—";
    fillBriefing(
      { root: el.guideBar, objective: el.guideObjective, firstStep: el.guideFirstStep, expected: el.guideExpected },
      null
    );
  }
}

function fillBriefing(target, reto) {
  if (!reto || !reto.objective) {
    target.root.hidden = true;
    return;
  }
  target.objective.textContent = reto.objective;
  target.firstStep.textContent = reto.first_step;
  target.expected.textContent = reto.expected_result;
  target.root.hidden = false;
}

function wireCopyButton(button, codeEl) {
  if (!button) return;
  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(codeEl.textContent);
      button.textContent = "Copiado";
      button.classList.add("is-copied");
      setTimeout(() => {
        button.textContent = "Copiar";
        button.classList.remove("is-copied");
      }, 1500);
    } catch {
      setStatus("El navegador bloqueó el acceso al portapapeles", "warn");
    }
  });
}

wireCopyButton(el.briefingCopy, el.briefingFirstStep);
wireCopyButton(el.guideCopy, el.guideFirstStep);

let guideCollapsed = false;
let guideAutoCollapseHecho = false;
if (el.guideToggle) {
  el.guideToggle.addEventListener("click", () => {
    guideCollapsed = !guideCollapsed;
    el.guideBody.hidden = guideCollapsed;
    el.guideToggle.classList.toggle("is-collapsed", guideCollapsed);
  });
}

function mostrarBriefingSeleccionado() {
  const reto = todosLosRetos.find((r) => r.slug === selectedChallenge);
  fillBriefing(
    { root: el.briefing, objective: el.briefingObjective, firstStep: el.briefingFirstStep, expected: el.briefingExpected },
    reto || null
  );
}

const NOMBRE_DIFICULTAD = {
  basico: "Básico",
  intermedio: "Intermedio",
  dificil: "Difícil",
};

const ICONO_CATEGORIA = {
  A01: "🔓",
  A02: "🔑",
  A03: "💉",
  A04: "📐",
  A05: "⚙️",
  A06: "📦",
  A07: "🪪",
  A08: "🧬",
  A09: "📜",
  A10: "🌐",
};

// Descripción de cada categoría del OWASP Top 10 (2021), para el tooltip ⓘ
// del encabezado de categoría en el catálogo. Texto de referencia educativo.
const DESCRIPCION_OWASP = {
  A01: "Broken Access Control: la aplicación no verifica bien que un usuario tenga permiso para un recurso o acción, así que puede ver o modificar datos ajenos o usar funciones que no le corresponden (ej. cambiar un ID y leer el pedido de otro).",
  A02: "Cryptographic Failures: datos sensibles expuestos por cifrado débil, ausente o mal usado — contraseñas sin sal, algoritmos obsoletos como MD5, o tráfico sin TLS.",
  A03: "Injection: datos no confiables llegan a un intérprete (SQL, comandos del sistema, etc.) como parte de una consulta, permitiendo ejecutar acciones no previstas o leer datos sin autorización.",
  A04: "Insecure Design: la falla está en el diseño y la lógica de negocio, no en el código — por ejemplo, no prever límites de uso o flujos de abuso. No se arregla con un parche: falta un control que nunca se diseñó.",
  A05: "Security Misconfiguration: configuraciones inseguras — valores por defecto peligrosos, permisos de más, servicios innecesarios, errores verbosos o archivos sensibles (backups) accesibles.",
  A06: "Vulnerable and Outdated Components: usar librerías, frameworks o dependencias con vulnerabilidades conocidas o sin soporte; la app hereda las fallas de esos componentes.",
  A07: "Identification and Authentication Failures: debilidades en el login que permiten suplantar identidad — sin límite de intentos, contraseñas débiles, o manejo de sesión inseguro (fuerza bruta posible).",
  A08: "Software and Data Integrity Failures: confiar en código o datos sin verificar su integridad — actualizaciones sin firmar o deserialización insegura (pickle) — lo que permite ejecutar código malicioso.",
  A09: "Security Logging and Monitoring Failures: falta o mal manejo de registros y alertas, que impide detectar y responder a ataques a tiempo — o, peor, deja datos sensibles en los propios logs.",
  A10: "Server-Side Request Forgery (SSRF): el servidor hace peticiones a URLs que controla el atacante sin validarlas, alcanzando recursos internos que no deberían ser accesibles desde afuera.",
};

function escaparAtributo(texto) {
  return String(texto)
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function agruparPorCategoria(retos) {
  const grupos = new Map();
  retos.forEach((reto) => {
    const [codigo, nombre] = reto.owasp.split(" - ");
    if (!grupos.has(codigo)) grupos.set(codigo, { codigo, nombre, retos: [] });
    grupos.get(codigo).retos.push(reto);
  });
  return Array.from(grupos.values()).sort((a, b) => a.codigo.localeCompare(b.codigo));
}

function crearTarjetaReto(reto, indice = 0) {
  const label = document.createElement("label");
  label.className = `challenge-card is-${reto.difficulty}`;
  if (reto.solved) label.classList.add("is-solved");
  label.dataset.slug = reto.slug;
  label.style.animationDelay = `${Math.min(indice, 14) * 30}ms`;

  const input = document.createElement("input");
  input.type = "radio";
  input.name = "challenge";
  input.value = reto.slug;
  input.checked = reto.slug === selectedChallenge;

  const body = document.createElement("div");
  body.className = "challenge-card-body";
  body.innerHTML = `
    <div class="challenge-card-head">
      <span class="challenge-card-name">${reto.name}</span>
      <span class="difficulty-tag is-${reto.difficulty}">${NOMBRE_DIFICULTAD[reto.difficulty] || reto.difficulty}</span>
      ${reto.time_limit_seconds ? `<span class="time-limit-tag" title="Vida máxima de la instancia">⏱ ${formatTimeout(reto.time_limit_seconds)}</span>` : ""}
      ${reto.solved ? '<span class="solved-tag">✓ Resuelto</span>' : ""}
    </div>
    <p class="challenge-card-desc">${reto.description}</p>
    <span class="image-tag" title="Imagen Docker de este reto">${reto.image || ""}</span>
  `;

  label.appendChild(input);
  label.appendChild(body);
  label.classList.toggle("is-selected", input.checked);

  input.addEventListener("change", () => {
    selectedChallenge = reto.slug;
    el.picker
      .querySelectorAll(".challenge-card")
      .forEach((card) => card.classList.toggle("is-selected", card.dataset.slug === selectedChallenge));
    mostrarBriefingSeleccionado();
  });

  return label;
}

function renderChallengePicker(disponibles) {
  el.picker.innerHTML = "";
  if (disponibles.length === 0) {
    el.picker.innerHTML = '<p class="challenge-picker-empty">Sin retos en esta dificultad.</p>';
    mostrarBriefingSeleccionado();
    return;
  }

  let indiceTarjeta = 0;
  agruparPorCategoria(disponibles).forEach((grupo) => {
    const seccion = document.createElement("div");
    seccion.className = "category-group";

    const head = document.createElement("div");
    head.className = "category-head";
    const prefijo = grupo.codigo.split(":")[0];
    const descOwasp = DESCRIPCION_OWASP[prefijo] || "";
    head.innerHTML = `
      <span class="category-icon">${ICONO_CATEGORIA[prefijo] || "🛡"}</span>
      <span class="category-code">${grupo.codigo}</span>
      <span class="category-name">${grupo.nombre}</span>
      ${descOwasp ? `<span class="owasp-info" tabindex="0" role="note" data-owasp="${escaparAtributo(descOwasp)}" aria-label="Qué es ${escaparAtributo(grupo.nombre)} según OWASP">ⓘ</span>` : ""}
      <span class="category-count">${grupo.retos.length} reto${grupo.retos.length === 1 ? "" : "s"}</span>
    `;
    seccion.appendChild(head);

    const lista = document.createElement("div");
    lista.className = "category-cards";
    grupo.retos.forEach((reto) => lista.appendChild(crearTarjetaReto(reto, indiceTarjeta++)));
    seccion.appendChild(lista);

    el.picker.appendChild(seccion);
  });

  mostrarBriefingSeleccionado();
}

function retosFiltrados() {
  if (filtroDificultad === "todos") return todosLosRetos;
  return todosLosRetos.filter((reto) => reto.difficulty === filtroDificultad);
}

function moverIndicadorFiltro(btn) {
  const indicador = document.getElementById("filter-indicator");
  const contenedor = document.getElementById("difficulty-filter");
  if (!indicador || !contenedor || !btn) return;
  const rectContenedor = contenedor.getBoundingClientRect();
  const rectBtn = btn.getBoundingClientRect();
  indicador.style.left = `${rectBtn.left - rectContenedor.left}px`;
  indicador.style.width = `${rectBtn.width}px`;
}

function aplicarFiltro(dificultad) {
  filtroDificultad = dificultad;
  let btnActivo = null;
  document.querySelectorAll(".difficulty-filter-btn").forEach((btn) => {
    const activo = btn.dataset.difficulty === dificultad;
    btn.classList.toggle("is-active", activo);
    if (activo) btnActivo = btn;
  });
  moverIndicadorFiltro(btnActivo);
  renderChallengePicker(retosFiltrados());
}

document.querySelectorAll(".difficulty-filter-btn").forEach((btn) => {
  btn.addEventListener("click", () => aplicarFiltro(btn.dataset.difficulty));
});

moverIndicadorFiltro(document.querySelector(".difficulty-filter-btn.is-active"));
window.addEventListener("resize", () => {
  moverIndicadorFiltro(document.querySelector(".difficulty-filter-btn.is-active"));
});

async function cargarRetos() {
  const data = await callApi(API.challenges, "GET");
  selectedChallenge = selectedChallenge || data.default;
  todosLosRetos = data.challenges;
  renderChallengePicker(retosFiltrados());
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

function mostrarToastDestruccion() {
  if (!el.destroyedToast) return;

  // Mensaje genérico y correcto para cualquier causa de destrucción
  // automática: el frontend no puede saber con certeza cuál fue (el
  // servidor borra la fila sin dejar el motivo accesible desde acá), y
  // además puede llegar por caminos distintos (cierre del WebSocket o
  // respuesta de la API) que compiten entre sí. Un texto que cubre todos
  // los casos evita mostrar un motivo equivocado gane el que gane.
  el.destroyedToastText.textContent =
    "La instancia se cerró automáticamente (tiempo de vida agotado, " +
    "inactividad o demasiados intentos de bandera fallidos). Despliega " +
    "una nueva si la necesitas.";
  el.destroyedToast.hidden = false;
}

if (el.destroyedToastClose) {
  el.destroyedToastClose.addEventListener("click", () => {
    el.destroyedToast.hidden = true;
  });
}

function resetUIsinInstancia() {
  // Deja toda la UI en estado "sin instancia" SIN preguntar al servidor.
  // Es a propósito: cuando el watchdog destruye la instancia, mata el
  // contenedor y recién después borra su fila; si consultáramos el estado
  // en ese instante, la fila todavía podría figurar activa y repintaríamos
  // la guía y la barra de bandera de una instancia que ya no existe.
  ultimoStatusActivo = null; // corta el countdown (actualizarCountdown lo lee)
  if (el.countdownBadge) el.countdownBadge.hidden = true;
  el.state.innerHTML = '<span class="chip is-idle">Inactiva</span>';
  el.challenge.textContent = "—";
  if (el.image) el.image.textContent = "—";
  el.container.textContent = "—";
  el.network.textContent = "—";
  el.created.textContent = "—";
  if (el.headChallengeChip) el.headChallengeChip.hidden = true;
  if (el.headContainerChip) el.headContainerChip.hidden = true;
  if (el.guideBar) el.guideBar.hidden = true;
  if (el.flagBar) el.flagBar.hidden = true;
  el.start.disabled = false;
  el.stop.disabled = true;
}

function mostrarInstanciaDestruida({ toast = true, statusText = "La instancia ya no existe" } = {}) {
  term.reset();
  showTerminal(false);
  resetUIsinInstancia();
  setStatus(statusText, toast ? null : "warn");
  // El toast del watchdog no aplica cuando la destrucción tuvo otra causa
  // explicada aparte (ej. límite de intentos de bandera): en ese caso se
  // llama con toast:false.
  if (toast) mostrarToastDestruccion();
}

function vidaMaximaAgotada() {
  // ¿El countdown de vida máxima ya llegó a 0? Si es así, un corte del
  // WebSocket es el watchdog destruyendo la instancia, no un parpadeo de
  // red -- no tiene sentido ofrecer "Reconectando". Se usa el último
  // snapshot activo (nunca se limpia, ver refresh()).
  const s = ultimaInstanciaActiva;
  if (!s || !s.created_at || !s.max_lifetime_seconds) return false;
  const limite = new Date(s.created_at).getTime() + s.max_lifetime_seconds * 1000;
  return Date.now() >= limite;
}

async function intentarReconectar() {
  /*
   * La consola se cortó sin que el usuario lo pidiera. Dos causas posibles:
   *  a) la instancia sigue viva pero la conexión se cayó (parpadeo de red,
   *     suspensión de la laptop, hotspot inestable) -> se reconecta sola.
   *  b) la instancia ya no existe (el estudiante escribió `exit`, o el
   *     watchdog la destruyó) -> no hay nada a que reconectarse.
   *
   * Antes de reintentar se consulta el estado: solo tiene sentido
   * reconectar si el contenedor todavía está. Si no, se cae al mismo
   * manejo de siempre (limpiar la terminal y avisar). Cada intento
   * espera un poco más (backoff) para no martillar al servidor.
   *
   * Ojo: reconectar abre un `exec` NUEVO -> es un shell fresco, no la
   * misma sesión (se pierde cwd/procesos/historial), igual que recargar
   * la página. El `terminate_console` del backend ya limpió el shell
   * viejo al cerrarse la conexión anterior, así que no se acumulan.
   */
  if (closingOnPurpose) return;

  let status;
  try {
    status = await refresh();
  } catch {
    setStatus("Consola desconectada", null);
    return;
  }

  if (!status.active) {
    mostrarInstanciaDestruida();
    return;
  }

  if (reconnectAttempts >= MAX_RECONNECT) {
    setStatus("Consola cerrada — recarga para reabrirla", "warn");
    return;
  }

  reconnectAttempts += 1;
  const espera = Math.min(1000 * 2 ** (reconnectAttempts - 1), 8000);
  setStatus(`Reconectando (intento ${reconnectAttempts}/${MAX_RECONNECT})…`, "warn");
  await new Promise((r) => setTimeout(r, espera));
  if (closingOnPurpose) return;
  connectWebSocket();
}

function connectWebSocket() {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${scheme}://${window.location.host}/ws/terminal/`);
  socket.binaryType = "arraybuffer";

  socket.onopen = () => {
    reconnectAttempts = 0;
    setStatus("Consola conectada", "ok");
    showTerminal(true);
    sendResize();
  };

  socket.onmessage = (event) => {
    term.write(new Uint8Array(event.data));
  };

  socket.onclose = (event) => {
    socket = null;
    renderSessionInfo();
    if (closingOnPurpose) return;

    // No reintentar cuando es destrucción real, no un parpadeo de red:
    //  - el servidor rechaza la conexión (4004 = ya no hay instancia,
    //    4002 = el contenedor se está destruyendo), o
    //  - la vida máxima ya venció (el countdown llegó a 0 -> es el
    //    watchdog el que la está destruyendo).
    // En esos casos se avisa al instante, sin mostrar "Reconectando".
    if (event.code === 4004 || event.code === 4002 || vidaMaximaAgotada()) {
      mostrarInstanciaDestruida();
      return;
    }

    intentarReconectar();
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

/*
 * El tamaño de `.terminal-wrap` no solo cambia con la ventana: también
 * se achica cuando la barra de bandera crece (ej. al mostrar un mensaje
 * de error) o cuando se abre/cierra la guía del reto. Sin reajustar el
 * canvas de xterm en esos casos, queda calculado para un tamaño viejo y
 * se desborda visualmente sobre lo que esté debajo. El ResizeObserver
 * cubre cualquier cambio de tamaño, sea la causa que sea.
 */
new ResizeObserver(() => {
  if (!el.empty.hidden) return;
  fitAddon.fit();
  sendResize();
}).observe(el.terminal.parentElement);

el.start.addEventListener("click", async () => {
  if (!selectedChallenge) {
    setStatus("Elige un reto antes de desplegar", "warn");
    return;
  }
  el.start.disabled = true;
  setStatus("Creando contenedor", "warn");
  // El mensaje de la última bandera validada (de un reto anterior, ya
  // destruido) no se borraba solo -- quedaba pegado ahí hasta que se
  // validara una bandera nueva, aunque fuera de otro reto.
  if (el.flagFeedback) el.flagFeedback.hidden = true;
  if (el.flagInput) el.flagInput.value = "";
  try {
    await callApi(API.start, "POST", { challenge: selectedChallenge });
    await refresh();
    connectWebSocket();
    // Primera vez que despliega: tour guiado de la UI en vivo.
    maybeStartTour();
  } catch (err) {
    setStatus(err.message, "down");
    el.start.disabled = false;
  }
});

el.stop.addEventListener("click", async () => {
  el.stop.disabled = true;
  setStatus("Destruyendo contenedor", "warn");
  try {
    await callApi(API.stop);
    // El socket se cierra recién acá, ya confirmado el éxito: si el
    // servidor falla en destruir (ej. Docker no responde), la consola
    // sigue funcionando en vez de quedar muerta sin reconexión.
    closingOnPurpose = true;
    if (socket) {
      socket.close();
      socket = null;
    }
    term.reset();
    showTerminal(false);
    setStatus("Instancia destruida", null);
    if (el.flagFeedback) el.flagFeedback.hidden = true;
    if (el.flagInput) el.flagInput.value = "";
    await refresh();
  } catch (err) {
    setStatus(err.message, "down");
    el.stop.disabled = false;
  } finally {
    closingOnPurpose = false;
  }
});

let ultimoStatusActivo = null;
let ultimaInstanciaActiva = null;

function actualizarCountdown() {
  if (!el.countdownBadge) return;
  if (!ultimoStatusActivo || !ultimoStatusActivo.created_at || !ultimoStatusActivo.max_lifetime_seconds) {
    el.countdownBadge.hidden = true;
    return;
  }
  const limite =
    new Date(ultimoStatusActivo.created_at).getTime() +
    ultimoStatusActivo.max_lifetime_seconds * 1000;
  const restanteS = Math.max(0, Math.floor((limite - Date.now()) / 1000));
  const mm = String(Math.floor(restanteS / 60)).padStart(2, "0");
  const ss = String(restanteS % 60).padStart(2, "0");
  el.countdownBadge.textContent = `⏱ ${mm}:${ss}`;
  el.countdownBadge.hidden = false;
  el.countdownBadge.classList.toggle("is-critical", restanteS <= 15);
  el.countdownBadge.classList.toggle("is-warn", restanteS > 15 && restanteS <= 60);
}

setInterval(actualizarCountdown, 1000);

async function refresh() {
  const status = await callApi(API.status, "GET");
  renderInfo(status);
  el.start.disabled = status.active;
  el.stop.disabled = !status.active;
  // Para el countdown, que se apague apenas se sabe que ya no está
  // activa. Para el toast de "se destruyó sola" (mostrarToastDestruccion,
  // en intentarReconectar) hace falta el último snapshot ACTIVO, así que ese
  // se guarda aparte y nunca se limpia con esto.
  ultimoStatusActivo = status.active ? status : null;
  if (status.active) ultimaInstanciaActiva = status;
  actualizarCountdown();
  return status;
}

if (el.flagForm) {
  el.flagForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const flag = el.flagInput.value.trim();
    if (!flag) return;

    el.flagSubmitBtn.disabled = true;
    el.flagFeedback.hidden = true;
    el.flagFeedback.className = "flag-feedback";

    try {
      const res = await callApi(API.submitFlag, "POST", { flag });
      if (res.success) {
        el.flagFeedback.textContent = res.message;
        el.flagFeedback.className = "flag-feedback is-success";
        el.flagFeedback.hidden = false;
        el.flagInput.value = "";

        el.flagStatusBadge.textContent = "✓ Resuelto";
        el.flagStatusBadge.className = "flag-bar-status is-solved";

        el.victoryChallengeName.textContent = res.challenge_name || "Reto Completado";
        el.victoryMessage.textContent = res.message;
        el.victoryModal.hidden = false;

        // Ya resuelto, la guía deja de hacer falta: se colapsa sola para
        // devolverle ese espacio a la terminal (el usuario la puede
        // volver a abrir con el botón ▾ si quiere releerla).
        if (res.newly_solved && el.guideToggle && !guideCollapsed) {
          guideAutoCollapseHecho = true;
          guideCollapsed = true;
          el.guideBody.hidden = true;
          el.guideToggle.classList.add("is-collapsed");
        }

        await cargarRetos();
        await refresh();
      }
    } catch (err) {
      el.flagFeedback.textContent = err.message || "Bandera incorrecta";
      el.flagFeedback.className = "flag-feedback is-error";
      el.flagFeedback.hidden = false;
      // Se superó el límite de intentos: el servidor ya destruyó la
      // instancia. Se resetea la UI al estado "sin instancia" (sin el toast
      // del watchdog: el feedback de bandera de arriba ya explica el motivo).
      if (err.payload && err.payload.instance_destroyed) {
        mostrarInstanciaDestruida({
          toast: false,
          statusText: "Instancia destruida por demasiados intentos",
        });
      }
    } finally {
      el.flagSubmitBtn.disabled = false;
    }
  });
}

if (el.victoryCloseBtn) {
  el.victoryCloseBtn.addEventListener("click", () => {
    el.victoryModal.hidden = true;
  });
}

/*
 * Tutorial de bienvenida. Se muestra solo la primera vez (el backend pasa
 * `mostrar_tutorial` -> data-autoshow="1", y se marca visto en la BD al
 * cerrarlo). El botón "?" del topbar lo reabre cuando quieran, sin volver
 * a tocar la BD.
 */
if (el.welcomeModal) {
  let tutorialMarcadoVisto = false;

  const marcarTutorialVisto = async () => {
    if (tutorialMarcadoVisto) return;
    tutorialMarcadoVisto = true;
    try {
      await callApi(API.tutorialVisto, "POST");
    } catch (_) {
      // Si falla el marcado no es grave: a lo sumo reaparece la próxima vez.
    }
  };

  const abrirTutorial = () => {
    el.welcomeModal.hidden = false;
  };
  const cerrarTutorial = () => {
    el.welcomeModal.hidden = true;
    marcarTutorialVisto();
  };

  if (el.welcomeCloseBtn) el.welcomeCloseBtn.addEventListener("click", cerrarTutorial);
  // Cerrar al clickear el fondo (fuera de la tarjeta).
  el.welcomeModal.addEventListener("click", (evento) => {
    if (evento.target === el.welcomeModal) cerrarTutorial();
  });
  // Botón "?" del topbar: reabrir el tutorial a demanda.
  if (el.helpBtn) el.helpBtn.addEventListener("click", abrirTutorial);

  // Primera vez: mostrarlo solo. Al cerrarse queda marcado como visto.
  if (el.welcomeModal.dataset.autoshow === "1") abrirTutorial();
}

/*
 * Tooltip flotante para el ⓘ de cada categoría OWASP en el catálogo. Se
 * posiciona con position:fixed vía JS para que ningún contenedor con scroll
 * lo recorte (un tooltip CSS anidado sí se recortaría).
 */
if (el.picker) {
  const tip = document.createElement("div");
  tip.className = "owasp-tooltip-float";
  tip.setAttribute("role", "tooltip");
  tip.hidden = true;
  document.body.appendChild(tip);

  const mostrarTip = (info) => {
    const desc = info.getAttribute("data-owasp");
    if (!desc) return;
    tip.textContent = desc;
    tip.hidden = false;
    const r = info.getBoundingClientRect();
    const ancho = Math.min(320, window.innerWidth - 24);
    tip.style.width = `${ancho}px`;
    let left = r.left;
    if (left + ancho > window.innerWidth - 12) left = window.innerWidth - 12 - ancho;
    if (left < 12) left = 12;
    tip.style.left = `${left}px`;
    tip.style.top = `${r.bottom + 8}px`;
  };
  const ocultarTip = () => {
    tip.hidden = true;
  };

  el.picker.addEventListener("mouseover", (e) => {
    const info = e.target.closest && e.target.closest(".owasp-info");
    if (info) mostrarTip(info);
  });
  el.picker.addEventListener("mouseout", (e) => {
    if (e.target.closest && e.target.closest(".owasp-info")) ocultarTip();
  });
  el.picker.addEventListener("focusin", (e) => {
    const info = e.target.closest && e.target.closest(".owasp-info");
    if (info) mostrarTip(info);
  });
  el.picker.addEventListener("focusout", ocultarTip);
  // Al scrollear, ocultarlo para que no quede flotando en una posición vieja.
  window.addEventListener("scroll", ocultarTip, true);
}

/*
 * Tour guiado (coach-marks) que resalta la UII en vivo la primera vez que
 * el usuario despliega una instancia. `maybeStartTour()` se llama desde el
 * handler de desplegar; el resaltado usa un anillo con box-shadow gigante
 * para oscurecer todo menos el elemento apuntado.
 */
const TOUR_STEPS = [
  { sel: "#terminal", title: "Tu consola", text: "Esta es la terminal del contenedor del reto. Aquí ejecutas comandos reales para explorar y explotar la vulnerabilidad." },
  { sel: "#guide-bar", title: "Guía del reto", text: "El objetivo, el primer comando para arrancar y qué deberías ver. Si te trabas, empieza por aquí." },
  { sel: "#countdown-badge", title: "Tiempo límite", text: "Tu instancia dura un tiempo limitado. Cuando el contador llega a 0, se destruye sola y se liberan los recursos." },
  { sel: "#flag-bar", title: "Validar tu bandera", text: "Cuando encuentres la bandera (FLAG{...}), la pegas aquí y la validas. Ojo: 5 intentos fallidos destruyen la instancia." },
  { sel: ".side", title: "Datos y límites", text: "Aquí ves el estado de tu instancia y sus límites de recursos (memoria, CPU, procesos)." },
  { sel: "#btn-stop", title: "Destruir cuando termines", text: "Puedes destruir la instancia manualmente en cualquier momento para empezar otro reto." },
];

let tourIndice = 0;
let tourPasos = [];
let tourMostradoEstaSesion = false;
let tourMarcadoVisto = false;

function tourVisible(elemento) {
  if (!elemento) return false;
  const r = elemento.getBoundingClientRect();
  return r.width > 0 && r.height > 0;
}

function tourPosicionar(target) {
  const r = target.getBoundingClientRect();
  const pad = 6;
  el.tourRing.style.left = `${r.left - pad}px`;
  el.tourRing.style.top = `${r.top - pad}px`;
  el.tourRing.style.width = `${r.width + pad * 2}px`;
  el.tourRing.style.height = `${r.height + pad * 2}px`;

  const callout = el.tourCallout;
  const ancho = Math.min(320, window.innerWidth - 24);
  callout.style.width = `${ancho}px`;
  const alto = callout.offsetHeight;
  let top = r.bottom + 12;
  if (top + alto > window.innerHeight - 12) top = r.top - alto - 12;
  if (top < 12) top = 12;
  let left = r.left;
  if (left + ancho > window.innerWidth - 12) left = window.innerWidth - 12 - ancho;
  if (left < 12) left = 12;
  callout.style.left = `${left}px`;
  callout.style.top = `${top}px`;
}

function tourMostrarPaso(i) {
  tourIndice = i;
  const paso = tourPasos[i];
  const target = document.querySelector(paso.sel);
  if (!tourVisible(target)) {
    tourTerminar();
    return;
  }
  el.tourStep.textContent = `Paso ${i + 1} de ${tourPasos.length}`;
  el.tourTitle.textContent = paso.title;
  el.tourText.textContent = paso.text;
  el.tourPrev.disabled = i === 0;
  el.tourNext.textContent = i === tourPasos.length - 1 ? "Listo" : "Siguiente";
  target.scrollIntoView({ block: "nearest", behavior: "smooth" });
  requestAnimationFrame(() => tourPosicionar(target));
}

async function tourMarcar() {
  if (tourMarcadoVisto) return;
  tourMarcadoVisto = true;
  try {
    await callApi(API.tourVisto, "POST");
  } catch (_) {
    // Si falla el marcado no es grave: reaparecería en el próximo despliegue.
  }
}

function tourTerminar() {
  if (el.tourOverlay) el.tourOverlay.hidden = true;
  tourMarcar();
}

function tourLanzar() {
  // Arranca el tour con los pasos cuyo elemento esté visible ahora mismo.
  // Devuelve false si no hay nada que mostrar (ej. sin instancia activa).
  if (!el.tourOverlay) return false;
  tourPasos = TOUR_STEPS.filter((s) => tourVisible(document.querySelector(s.sel)));
  if (tourPasos.length === 0) return false;
  el.tourOverlay.hidden = false;
  tourMostrarPaso(0);
  return true;
}

function maybeStartTour() {
  // Auto: solo la primera vez que se despliega (marcado en BD).
  if (!el.tourOverlay) return;
  if (el.tourOverlay.dataset.mostrarTour !== "1") return;
  if (tourMostradoEstaSesion) return;
  if (el.welcomeModal && !el.welcomeModal.hidden) return; // no pisar el modal
  // Esperar a que la UI en vivo (consola, guía, contador, flag) esté pintada.
  setTimeout(() => {
    if (tourMostradoEstaSesion) return;
    if (tourLanzar()) tourMostradoEstaSesion = true;
  }, 700);
}

function tourReplayManual() {
  // A demanda desde el botón "?" de la consola. Ignora si ya se vio; solo
  // tiene sentido con una instancia activa (ahí existen los elementos).
  if (!tourLanzar()) {
    setStatus("Despliega una instancia para ver el tour de la consola", "warn");
  }
}

if (el.tourOverlay) {
  el.tourNext.addEventListener("click", () => {
    if (tourIndice >= tourPasos.length - 1) tourTerminar();
    else tourMostrarPaso(tourIndice + 1);
  });
  el.tourPrev.addEventListener("click", () => {
    if (tourIndice > 0) tourMostrarPaso(tourIndice - 1);
  });
  el.tourSkip.addEventListener("click", tourTerminar);
  if (el.tourReplayBtn) el.tourReplayBtn.addEventListener("click", tourReplayManual);
  window.addEventListener("resize", () => {
    if (!el.tourOverlay.hidden && tourPasos[tourIndice]) {
      const t = document.querySelector(tourPasos[tourIndice].sel);
      if (t) tourPosicionar(t);
    }
  });
}

/*
 * Panel oculto: 5 clicks seguidos (menos de 1.5s entre cada uno) sobre
 * el propio nombre de usuario abren el ajuste del watchdog. Que esté
 * escondido es solo para que no cualquiera se tropiece con él por
 * accidente -- el control real de acceso es el `is_staff` que exige el
 * backend (`platform_settings_view`); a alguien sin permiso esto ni
 * siquiera le sirve de nada, el fetch le va a devolver 403.
 */
if (el.userChip && el.userChip.dataset.isStaff === "true") {
  let clicksSeguidos = 0;
  let ultimoClick = 0;

  el.userChip.addEventListener("click", async () => {
    const ahora = Date.now();
    clicksSeguidos = ahora - ultimoClick < 1500 ? clicksSeguidos + 1 : 1;
    ultimoClick = ahora;

    if (clicksSeguidos < 5) return;
    clicksSeguidos = 0;

    try {
      const config = await callApi(API.platformSettings, "GET");
      el.settingsInactivity.value = Math.round(config.inactivity_timeout_seconds / 60);
      el.settingsLifetime.value = +(config.max_lifetime_seconds / 3600).toFixed(2);
      el.settingsTimeBasico.value = Math.round(config.time_limit_basico_seconds / 60);
      el.settingsTimeIntermedio.value = Math.round(config.time_limit_intermedio_seconds / 60);
      el.settingsTimeDificil.value = Math.round(config.time_limit_dificil_seconds / 60);
      el.settingsFeedback.hidden = true;
      el.settingsModal.hidden = false;
      cambiarTabPanel("config");
    } catch (err) {
      setStatus(err.message, "warn");
    }
  });
}

if (el.settingsCancelBtn) {
  el.settingsCancelBtn.addEventListener("click", () => {
    el.settingsModal.hidden = true;
  });
}

function cambiarTabPanel(tab) {
  if (!el.settingsTabConfig || !el.settingsTabInstances || !el.settingsTabUsers) return;

  el.settingsTabConfig.hidden = tab !== "config";
  el.settingsTabInstances.hidden = tab !== "instances";
  el.settingsTabUsers.hidden = tab !== "users";
  el.settingsTabBtnConfig.classList.toggle("is-active", tab === "config");
  el.settingsTabBtnInstances.classList.toggle("is-active", tab === "instances");
  el.settingsTabBtnUsers.classList.toggle("is-active", tab === "users");

  if (tab === "instances") cargarInstanciasEnVivo();
  if (tab === "users") {
    // Siempre arranca en modo "crear" al abrir la pestaña (por si quedó a
    // medias una edición anterior).
    if (typeof salirModoEdicionUsuario === "function") salirModoEdicionUsuario();
    cargarUsuarios();
  }
}

if (el.settingsTabBtnUsers) {
  el.settingsTabBtnUsers.addEventListener("click", () => cambiarTabPanel("users"));
}

if (el.settingsTabBtnConfig) {
  el.settingsTabBtnConfig.addEventListener("click", () => cambiarTabPanel("config"));
}
if (el.settingsTabBtnInstances) {
  el.settingsTabBtnInstances.addEventListener("click", () => cambiarTabPanel("instances"));
}

function formatearMomento(instancia) {
  const iso = instancia.created ? instancia.created * 1000 : instancia.last_activity;
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function renderInstancesTable(instancias) {
  if (!el.instancesTbody) return;
  if (!instancias.length) {
    el.instancesTbody.innerHTML = '<tr><td colspan="6" class="instances-empty">Nada corriendo ahora mismo.</td></tr>';
    return;
  }
  el.instancesTbody.innerHTML = instancias
    .map(
      (i) => `
    <tr>
      <td><span class="instance-state-tag is-${i.estado}">${i.estado}</span></td>
      <td>${i.user || "—"}</td>
      <td>${i.challenge || "—"}</td>
      <td title="${i.container_id}">${i.container_id.slice(0, 12)}</td>
      <td>${formatearMomento(i)}</td>
      <td><button type="button" class="btn-instance-destroy" data-container="${i.container_id}" data-network="${i.network_id || ""}">Destruir</button></td>
    </tr>
  `
    )
    .join("");
}

async function cargarInstanciasEnVivo() {
  if (!el.instancesTbody) return;
  try {
    const data = await callApi(API.liveInstances, "GET");
    renderInstancesTable(data.instances);
    if (el.instancesFeedback) el.instancesFeedback.hidden = true;
  } catch (err) {
    if (el.instancesFeedback) {
      el.instancesFeedback.textContent = err.message;
      el.instancesFeedback.className = "settings-feedback is-error";
      el.instancesFeedback.hidden = false;
    }
  }
}

if (el.instancesTbody) {
  el.instancesTbody.addEventListener("click", async (evento) => {
    const boton = evento.target.closest(".btn-instance-destroy");
    if (!boton) return;
    boton.disabled = true;
    boton.textContent = "...";
    try {
      await callApi(API.destroyContainer, "POST", {
        container_id: boton.dataset.container,
        network_id: boton.dataset.network || null,
      });
      await cargarInstanciasEnVivo();
      await refresh();
    } catch (err) {
      if (el.instancesFeedback) {
        el.instancesFeedback.textContent = err.message;
        el.instancesFeedback.className = "settings-feedback is-error";
        el.instancesFeedback.hidden = false;
      }
      boton.disabled = false;
      boton.textContent = "Destruir";
    }
  });
}

if (el.instancesRefreshBtn) {
  el.instancesRefreshBtn.addEventListener("click", cargarInstanciasEnVivo);
}
if (el.instancesCloseBtn) {
  el.instancesCloseBtn.addEventListener("click", () => {
    el.settingsModal.hidden = true;
  });
}

/*
 * Un solo intervalo, siempre corriendo, en vez de arrancarlo/pararlo al
 * abrir y cerrar el panel: la pestaña de instancias se puede cerrar por
 * varios caminos (el botón, Cancelar, o clickeando afuera del recuadro
 * -- ese último es un atributo `onclick` inline en el HTML, sin aviso
 * para este script). Más simple no hacer nada la mayoría de los ticks
 * que tratar de sincronizar el apagado con cada camino de cierre.
 */
setInterval(() => {
  if (
    el.settingsModal &&
    !el.settingsModal.hidden &&
    el.settingsTabInstances &&
    !el.settingsTabInstances.hidden
  ) {
    cargarInstanciasEnVivo();
  }
}, 5000);

/*
 * Mismo criterio que en el backend (`views.manage_users_view`): solo
 * letras (con acentos/ñ) y guion bajo, sin números ni espacios, entre
 * 3 y 20 caracteres. Esto es solo para avisar rápido en el formulario
 * -- la validación que de verdad importa es la del servidor, esto
 * nunca la reemplaza.
 */
const PATRON_USUARIO = /^[A-Za-zÁÉÍÓÚÑáéíóúñ_]{3,20}$/;

function generarClave() {
  const alfabeto = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789";
  let clave = "";
  for (let i = 0; i < 10; i++) {
    clave += alfabeto[Math.floor(Math.random() * alfabeto.length)];
  }
  return clave;
}

if (el.generatePasswordBtn) {
  el.generatePasswordBtn.addEventListener("click", () => {
    el.newUserPassword.value = generarClave();
    el.newUserPassword.type = "text";
  });
}

function renderUsersTable(usuarios) {
  if (!el.usersTbody) return;
  if (!usuarios.length) {
    el.usersTbody.innerHTML = '<tr><td colspan="4" class="instances-empty">Sin usuarios todavía.</td></tr>';
    return;
  }
  // El username solo admite letras y guion bajo (validado en el backend),
  // así que no puede inyectar HTML/atributos -- se puede interpolar directo.
  el.usersTbody.innerHTML = usuarios
    .map((u) => {
      const rolLabel = u.is_staff ? "Quitar staff" : "Hacer staff";
      // No puedes degradarte ni eliminarte a ti mismo (te dejaría sin
      // acceso al panel), así que esos botones no aparecen en tu fila.
      const rolBtn = u.is_self
        ? ""
        : `<button type="button" class="btn-user-accion" data-accion="rol" data-id="${u.id}" data-staff="${u.is_staff ? "1" : "0"}">${rolLabel}</button>`;
      const delBtn = u.is_self
        ? ""
        : `<button type="button" class="btn-user-accion is-danger" data-accion="eliminar" data-id="${u.id}" data-nombre="${u.username}">Eliminar</button>`;
      return `
    <tr>
      <td>${u.username}${u.is_self ? ' <span class="user-self-tag">tú</span>' : ""}</td>
      <td>${u.is_staff ? '<span class="user-staff-tag">Staff</span>' : "—"}</td>
      <td>${new Date(u.date_joined).toLocaleDateString("es")}</td>
      <td class="user-acciones">
        <button type="button" class="btn-user-accion" data-accion="editar" data-id="${u.id}" data-nombre="${u.username}" data-staff="${u.is_staff ? "1" : "0"}">Editar</button>
        ${rolBtn}
        ${delBtn}
      </td>
    </tr>`;
    })
    .join("");
}

async function accionUsuario(id, body) {
  try {
    await callApi(`${API.manageUsers}${id}/`, "POST", body);
    if (el.usersFeedback) el.usersFeedback.hidden = true;
    await cargarUsuarios();
  } catch (err) {
    if (el.usersFeedback) {
      el.usersFeedback.textContent = err.message;
      el.usersFeedback.className = "settings-feedback is-error";
      el.usersFeedback.hidden = false;
    }
  }
}

let editandoUsuarioId = null;

function entrarModoEdicionUsuario(user) {
  editandoUsuarioId = user.id;
  el.newUserUsername.value = user.username;
  el.newUserPassword.value = "";
  el.newUserIsStaff.checked = user.is_staff;
  if (el.userFormTitle) el.userFormTitle.textContent = `Editar cuenta: ${user.username}`;
  if (el.newUserPasswordLabel) el.newUserPasswordLabel.textContent = "Clave (dejar vacía para no cambiarla)";
  el.newUserPassword.placeholder = "Dejar vacío para mantener la actual";
  el.createUserBtn.textContent = "Guardar cambios";
  if (el.cancelEditUserBtn) el.cancelEditUserBtn.hidden = false;
  if (el.usersFeedback) el.usersFeedback.hidden = true;
  el.newUserUsername.focus();
}

function salirModoEdicionUsuario() {
  editandoUsuarioId = null;
  el.newUserUsername.value = "";
  el.newUserPassword.value = "";
  el.newUserIsStaff.checked = false;
  if (el.userFormTitle) el.userFormTitle.textContent = "Crear cuenta";
  if (el.newUserPasswordLabel) el.newUserPasswordLabel.textContent = "Clave";
  el.newUserPassword.placeholder = "Al menos 6 caracteres";
  el.createUserBtn.textContent = "Crear usuario";
  if (el.cancelEditUserBtn) el.cancelEditUserBtn.hidden = true;
}

if (el.usersTbody) {
  el.usersTbody.addEventListener("click", async (evento) => {
    const btn = evento.target.closest(".btn-user-accion");
    if (!btn) return;
    const id = btn.dataset.id;
    const accion = btn.dataset.accion;

    if (accion === "editar") {
      entrarModoEdicionUsuario({
        id,
        username: btn.dataset.nombre,
        is_staff: btn.dataset.staff === "1",
      });
    } else if (accion === "rol") {
      await accionUsuario(id, { accion: "editar", is_staff: btn.dataset.staff !== "1" });
    } else if (accion === "eliminar") {
      if (!confirm(`¿Eliminar al usuario "${btn.dataset.nombre}"? Esta acción no se puede deshacer.`)) return;
      await accionUsuario(id, { accion: "eliminar" });
    }
  });
}

if (el.cancelEditUserBtn) {
  el.cancelEditUserBtn.addEventListener("click", salirModoEdicionUsuario);
}

async function cargarUsuarios() {
  if (!el.usersTbody) return;
  try {
    const data = await callApi(API.manageUsers, "GET");
    renderUsersTable(data.users);
  } catch (err) {
    if (el.usersFeedback) {
      el.usersFeedback.textContent = err.message;
      el.usersFeedback.className = "settings-feedback is-error";
      el.usersFeedback.hidden = false;
    }
  }
}

function mostrarErrorUsuarios(mensaje) {
  el.usersFeedback.textContent = mensaje;
  el.usersFeedback.className = "settings-feedback is-error";
  el.usersFeedback.hidden = false;
}

if (el.createUserBtn) {
  el.createUserBtn.addEventListener("click", async () => {
    const username = el.newUserUsername.value.trim();
    const password = el.newUserPassword.value;
    const enEdicion = editandoUsuarioId !== null;

    if (!PATRON_USUARIO.test(username)) {
      mostrarErrorUsuarios(
        "El usuario tiene que tener entre 3 y 20 caracteres, solo letras y guion bajo (sin números ni espacios)."
      );
      return;
    }
    // Al crear, la clave es obligatoria (>=6). Al editar, es opcional: si
    // se deja vacía no se cambia; si se pone, igual tiene que ser >=6.
    if (!enEdicion && password.length < 6) {
      mostrarErrorUsuarios("La clave tiene que tener al menos 6 caracteres.");
      return;
    }
    if (enEdicion && password.length > 0 && password.length < 6) {
      mostrarErrorUsuarios("La clave nueva tiene que tener al menos 6 caracteres (o dejala vacía).");
      return;
    }

    el.createUserBtn.disabled = true;
    try {
      if (enEdicion) {
        await callApi(`${API.manageUsers}${editandoUsuarioId}/`, "POST", {
          accion: "editar",
          username,
          password: password || undefined, // vacío = no cambiar la clave
          is_staff: el.newUserIsStaff.checked,
        });
        el.usersFeedback.textContent = `Usuario "${username}" actualizado.`;
        el.usersFeedback.className = "settings-feedback is-success";
        el.usersFeedback.hidden = false;
        salirModoEdicionUsuario();
        await cargarUsuarios();
      } else {
        await callApi(API.manageUsers, "POST", {
          username,
          password,
          is_staff: el.newUserIsStaff.checked,
        });
        el.usersFeedback.textContent = `Usuario "${username}" creado. Anota la clave -- no se puede volver a ver.`;
        el.usersFeedback.className = "settings-feedback is-success";
        el.usersFeedback.hidden = false;
        el.newUserUsername.value = "";
        el.newUserPassword.value = "";
        el.newUserIsStaff.checked = false;
        await cargarUsuarios();
      }
    } catch (err) {
      el.usersFeedback.textContent = err.message;
      el.usersFeedback.className = "settings-feedback is-error";
      el.usersFeedback.hidden = false;
    } finally {
      el.createUserBtn.disabled = false;
    }
  });
}

if (el.usersCloseBtn) {
  el.usersCloseBtn.addEventListener("click", () => {
    el.settingsModal.hidden = true;
  });
}

document.querySelectorAll(".number-stepper-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const input = document.getElementById(btn.dataset.target);
    const paso = Number(btn.dataset.step);
    const min = Number(input.min) || 0;
    const actual = Number(input.value) || 0;
    const nuevo = actual + paso;
    input.value = nuevo < min ? min : Math.round(nuevo * 100) / 100;
  });
});

if (el.settingsSaveBtn) {
  el.settingsSaveBtn.addEventListener("click", async () => {
    const minutos = Number(el.settingsInactivity.value);
    const horas = Number(el.settingsLifetime.value);
    const minBasico = Number(el.settingsTimeBasico.value);
    const minIntermedio = Number(el.settingsTimeIntermedio.value);
    const minDificil = Number(el.settingsTimeDificil.value);
    const todosValidos = [minutos, horas, minBasico, minIntermedio, minDificil].every(
      (v) => v && v > 0
    );
    if (!todosValidos) {
      el.settingsFeedback.textContent = "Ingresa valores válidos, mayores a 0, en todos los campos.";
      el.settingsFeedback.className = "settings-feedback is-error";
      el.settingsFeedback.hidden = false;
      return;
    }

    el.settingsSaveBtn.disabled = true;
    try {
      await callApi(API.platformSettings, "POST", {
        inactivity_timeout_seconds: Math.round(minutos * 60),
        max_lifetime_seconds: Math.round(horas * 3600),
        time_limit_basico_seconds: Math.round(minBasico * 60),
        time_limit_intermedio_seconds: Math.round(minIntermedio * 60),
        time_limit_dificil_seconds: Math.round(minDificil * 60),
      });
      el.settingsFeedback.textContent = `Guardado: ${minutos} min inactividad · básico ${minBasico}m · intermedio ${minIntermedio}m · difícil ${minDificil}m.`;
      el.settingsFeedback.className = "settings-feedback is-success";
      el.settingsFeedback.hidden = false;
      await refresh();
    } catch (err) {
      el.settingsFeedback.textContent = err.message;
      el.settingsFeedback.className = "settings-feedback is-error";
      el.settingsFeedback.hidden = false;
    } finally {
      el.settingsSaveBtn.disabled = false;
    }
  });
}

window.addEventListener("pageshow", () => {
  // Si el navegador restaura la página desde su caché de historial
  // (bfcache) -- por ejemplo, volviendo con el botón "atrás" después de
  // cerrar sesión sin haber cerrado antes este modal -- el DOM vuelve
  // exactamente como quedó, con el modal todavía visible. Se fuerza a
  // cerrado en cada carga/restauración, sin excepción.
  if (el.victoryModal) el.victoryModal.hidden = true;
});

document.addEventListener("keydown", (evento) => {
  if (evento.key === "Escape" && el.victoryModal && !el.victoryModal.hidden) {
    el.victoryModal.hidden = true;
  }
});

(async function init() {
  if (el.victoryModal) el.victoryModal.hidden = true;
  renderSessionInfo();
  try {
    await cargarRetos();
  } catch {
    el.pickerNote.textContent = "No se pudo cargar el catálogo de retos.";
  }
  try {
    const status = await refresh();
    if (status.active) {
      setStatus("Instancia activa — conectando", "warn");
      connectWebSocket();
    } else {
      setStatus("Sin instancia", null);
    }
  } catch (err) {
    setStatus(`Sin estado: ${err.message}`, "down");
  }
})();
