/*
 * Indicadores de la pantalla de acceso.
 *
 * Todos reflejan el estado real: la latencia y el código de respuesta se
 * miden contra el propio servidor, y el chip de protocolo dice si la
 * conexión va cifrada o no. Nada de sellos decorativos: esta plataforma
 * enseña seguridad, así que no puede mentir sobre la suya.
 */

const linkDot = document.getElementById("link-dot");
const linkText = document.getElementById("link-text");
const latencyEl = document.getElementById("latency");
const syscheckEl = document.getElementById("syscheck");
const protocolChip = document.getElementById("protocol-chip");

function renderProtocol() {
  const secure = window.location.protocol === "https:";
  protocolChip.textContent = secure
    ? "TLS activo // sesión cifrada"
    : "HTTP local // sin cifrar";
  protocolChip.className = secure ? "chip" : "chip is-warn";
}

async function probe() {
  const started = performance.now();
  try {
    const response = await fetch(window.location.pathname, {
      method: "HEAD",
      cache: "no-store",
    });
    const elapsed = Math.round(performance.now() - started);

    linkDot.className = "rail-dot is-ok";
    linkText.textContent = "Enlace activo";
    latencyEl.textContent = `Latencia: ${elapsed}ms`;
    syscheckEl.textContent = `Sys_check: OK (${response.status})`;
  } catch {
    linkDot.className = "rail-dot is-down";
    linkText.textContent = "Sin enlace";
    latencyEl.textContent = "Latencia: —";
    syscheckEl.textContent = "Sys_check: sin respuesta";
  }
}

document.getElementById("toggle-pw").addEventListener("click", () => {
  const input = document.getElementById("password");
  input.type = input.type === "password" ? "text" : "password";
});

renderProtocol();
probe();
setInterval(probe, 15000);
