"""Django Admin personalizado. Las acciones usan los mismos servicios que la web y la API."""
from django.contrib import admin, messages
from django.db.models import Count
from django.utils.html import format_html

from . import services
from .models import (
    Alerta, Categoria, Contratista, Firma, Herramienta, MovimientoEstado,
    Obra, OrdenMantenimiento, PlanMantenimiento, Prestamo,
)

COLORES_ESTADO = {
    "DISPONIBLE": "#1d6b45", "EN_USO": "#1f5a9e", "MANTENIMIENTO": "#9a6200", "BAJA": "#5c6663",
}


def clp(valor):
    return f"${valor:,.0f}".replace(",", ".")


def _ejecutar(modeladmin, request, queryset, funcion, exito):
    correctas = 0
    for objeto in queryset:
        try:
            funcion(objeto)
            correctas += 1
        except services.ReglaNegocio as error:
            modeladmin.message_user(request, f"{objeto}: {error.mensaje}", messages.ERROR)
    if correctas:
        modeladmin.message_user(request, f"{exito}: {correctas}.", messages.SUCCESS)


class SoloLecturaInline(admin.TabularInline):
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class MovimientoInline(SoloLecturaInline):
    model = MovimientoEstado
    fields = ("fecha", "estado_anterior", "estado_nuevo", "motivo", "usuario")


class PlanInline(admin.TabularInline):
    model = PlanMantenimiento
    extra = 0
    fields = ("nombre", "intervalo_dias", "intervalo_horas", "ultima_fecha", "ultimas_horas", "activo")


class FirmaInline(SoloLecturaInline):
    model = Firma
    fields = ("tipo", "nombre", "rut", "fecha", "vista_firma", "huella")
    readonly_fields = ("vista_firma",)

    @admin.display(description="Firma")
    def vista_firma(self, obj):
        return format_html('<img src="{}" alt="Firma" style="height:60px;background:#fff">', obj.imagen_data_url)


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "descripcion", "total_herramientas")
    search_fields = ("nombre",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(total=Count("herramienta"))

    @admin.display(description="Herramientas", ordering="total")
    def total_herramientas(self, obj):
        return obj.total


@admin.register(Obra)
class ObraAdmin(admin.ModelAdmin):
    list_display = ("nombre", "direccion", "comuna", "activa")
    list_filter = ("activa", "comuna")
    list_editable = ("activa",)
    search_fields = ("nombre", "direccion")


@admin.register(Contratista)
class ContratistaAdmin(admin.ModelAdmin):
    list_display = ("razon_social", "rut", "contacto", "telefono", "activo", "bloqueado", "motivo_bloqueo")
    list_filter = ("bloqueado", "bloqueo_automatico", "activo")
    search_fields = ("razon_social", "rut", "contacto")
    readonly_fields = ("bloqueado", "bloqueo_automatico", "motivo_bloqueo", "fecha_bloqueo")
    actions = ["desbloquear"]

    @admin.action(description="Desbloquear contratistas sin morosidad")
    def desbloquear(self, request, queryset):
        _ejecutar(self, request, queryset, services.desbloquear_contratista, "Contratistas desbloqueados")


@admin.register(Herramienta)
class HerramientaAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nombre", "categoria", "estado_coloreado", "horas_uso", "tarifa_clp", "ubicacion")
    list_filter = ("estado", "categoria", "marca")
    search_fields = ("codigo", "nombre", "marca", "modelo", "numero_serie")
    readonly_fields = ("estado", "creada", "actualizada")
    list_select_related = ("categoria",)
    list_per_page = 30
    inlines = [PlanInline, MovimientoInline]
    actions = ["enviar_a_mantenimiento", "marcar_disponible", "dar_de_baja"]
    fieldsets = (
        ("Identificación", {"fields": ("codigo", "nombre", "categoria", "marca", "modelo", "numero_serie")}),
        ("Estado y uso", {"fields": ("estado", "ubicacion", "horas_uso", "fecha_adquisicion")}),
        ("Valores", {"fields": ("tarifa_diaria", "valor_reposicion")}),
        ("Otros", {"fields": ("observaciones", "creada", "actualizada"), "classes": ("collapse",)}),
    )

    @admin.display(description="Estado", ordering="estado")
    def estado_coloreado(self, obj):
        return format_html(
            '<strong style="color:{}">{}</strong>', COLORES_ESTADO[obj.estado], obj.get_estado_display()
        )

    @admin.display(description="Tarifa diaria", ordering="tarifa_diaria")
    def tarifa_clp(self, obj):
        return clp(obj.tarifa_diaria)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change:
            services.registrar_alta(obj, request.user)

    def _cambiar(self, request, queryset, estado, motivo, exito):
        _ejecutar(self, request, queryset, lambda h: services.cambiar_estado(h, estado, request.user, motivo), exito)

    @admin.action(description="Enviar a mantenimiento")
    def enviar_a_mantenimiento(self, request, queryset):
        self._cambiar(request, queryset, Herramienta.Estado.MANTENIMIENTO, "Cambio desde el administrador", "Enviadas a mantenimiento")

    @admin.action(description="Marcar como disponible")
    def marcar_disponible(self, request, queryset):
        self._cambiar(request, queryset, Herramienta.Estado.DISPONIBLE, "Cambio desde el administrador", "Marcadas como disponibles")

    @admin.action(description="Dar de baja")
    def dar_de_baja(self, request, queryset):
        self._cambiar(request, queryset, Herramienta.Estado.BAJA, "Baja desde el administrador", "Dadas de baja")


@admin.register(MovimientoEstado)
class MovimientoAdmin(admin.ModelAdmin):
    list_display = ("fecha", "herramienta", "estado_anterior", "estado_nuevo", "motivo", "usuario")
    list_filter = ("estado_nuevo", "fecha")
    search_fields = ("herramienta__codigo", "motivo")
    date_hierarchy = "fecha"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Prestamo)
