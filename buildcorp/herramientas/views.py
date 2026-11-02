"""Vistas web. Son funciones simples: validan, llaman a un servicio y responden."""
import csv
from datetime import datetime
from itertools import groupby

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db.models import Count, ProtectedError, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import services
from .forms import (
    BloqueoForm, CambioEstadoForm, CategoriaForm, CompletarOrdenForm, ContratistaForm, DevolucionForm,
    EntregaForm, HerramientaForm, ObraForm, OrdenForm, PlanForm,
)
from .models import (
    Alerta, Categoria, Contratista, Herramienta, Obra, OrdenMantenimiento, PlanMantenimiento, Prestamo,
)


def permiso(codigo):
    return permission_required(f"herramientas.{codigo}", raise_exception=True)


def ip_cliente(request):
    """Nginx deja la IP real en X-Real-IP; sin proxy se usa la conexión directa."""
    return request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR")


def paginar(request, queryset, por_pagina=25):
    return Paginator(queryset, por_pagina).get_page(request.GET.get("pagina"))


def eliminar_generico(request, objeto, volver, nombre):
    """Confirma con GET y borra con POST. Lo que tiene historial queda protegido."""
    if request.method == "POST":
        try:
            objeto.delete()
        except ProtectedError:
            messages.error(request, f"No se puede eliminar {objeto}: tiene registros asociados.")
            return redirect(volver)
        messages.success(request, f"{nombre} eliminado.")
        return redirect(volver)
    return render(request, "herramientas/confirmar_eliminar.html", {"objeto": objeto, "volver": volver, "nombre": nombre})


# ---------------------------------------------------------------- Panel


@login_required
def panel(request):
    herramientas = list(Herramienta.objects.select_related("categoria").order_by("categoria__nombre", "codigo"))
    vencidos = list(
        Prestamo.objects.vencidos().select_related("herramienta", "contratista", "obra").order_by("fecha_limite")
    )
    ids_vencidas = {p.herramienta_id for p in vencidos}
    planes = list(PlanMantenimiento.objects.filter(activo=True).select_related("herramienta"))
    atencion = [p for p in planes if p.situacion != PlanMantenimiento.AL_DIA]
    atencion.sort(key=lambda p: (p.situacion != PlanMantenimiento.VENCIDO, p.herramienta.codigo))
    ids_mantencion = {p.herramienta_id for p in atencion if p.situacion == PlanMantenimiento.VENCIDO}
    for herramienta in herramientas:
        herramienta.atrasada = herramienta.pk in ids_vencidas
        herramienta.mantencion_vencida = herramienta.pk in ids_mantencion

    conteo = {fila["estado"]: fila["total"] for fila in Herramienta.objects.values("estado").annotate(total=Count("id"))}
    estados = [
        {"valor": e.value, "nombre": e.label, "total": conteo.get(e.value, 0)} for e in Herramienta.Estado
    ]
    tablero = [
        {"categoria": nombre, "herramientas": list(grupo)}
        for nombre, grupo in groupby(herramientas, key=lambda h: h.categoria.nombre)
    ]
    contexto = {
        "tablero": tablero,
        "estados": estados,
        "total_herramientas": len(herramientas),
        "vencidos": vencidos[:6],
        "total_vencidos": len(vencidos),
        "planes_atencion": atencion[:6],
        "total_planes_atencion": len(atencion),
        "bloqueados": Contratista.objects.filter(bloqueado=True),
    }
    return render(request, "herramientas/panel.html", contexto)


# ---------------------------------------------------------------- Catálogo


@login_required
@permiso("view_herramienta")
def herramienta_lista(request):
    consulta = request.GET.get("q", "").strip()
    estado = request.GET.get("estado", "")
    categoria = request.GET.get("categoria", "")
    herramientas = Herramienta.objects.select_related("categoria")
    if consulta:
        herramientas = herramientas.filter(
            Q(codigo__icontains=consulta) | Q(nombre__icontains=consulta)
            | Q(marca__icontains=consulta) | Q(modelo__icontains=consulta) | Q(numero_serie__icontains=consulta)
        )
    if estado in Herramienta.Estado.values:
        herramientas = herramientas.filter(estado=estado)
    if categoria.isdigit():
        herramientas = herramientas.filter(categoria_id=categoria)
    parametros = request.GET.copy()
    parametros.pop("pagina", None)
    return render(request, "herramientas/herramienta_lista.html", {
        "pagina": paginar(request, herramientas),
        "consulta": consulta,
        "estado": estado,
        "categoria": categoria,
        "estados": Herramienta.Estado.choices,
        "categorias": Categoria.objects.all(),
        "parametros": parametros.urlencode(),
    })


