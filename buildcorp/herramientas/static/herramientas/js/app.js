(function () {
  /* Menú en pantallas pequeñas */
  var boton = document.querySelector("[data-menu-boton]");
  var menu = document.getElementById("menu");
  if (boton && menu) {
    boton.addEventListener("click", function () {
      var abierto = menu.classList.toggle("lateral--abierta");
      boton.setAttribute("aria-expanded", abierto ? "true" : "false");
    });
  }

  /* Aviso de alertas: se actualiza en segundo plano consultando la API */
  var aviso = document.querySelector("[data-alertas]");
  function refrescarAlertas() {
    fetch("/api/v1/resumen/", { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (datos) {
        if (!datos || !aviso) return;
        aviso.textContent = datos.alertas_pendientes;
        aviso.hidden = !datos.alertas_pendientes;
      })
      .catch(function () { /* sin conexión: se reintenta en el próximo ciclo */ });
  }
  if (aviso) setInterval(refrescarAlertas, 60000);

  /* Entrega: consulta si el contratista elegido puede recibir herramientas */
  var selector = document.querySelector("[data-contratista-estado]");
  if (selector) {
    var salida = document.getElementById("estado-contratista");
    var enviar = document.querySelector("[data-enviar-entrega]");
    var revisar = function () {
      salida.hidden = true;
      if (enviar) enviar.disabled = false;
      if (!selector.value) return;
      fetch("/api/v1/contratistas/" + encodeURIComponent(selector.value) + "/", {
        credentials: "same-origin", headers: { Accept: "application/json" },
      })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (c) {
          if (!c) return;
          salida.hidden = false;
          salida.className = "aviso-campo";
          if (c.bloqueado) {
            salida.classList.add("aviso-campo--error");
            salida.textContent = c.razon_social + " está bloqueado: " + c.motivo_bloqueo + ". Registra sus devoluciones antes de entregarle herramientas.";
            if (enviar) enviar.disabled = true;
          } else if (c.prestamos_vencidos > 0) {
            salida.classList.add("aviso-campo--error");
            salida.textContent = c.razon_social + " tiene devoluciones vencidas: " + c.prestamos_vencidos + ".";
          } else {
            salida.classList.add("aviso-campo--ok");
            salida.textContent = c.razon_social + " puede recibir herramientas. Préstamos abiertos: " + c.prestamos_activos + ".";
          }
        })
        .catch(function () {});
    };
    selector.addEventListener("change", revisar);
    revisar();
  }

  /* Devolución: explica el cargo que se aplicará según la condición */
  var condicion = document.querySelector("[data-condicion]");
  if (condicion) {
    var nota = document.getElementById("nota-condicion");
    var cargo = document.getElementById("id_cargo_danos");
    var reposicion = condicion.getAttribute("data-reposicion");
    var textos = {
      BUENA: "La herramienta vuelve a quedar disponible.",
      DESGASTE: "La herramienta vuelve a quedar disponible y el desgaste queda en el acta.",
      DANADA: "La herramienta pasa a mantenimiento y se abre una orden correctiva.",
      PERDIDA: "La herramienta se da de baja y se cobra su valor de reposición: " + reposicion + ".",
    };
    var mostrar = function () {
      nota.textContent = textos[condicion.value] || "";
      if (cargo) cargo.placeholder = condicion.value === "PERDIDA" ? "Valor de reposición" : "0";
    };
    condicion.addEventListener("change", mostrar);
    mostrar();
  }
})();
