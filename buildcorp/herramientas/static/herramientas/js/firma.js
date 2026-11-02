/* Recuadro de firma: captura el trazo con mouse, lápiz o dedo y lo guarda como PNG. */
(function () {
  document.querySelectorAll("[data-firma]").forEach(function (zona) {
    var lienzo = zona.querySelector("canvas");
    var limpiar = zona.querySelector("[data-firma-limpiar]");
    var aviso = zona.querySelector("[data-firma-aviso]");
    var formulario = zona.closest("form");
    var campo = formulario.querySelector('input[name="firma"]');
    var ctx = lienzo.getContext("2d");
    var dibujando = false;
    var trazos = 0;
    var anterior = null;

    function ajustarTamano() {
      var caja = lienzo.getBoundingClientRect();
      var escala = Math.min(window.devicePixelRatio || 1, 2);
      var respaldo = trazos ? lienzo.toDataURL("image/png") : null;
      lienzo.width = Math.round(caja.width * escala);
      lienzo.height = Math.round(caja.height * escala);
      ctx.setTransform(escala, 0, 0, escala, 0, 0);
      ctx.lineWidth = 2.4;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.strokeStyle = "#17231f";
      if (respaldo) {
        var imagen = new Image();
        imagen.onload = function () { ctx.drawImage(imagen, 0, 0, caja.width, caja.height); };
        imagen.src = respaldo;
      }
    }

    function posicion(evento) {
      var caja = lienzo.getBoundingClientRect();
      return { x: evento.clientX - caja.left, y: evento.clientY - caja.top };
    }

    lienzo.addEventListener("pointerdown", function (evento) {
      evento.preventDefault();
      lienzo.setPointerCapture(evento.pointerId);
      dibujando = true;
      anterior = posicion(evento);
      trazos += 1;
      zona.classList.add("firma--con-trazo");
      zona.classList.remove("firma--error");
      aviso.textContent = "";
      ctx.beginPath();
      ctx.arc(anterior.x, anterior.y, 1.2, 0, Math.PI * 2);
      ctx.fillStyle = "#17231f";
      ctx.fill();
    });

    lienzo.addEventListener("pointermove", function (evento) {
      if (!dibujando) return;
      evento.preventDefault();
      var actual = posicion(evento);
      ctx.beginPath();
      ctx.moveTo(anterior.x, anterior.y);
      ctx.lineTo(actual.x, actual.y);
      ctx.stroke();
      anterior = actual;
    });

    function terminar() { dibujando = false; }
    lienzo.addEventListener("pointerup", terminar);
    lienzo.addEventListener("pointercancel", terminar);

    limpiar.addEventListener("click", function () {
      ctx.clearRect(0, 0, lienzo.width, lienzo.height);
      trazos = 0;
      campo.value = "";
      zona.classList.remove("firma--con-trazo");
    });

    formulario.addEventListener("submit", function (evento) {
      if (!trazos) {
        evento.preventDefault();
        zona.classList.add("firma--error");
        aviso.textContent = "Falta la firma. Pide al responsable que firme en el recuadro.";
        zona.scrollIntoView({ behavior: "smooth", block: "center" });
        return;
      }
      campo.value = lienzo.toDataURL("image/png");
    });

    window.addEventListener("resize", ajustarTamano);
    ajustarTamano();
  });
})();