@login_required
@permiso("view_herramienta")
def herramienta_detalle(request, pk):
    herramienta = get_object_or_404(Herramienta.objects.select_related("categoria"), pk=pk)
    opciones = services.TRANSICIONES_MANUALES[Herramienta.Estado(herramienta.estado)]
    orden_opciones = [e for e in Herramienta.Estado if e in opciones]
    return render(request, "herramientas/herramienta_detalle.html", {
        "herramienta": herramienta,
        "prestamo": herramienta.prestamo_activo,
        "movimientos": herramienta.movimientos.select_related("usuario")[:30],
        "prestamos": herramienta.prestamos.select_related("contratista", "obra")[:10],
        "planes": herramienta.planes.select_related("herramienta"),
        "ordenes": herramienta.ordenes.all()[:10],
        "form_estado": CambioEstadoForm(opciones=orden_opciones) if orden_opciones else None,
    })


def _formulario(request, form_class, instancia, titulo, volver, exito, plantilla="herramientas/formulario.html", al_guardar=None):
    form = form_class(request.POST or None, instance=instancia)
    if request.method == "POST" and form.is_valid():
        objeto = form.save()
        if al_guardar:
            al_guardar(objeto)
        messages.success(request, exito)
        return redirect(objeto.get_absolute_url() if hasattr(objeto, "get_absolute_url") else volver)
    return render(request, plantilla, {"form": form, "titulo": titulo, "volver": volver})


@login_required
@permiso("add_herramienta")
def herramienta_crear(request):
    return _formulario(
        request, HerramientaForm, None, "Agregar herramienta", "herramienta_lista", "Herramienta agregada.",
        al_guardar=lambda h: services.registrar_alta(h, request.user),
    )


@login_required
@permiso("change_herramienta")
def herramienta_editar(request, pk):
    herramienta = get_object_or_404(Herramienta, pk=pk)
    return _formulario(request, HerramientaForm, herramienta, f"Editar {herramienta.codigo}", "herramienta_lista", "Cambios guardados.")


@login_required
@permiso("delete_herramienta")
def herramienta_eliminar(request, pk):
    herramienta = get_object_or_404(Herramienta, pk=pk)
    return eliminar_generico(request, herramienta, "herramienta_lista", "Herramienta")


@login_required
@permiso("cambiar_estado")
@require_POST
def herramienta_cambiar_estado(request, pk):
    herramienta = get_object_or_404(Herramienta, pk=pk)
    opciones = services.TRANSICIONES_MANUALES[Herramienta.Estado(herramienta.estado)]
    form = CambioEstadoForm(request.POST, opciones=opciones)
    if not form.is_valid():
        messages.error(request, "Elige un estado y escribe el motivo.")
        return redirect(herramienta)
    try:
        services.cambiar_estado(herramienta, form.cleaned_data["estado"], request.user, form.cleaned_data["motivo"])
        messages.success(request, "Estado actualizado.")
    except services.ReglaNegocio as error:
        messages.error(request, error.mensaje)
    return redirect(herramienta)


# ---------------------------------------------------------------- Categorías y obras


@login_required
@permiso("view_categoria")
def categoria_lista(request):
    categorias = Categoria.objects.annotate(total=Count("herramienta")).order_by("nombre")
    return render(request, "herramientas/categoria_lista.html", {"categorias": categorias})


@login_required
@permiso("add_categoria")
def categoria_crear(request):
    return _formulario(request, CategoriaForm, None, "Agregar categoría", "categoria_lista", "Categoría agregada.")


@login_required
@permiso("change_categoria")
def categoria_editar(request, pk):
    categoria = get_object_or_404(Categoria, pk=pk)
    return _formulario(request, CategoriaForm, categoria, f"Editar {categoria.nombre}", "categoria_lista", "Cambios guardados.")


@login_required
@permiso("delete_categoria")
def categoria_eliminar(request, pk):
    return eliminar_generico(request, get_object_or_404(Categoria, pk=pk), "categoria_lista", "Categoría")


@login_required
@permiso("view_obra")
def obra_lista(request):
    obras = Obra.objects.annotate(
        activos=Count("prestamos", filter=Q(prestamos__fecha_devolucion__isnull=True))
    ).order_by("nombre")
    return render(request, "herramientas/obra_lista.html", {"obras": obras})


