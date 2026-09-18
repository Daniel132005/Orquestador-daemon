/*
 * Indicadores de la pantalla de acceso.
 *
 * El código de respuesta (Sys_check) se mide contra el propio servidor,
 * no es un sello decorativo.
 */

const syscheckEl = document.getElementById("syscheck");

async function probe() {
  try {
    const response = await fetch(window.location.pathname, {
      method: "HEAD",
      cache: "no-store",
    });
    syscheckEl.textContent = `Sys_check: OK (${response.status})`;
  } catch {
    syscheckEl.textContent = "Sys_check: sin respuesta";
  }
}

document.getElementById("toggle-pw").addEventListener("click", () => {
  const input = document.getElementById("password");
  input.type = input.type === "password" ? "text" : "password";
});

probe();
setInterval(probe, 15000);