class PrestamoAdmin(admin.ModelAdmin):
    """El préstamo se abre y cierra con firma, por eso aquí solo se consulta."""

    list_display = ("numero", "herramienta", "contratista", "obra", "fecha_entrega", "fecha_limite", "situacion", "total_clp")
    list_filter = ("contratista", "obra", "condicion_devolucion")
    search_fields = ("herramienta__codigo", "contratista__razon_social", "responsable_nombre", "responsable_rut")
    date_hierarchy = "fecha_entrega"
    list_select_related = ("herramienta", "contratista", "obra")
    inlines = [FirmaInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Situación")
    def situacion(self, obj):
        if not obj.activo:
            return "Devuelto"
        if obj.vencido:
            return format_html('<strong style="color:#b42318">Vencido hace {} día(s)</strong>', obj.dias_atraso)
        return "En préstamo"

    @admin.display(description="Total", ordering="monto_total")
    def total_clp(self, obj):
        return clp(obj.cobro_a_la_fecha["monto_total"])


@admin.register(Firma)
class FirmaAdmin(admin.ModelAdmin):
    list_display = ("prestamo", "tipo", "nombre", "rut", "fecha", "integra")
    list_filter = ("tipo",)
    search_fields = ("nombre", "rut", "prestamo__herramienta__codigo")
    fields = ("prestamo", "tipo", "nombre", "rut", "fecha", "ip", "vista_firma", "huella", "integra")
    readonly_fields = fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Firma")
    def vista_firma(self, obj):
        return format_html('<img src="{}" alt="Firma" style="max-height:140px;background:#fff">', obj.imagen_data_url)

    @admin.display(description="Íntegra", boolean=True)
    def integra(self, obj):
        return obj.es_integra


@admin.register(PlanMantenimiento)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("nombre", "herramienta", "intervalo_dias", "intervalo_horas", "proxima_fecha", "proximas_horas", "situacion_display", "activo")
    list_filter = ("activo",)
    search_fields = ("nombre", "herramienta__codigo")
    autocomplete_fields = ("herramienta",)
    list_select_related = ("herramienta",)


@admin.register(OrdenMantenimiento)
class OrdenAdmin(admin.ModelAdmin):
    list_display = ("numero", "herramienta", "tipo", "estado", "fecha_programada", "tecnico", "costo")
    list_filter = ("estado", "tipo")
    search_fields = ("herramienta__codigo", "descripcion")
    autocomplete_fields = ("herramienta",)
    readonly_fields = ("estado", "fecha_inicio", "fecha_termino")
    date_hierarchy = "fecha_programada"
    list_select_related = ("herramienta", "tecnico")
    actions = ["iniciar", "cancelar"]

    @admin.action(description="Iniciar órdenes seleccionadas")
    def iniciar(self, request, queryset):
        _ejecutar(self, request, queryset, lambda o: services.iniciar_orden(o, request.user), "Órdenes iniciadas")

    @admin.action(description="Cancelar órdenes seleccionadas")
    def cancelar(self, request, queryset):
        _ejecutar(self, request, queryset, lambda o: services.cancelar_orden(o, request.user), "Órdenes canceladas")


@admin.register(Alerta)
class AlertaAdmin(admin.ModelAdmin):
    list_display = ("mensaje", "tipo", "nivel", "creada", "atendida_en", "resuelta_en")
    list_filter = ("tipo", "nivel", ("resuelta_en", admin.EmptyFieldListFilter))
    search_fields = ("mensaje",)
    actions = ["marcar_revisadas"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Marcar como revisadas")
    def marcar_revisadas(self, request, queryset):
        _ejecutar(self, request, queryset, lambda a: services.atender_alerta(a, request.user), "Alertas revisadas")