@login_required
@permiso("add_obra")
def obra_crear(request):
    return _formulario(request, ObraForm, None, "Agregar obra", "obra_lista", "Obra agregada.")


@login_required
@permiso("change_obra")
def obra_editar(request, pk):
    obra = get_object_or_404(Obra, pk=pk)
    return _formulario(request, ObraForm, obra, f"Editar {obra.nombre}", "obra_lista", "Cambios guardados.")


@login_required
@permiso("delete_obra")
def obra_eliminar(request, pk):
    return eliminar_generico(request, get_object_or_404(Obra, pk=pk), "obra_lista", "Obra")


# ---------------------------------------------------------------- Contratistas


@login_required
@permiso("view_contratista")
def contratista_lista(request):
    consulta = request.GET.get("q", "").strip()
    contratistas = Contratista.objects.annotate(
        activos=Count("prestamos", filter=Q(prestamos__fecha_devolucion__isnull=True)),
        vencidos=Count(
            "prestamos",
            filter=Q(prestamos__fecha_devolucion__isnull=True, prestamos__fecha_limite__lt=timezone.localdate()),
        ),
    ).order_by("razon_social")
    if consulta:
        contratistas = contratistas.filter(Q(razon_social__icontains=consulta) | Q(rut__icontains=consulta))
    if request.GET.get("bloqueados"):
        contratistas = contratistas.filter(bloqueado=True)
    return render(request, "herramientas/contratista_lista.html", {
        "pagina": paginar(request, contratistas), "consulta": consulta, "solo_bloqueados": bool(request.GET.get("bloqueados")),
    })


@login_required
@permiso("view_contratista")
def contratista_detalle(request, pk):
    contratista = get_object_or_404(Contratista, pk=pk)
    prestamos = list(contratista.prestamos.select_related("herramienta", "obra")[:40])
    facturado = contratista.prestamos.filter(fecha_devolucion__isnull=False).aggregate(total=Sum("monto_total"))["total"] or 0
    return render(request, "herramientas/contratista_detalle.html", {
        "contratista": contratista,
        "prestamos": prestamos,
        "abiertos": [p for p in prestamos if p.activo],
        "facturado": facturado,
        "form_bloqueo": BloqueoForm(),
    })


@login_required
@permiso("add_contratista")
def contratista_crear(request):
    return _formulario(request, ContratistaForm, None, "Agregar contratista", "contratista_lista", "Contratista agregado.")


@login_required
@permiso("change_contratista")
def contratista_editar(request, pk):
    contratista = get_object_or_404(Contratista, pk=pk)
    return _formulario(request, ContratistaForm, contratista, f"Editar {contratista.razon_social}", "contratista_lista", "Cambios guardados.")


@login_required
@permiso("delete_contratista")
def contratista_eliminar(request, pk):
    return eliminar_generico(request, get_object_or_404(Contratista, pk=pk), "contratista_lista", "Contratista")


@login_required
@permiso("gestionar_bloqueo")
@require_POST
def contratista_bloquear(request, pk):
    contratista = get_object_or_404(Contratista, pk=pk)
    try:
        services.bloquear_contratista(contratista, request.POST.get("motivo"))
        messages.success(request, "Contratista bloqueado.")
    except services.ReglaNegocio as error:
        messages.error(request, error.mensaje)
    return redirect(contratista)


@login_required
@permiso("gestionar_bloqueo")
@require_POST
def contratista_desbloquear(request, pk):
    contratista = get_object_or_404(Contratista, pk=pk)
    try:
        services.desbloquear_contratista(contratista)
        messages.success(request, "Contratista desbloqueado.")
    except services.ReglaNegocio as error:
        messages.error(request, error.mensaje)
    return redirect(contratista)


# ---------------------------------------------------------------- Préstamos


@login_required
@permiso("view_prestamo")
def prestamo_lista(request):
    vista = request.GET.get("vista", "activos")
    prestamos = Prestamo.objects.select_related("herramienta", "contratista", "obra")
    if vista == "vencidos":
        prestamos = prestamos.vencidos().order_by("fecha_limite")
    elif vista == "historial":
        prestamos = prestamos.filter(fecha_devolucion__isnull=False).order_by("-fecha_devolucion")
    else:
        vista = "activos"
        prestamos = prestamos.activos().order_by("fecha_limite")
    consulta = request.GET.get("q", "").strip()
    if consulta:
        prestamos = prestamos.filter(
            Q(herramienta__codigo__icontains=consulta) | Q(herramienta__nombre__icontains=consulta)
            | Q(contratista__razon_social__icontains=consulta) | Q(responsable_nombre__icontains=consulta)
        )
    return render(request, "herramientas/prestamo_lista.html", {
        "pagina": paginar(request, prestamos),
        "vista": vista,
        "consulta": consulta,
        "total_activos": Prestamo.objects.activos().count(),
        "total_vencidos": Prestamo.objects.vencidos().count(),
    })


