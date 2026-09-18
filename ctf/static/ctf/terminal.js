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
  xpDisplay: document.getElementById("user-xp-display"),
  flagBar: document.getElementById("flag-bar"),
  flagForm: document.getElementById("flag-form"),
  flagInput: document.getElementById("flag-input"),
  flagSubmitBtn: document.getElementById("btn-submit-flag"),
  flagStatusBadge: document.getElementById("flag-status-badge"),
  flagFeedback: document.getElementById("flag-feedback"),
  victoryModal: document.getElementById("victory-modal"),
  victoryChallengeName: document.getElementById("victory-challenge-name"),
  victoryXpGain: document.getElementById("victory-xp-gain"),
  victoryMessage: document.getElementById("victory-message"),
  victoryCloseBtn: document.getElementById("btn-victory-close"),
  countdownBadge: document.getElementById("countdown-badge"),
  destroyedToast: document.getElementById("destroyed-toast"),
  destroyedToastText: document.getElementById("destroyed-toast-text"),
  destroyedToastClose: document.getElementById("destroyed-toast-close"),
  userChip: document.getElementById("user-chip"),
  settingsModal: document.getElementById("settings-modal"),
  settingsInactivity: document.getElementById("settings-inactivity"),
  settingsLifetime: document.getElementById("settings-lifetime"),
  settingsTimeBasico: document.getElementById("settings-time-basico"),
  settingsTimeIntermedio: document.getElementById("settings-time-intermedio"),
  settingsTimeDificil: document.getElementById("settings-time-dificil"),
  settingsFeedback: document.getElementById("settings-feedback"),
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
    throw new Error(payload.error || `Error ${response.status}`);
  }
  return payload;
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
  el.maxLifetime.textContent = formatTimeout(status.max_lifetime_seconds);

  if (status.user_xp !== undefined && el.xpDisplay) {
    el.xpDisplay.textContent = status.user_xp;
  }

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

function agruparPorCategoria(retos) {
  const grupos = new Map();
  retos.forEach((reto) => {
    const [codigo, nombre] = reto.owasp.split(" - ");
    if (!grupos.has(codigo)) grupos.set(codigo, { codigo, nombre, retos: [] });
    grupos.get(codigo).retos.push(reto);
  });
  return Array.from(grupos.values()).sort((a, b) => a.codigo.localeCompare(b.codigo));
}

function crearTarjetaReto(reto) {
  const label = document.createElement("label");
  label.className = "challenge-card";
  if (reto.solved) label.classList.add("is-solved");
  label.dataset.slug = reto.slug;

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
      <span class="xp-tag">+${reto.xp || 100} XP</span>
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

  agruparPorCategoria(disponibles).forEach((grupo) => {
    const seccion = document.createElement("div");
    seccion.className = "category-group";

    const head = document.createElement("div");
    head.className = "category-head";
    head.innerHTML = `
      <span class="category-code">${grupo.codigo}</span>
      <span class="category-name">${grupo.nombre}</span>
      <span class="category-count">${grupo.retos.length} reto${grupo.retos.length === 1 ? "" : "s"}</span>
    `;
    seccion.appendChild(head);

    const lista = document.createElement("div");
    lista.className = "category-cards";
    grupo.retos.forEach((reto) => lista.appendChild(crearTarjetaReto(reto)));
    seccion.appendChild(lista);

    el.picker.appendChild(seccion);
  });

  mostrarBriefingSeleccionado();
}

function retosFiltrados() {
  if (filtroDificultad === "todos") return todosLosRetos;
  return todosLosRetos.filter((reto) => reto.difficulty === filtroDificultad);
}

function aplicarFiltro(dificultad) {
  filtroDificultad = dificultad;
  document.querySelectorAll(".difficulty-filter-btn").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.difficulty === dificultad);
  });
  renderChallengePicker(retosFiltrados());
}

document.querySelectorAll(".difficulty-filter-btn").forEach((btn) => {
  btn.addEventListener("click", () => aplicarFiltro(btn.dataset.difficulty));
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

  // No sabemos con certeza cuál de los dos mecanismos la mató (el
  // servidor borra la fila sin dejar rastro de "por qué" accesible
  // desde el frontend), pero se puede estimar: si ya llevaba casi toda
  // su vida máxima permitida, lo más probable es que la haya matado eso
  // y no la inactividad.
  let motivo = "por inactividad o por alcanzar su tiempo máximo de vida";
  if (ultimaInstanciaActiva && ultimaInstanciaActiva.created_at) {
    const vivaDesde = Date.now() - new Date(ultimaInstanciaActiva.created_at).getTime();
    const vidaMaximaMs = (ultimaInstanciaActiva.max_lifetime_seconds || 0) * 1000;
    if (vidaMaximaMs > 0 && vivaDesde >= vidaMaximaMs * 0.9) {
      motivo = "por alcanzar su tiempo máximo de vida";
    } else {
      motivo = "por inactividad";
    }
  }

  el.destroyedToastText.textContent =
    `El watchdog la destruyó automáticamente ${motivo}. Desplegá una nueva si la necesitás.`;
  el.destroyedToast.hidden = false;
}

if (el.destroyedToastClose) {
  el.destroyedToastClose.addEventListener("click", () => {
    el.destroyedToast.hidden = true;
  });
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
        mostrarToastDestruccion();
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
    setStatus("Elegí un reto antes de desplegar", "warn");
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
  setLink(true);
  // Para el countdown, que se apague apenas se sabe que ya no está
  // activa. Para el toast de "se destruyó sola" (mostrarToastDestruccion,
  // en resincronizar) hace falta el último snapshot ACTIVO, así que ese
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

        if (res.total_xp !== undefined && el.xpDisplay) {
          el.xpDisplay.textContent = res.total_xp;
        }

        el.flagStatusBadge.textContent = "✓ Resuelto";
        el.flagStatusBadge.className = "flag-bar-status is-solved";

        el.victoryChallengeName.textContent = res.challenge_name || "Reto Completado";
        el.victoryXpGain.textContent = res.newly_solved ? `+${res.xp_awarded} XP` : "✓ Ya Resuelto";
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
      el.settingsFeedback.textContent = "Ingresá valores válidos, mayores a 0, en todos los campos.";
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
  renderProtocol();
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
    setLink(false);
    setStatus(`Sin estado: ${err.message}`, "down");
  }
})();