@login_required
@permiso("registrar_entrega")
def entrega_nueva(request):
    inicial = {}
    if request.GET.get("herramienta", "").isdigit():
        inicial["herramienta"] = request.GET["herramienta"]
    form = EntregaForm(request.POST or None, initial=inicial)
    error_regla = None
    if request.method == "POST" and form.is_valid():
        datos = form.cleaned_data
        try:
            prestamo = services.registrar_entrega(
                herramienta=datos["herramienta"], contratista=datos["contratista"], obra=datos["obra"],
                responsable_nombre=datos["responsable_nombre"], responsable_rut=datos["responsable_rut"],
                fecha_limite=datos["fecha_limite"], condicion=datos["condicion"],
                observaciones=datos["observaciones"], firma=datos["firma"],
                usuario=request.user, ip=ip_cliente(request),
            )
        except services.ReglaNegocio as error:
            error_regla = error.mensaje
        else:
            messages.success(request, f"Entrega {prestamo.numero} registrada con firma.")
            return redirect("prestamo_acta", pk=prestamo.pk)
    return render(request, "herramientas/entrega.html", {"form": form, "error_regla": error_regla})


@login_required
@permiso("registrar_devolucion")
def devolucion(request, pk):
    prestamo = get_object_or_404(Prestamo.objects.select_related("herramienta", "contratista", "obra"), pk=pk)
    if not prestamo.activo:
        messages.info(request, f"El préstamo {prestamo.numero} ya fue devuelto.")
        return redirect("prestamo_acta", pk=prestamo.pk)
    inicial = {"responsable_nombre": prestamo.responsable_nombre, "responsable_rut": prestamo.responsable_rut}
    form = DevolucionForm(request.POST or None, initial=inicial)
    error_regla = None
    if request.method == "POST" and form.is_valid():
        datos = form.cleaned_data
        try:
            services.registrar_devolucion(
                prestamo=prestamo, condicion=datos["condicion"], horas_uso=datos["horas_uso"],
                cargo_danos=datos["cargo_danos"], observaciones=datos["observaciones"],
                responsable_nombre=datos["responsable_nombre"], responsable_rut=datos["responsable_rut"],
                firma=datos["firma"], usuario=request.user, ip=ip_cliente(request),
            )
        except services.ReglaNegocio as error:
            error_regla = error.mensaje
        else:
            messages.success(request, f"Devolución de {prestamo.numero} registrada con firma.")
            return redirect("prestamo_acta", pk=prestamo.pk)
    return render(request, "herramientas/devolucion.html", {
        "form": form, "prestamo": prestamo, "cobro": prestamo.calcular_cobro(), "error_regla": error_regla,
    })


@login_required
@permiso("view_prestamo")
def prestamo_acta(request, pk):
    prestamo = get_object_or_404(
        Prestamo.objects.select_related("herramienta", "contratista", "obra", "entregado_por", "recibido_por"), pk=pk
    )
    firmas = {firma.tipo: firma for firma in prestamo.firmas.select_related("prestamo__herramienta", "prestamo__contratista")}
    return render(request, "herramientas/prestamo_acta.html", {
        "prestamo": prestamo,
        "cobro": prestamo.cobro_a_la_fecha,
        "firma_entrega": firmas.get("ENTREGA"),
        "firma_devolucion": firmas.get("DEVOLUCION"),
    })


# ---------------------------------------------------------------- Cobros


def _cobros_filtrados(request):
    prestamos = Prestamo.objects.filter(fecha_devolucion__isnull=False).select_related("herramienta", "contratista", "obra")
    contratista = request.GET.get("contratista", "")
    if contratista.isdigit():
        prestamos = prestamos.filter(contratista_id=contratista)
    for parametro, filtro in (("desde", "fecha_devolucion__date__gte"), ("hasta", "fecha_devolucion__date__lte")):
        try:
            fecha = datetime.strptime(request.GET.get(parametro, ""), "%Y-%m-%d").date()
        except ValueError:
            continue
        prestamos = prestamos.filter(**{filtro: fecha})
    return prestamos.order_by("-fecha_devolucion")


@login_required
@permiso("ver_cobros")
def cobros(request):
    prestamos = _cobros_filtrados(request)
    totales = prestamos.aggregate(
        arriendo=Sum("monto_arriendo"), recargo=Sum("monto_recargo"), danos=Sum("cargo_danos"), total=Sum("monto_total")
    )
    return render(request, "herramientas/cobros.html", {
        "pagina": paginar(request, prestamos),
        "totales": totales,
        "contratistas": Contratista.objects.all(),
        "contratista": request.GET.get("contratista", ""),
        "desde": request.GET.get("desde", ""),
        "hasta": request.GET.get("hasta", ""),
        "parametros": request.GET.urlencode(),
    })


def _celda_segura(valor):
    """Evita que Excel interprete como fórmula un texto escrito por un usuario."""
    texto = str(valor)
    return f"'{texto}" if texto[:1] in ("=", "+", "-", "@", "\t", "\r") else texto


@login_required
@permiso("ver_cobros")
def cobros_csv(request):
    respuesta = HttpResponse(content_type="text/csv; charset=utf-8")
    respuesta["Content-Disposition"] = 'attachment; filename="cobros_buildcorp.csv"'
    respuesta.write("﻿")
    escritor = csv.writer(respuesta, delimiter=";")
    escritor.writerow([
        "Préstamo", "Herramienta", "Contratista", "RUT", "Obra", "Entrega", "Límite", "Devolución",
        "Días", "Días de mora", "Tarifa", "Arriendo", "Recargo", "Cargo por daño", "Total",
    ])
    for p in _cobros_filtrados(request):
        escritor.writerow([
            p.numero, _celda_segura(p.herramienta.codigo), _celda_segura(p.contratista.razon_social), p.contratista.rut,
            _celda_segura(p.obra.nombre), timezone.localtime(p.fecha_entrega).date().isoformat(),
            p.fecha_limite.isoformat(), timezone.localtime(p.fecha_devolucion).date().isoformat(),
            p.dias_cobrados, p.dias_mora, p.tarifa_pactada, p.monto_arriendo, p.monto_recargo, p.cargo_danos, p.monto_total,
        ])
    return respuesta


# ---------------------------------------------------------------- Mantenimiento


@login_required
@permiso("view_planmantenimiento")
def plan_lista(request):
    planes = list(PlanMantenimiento.objects.select_related("herramienta"))
    prioridad = {PlanMantenimiento.VENCIDO: 0, PlanMantenimiento.PROXIMO: 1, PlanMantenimiento.AL_DIA: 2}
    planes.sort(key=lambda p: (not p.activo, prioridad[p.situacion], p.herramienta.codigo))
    return render(request, "herramientas/plan_lista.html", {"planes": planes})


@login_required
@permiso("add_planmantenimiento")
def plan_crear(request):
    inicial = {}
    if request.GET.get("herramienta", "").isdigit():
        herramienta = Herramienta.objects.filter(pk=request.GET["herramienta"]).first()
        if herramienta:
            inicial = {"herramienta": herramienta.pk, "ultimas_horas": herramienta.horas_uso}
    form = PlanForm(request.POST or None, initial=inicial)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Plan agregado.")
        return redirect("plan_lista")
    return render(request, "herramientas/formulario.html", {"form": form, "titulo": "Agregar plan de mantenimiento", "volver": "plan_lista"})


@login_required
@permiso("change_planmantenimiento")
def plan_editar(request, pk):
    plan = get_object_or_404(PlanMantenimiento, pk=pk)
    return _formulario(request, PlanForm, plan, f"Editar {plan.nombre}", "plan_lista", "Cambios guardados.")


@login_required
@permiso("delete_planmantenimiento")
def plan_eliminar(request, pk):
    return eliminar_generico(request, get_object_or_404(PlanMantenimiento, pk=pk), "plan_lista", "Plan")


@login_required
@permiso("view_ordenmantenimiento")
def orden_lista(request):
    estado = request.GET.get("estado", "abiertas")
    ordenes = OrdenMantenimiento.objects.select_related("herramienta", "tecnico", "plan")
    if estado in OrdenMantenimiento.Estado.values:
        ordenes = ordenes.filter(estado=estado)
    elif estado == "todas":
        pass
    else:
        estado = "abiertas"
        ordenes = ordenes.filter(estado__in=[OrdenMantenimiento.Estado.PROGRAMADA, OrdenMantenimiento.Estado.EN_CURSO])
    return render(request, "herramientas/orden_lista.html", {
        "pagina": paginar(request, ordenes),
        "estado": estado,
        "estados": OrdenMantenimiento.Estado.choices,
    })


@login_required
@permiso("add_ordenmantenimiento")
def orden_crear(request):
    form = OrdenForm(request.POST or None, initial={"herramienta": request.GET.get("herramienta")})
    if request.method == "POST" and form.is_valid():
        orden = form.save()
        messages.success(request, f"Orden {orden.numero} programada.")
        return redirect("orden_detalle", pk=orden.pk)
    return render(request, "herramientas/formulario.html", {"form": form, "titulo": "Programar orden de mantenimiento", "volver": "orden_lista"})


@login_required
@permiso("view_ordenmantenimiento")
def orden_detalle(request, pk):
    orden = get_object_or_404(OrdenMantenimiento.objects.select_related("herramienta", "tecnico", "plan"), pk=pk)
    return render(request, "herramientas/orden_detalle.html", {"orden": orden, "form": CompletarOrdenForm()})


def _accion_orden(request, pk, accion, exito):
    orden = get_object_or_404(OrdenMantenimiento, pk=pk)
    try:
        accion(orden)
        messages.success(request, exito)
    except services.ReglaNegocio as error:
        messages.error(request, error.mensaje)
    return redirect("orden_detalle", pk=pk)


@login_required
@permiso("ejecutar_orden")
@require_POST
def orden_iniciar(request, pk):
    return _accion_orden(request, pk, lambda o: services.iniciar_orden(o, request.user), "Orden iniciada. La herramienta quedó en mantenimiento.")


@login_required
@permiso("ejecutar_orden")
@require_POST
def orden_completar(request, pk):
    form = CompletarOrdenForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Describe el trabajo realizado e indica un costo válido.")
        return redirect("orden_detalle", pk=pk)
    return _accion_orden(
        request, pk,
        lambda o: services.completar_orden(o, request.user, form.cleaned_data["trabajo_realizado"], form.cleaned_data["costo"]),
        "Orden completada.",
    )


@login_required
@permiso("ejecutar_orden")
@require_POST
def orden_cancelar(request, pk):
    return _accion_orden(request, pk, lambda o: services.cancelar_orden(o, request.user), "Orden cancelada.")


# ---------------------------------------------------------------- Alertas


@login_required
@permiso("view_alerta")
def alerta_lista(request):
    vista = request.GET.get("vista", "abiertas")
    alertas = Alerta.objects.visibles_para(request.user).select_related("atendida_por")
    if vista == "resueltas":
        alertas = alertas.filter(resuelta_en__isnull=False).order_by("-resuelta_en")
    else:
        vista = "abiertas"
        alertas = alertas.filter(resuelta_en__isnull=True).order_by("atendida_en", "nivel", "-creada")
    return render(request, "herramientas/alerta_lista.html", {"pagina": paginar(request, alertas), "vista": vista})


@login_required
@permiso("atender_alerta")
@require_POST
def alerta_atender(request, pk):
    services.atender_alerta(get_object_or_404(Alerta.objects.visibles_para(request.user), pk=pk), request.user)
    messages.success(request, "Alerta marcada como revisada.")
    return redirect("alerta_lista")


@login_required
@permiso("atender_alerta")
@require_POST
def alertas_procesar(request):
    r = services.procesar_alertas()
    messages.success(
        request,
        f"Revisión terminada: {r['alertas_nuevas']} alertas nuevas, {r['contratistas_bloqueados']} bloqueos, "
        f"{r['contratistas_desbloqueados']} desbloqueos y {r['ordenes_creadas']} órdenes programadas.",
    )
    return redirect("alerta_lista")


# ---------------------------------------------------------------- Errores


def error_403(request, exception=None):
    return render(request, "herramientas/error.html", {
        "codigo": 403, "titulo": "Tu rol no permite esta acción",
        "detalle": "Pide acceso a un administrador si necesitas hacerla.",
    }, status=403)


def error_404(request, exception=None):
    return render(request, "herramientas/error.html", {
        "codigo": 404, "titulo": "Esta página no existe",
        "detalle": "Revisa la dirección o vuelve al panel.",
    }, status=404)


def error_500(request):
    return render(request, "herramientas/error.html", {
        "codigo": 500, "titulo": "El servidor no pudo completar la acción",
        "detalle": "Vuelve a intentarlo. Si se repite, revisa el registro del servicio.",
    }, status=500)
