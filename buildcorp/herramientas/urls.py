from django.urls import path

from . import views as v

urlpatterns = [
    path("", v.panel, name="panel"),

    path("herramientas/", v.herramienta_lista, name="herramienta_lista"),
    path("herramientas/nueva/", v.herramienta_crear, name="herramienta_crear"),
    path("herramientas/<int:pk>/", v.herramienta_detalle, name="herramienta_detalle"),
    path("herramientas/<int:pk>/editar/", v.herramienta_editar, name="herramienta_editar"),
    path("herramientas/<int:pk>/eliminar/", v.herramienta_eliminar, name="herramienta_eliminar"),
    path("herramientas/<int:pk>/estado/", v.herramienta_cambiar_estado, name="herramienta_cambiar_estado"),

    path("categorias/", v.categoria_lista, name="categoria_lista"),
    path("categorias/nueva/", v.categoria_crear, name="categoria_crear"),
    path("categorias/<int:pk>/editar/", v.categoria_editar, name="categoria_editar"),
    path("categorias/<int:pk>/eliminar/", v.categoria_eliminar, name="categoria_eliminar"),

    path("obras/", v.obra_lista, name="obra_lista"),
    path("obras/nueva/", v.obra_crear, name="obra_crear"),
    path("obras/<int:pk>/editar/", v.obra_editar, name="obra_editar"),
    path("obras/<int:pk>/eliminar/", v.obra_eliminar, name="obra_eliminar"),

    path("contratistas/", v.contratista_lista, name="contratista_lista"),
    path("contratistas/nuevo/", v.contratista_crear, name="contratista_crear"),
    path("contratistas/<int:pk>/", v.contratista_detalle, name="contratista_detalle"),
    path("contratistas/<int:pk>/editar/", v.contratista_editar, name="contratista_editar"),
    path("contratistas/<int:pk>/eliminar/", v.contratista_eliminar, name="contratista_eliminar"),
    path("contratistas/<int:pk>/bloquear/", v.contratista_bloquear, name="contratista_bloquear"),
    path("contratistas/<int:pk>/desbloquear/", v.contratista_desbloquear, name="contratista_desbloquear"),

    path("prestamos/", v.prestamo_lista, name="prestamo_lista"),
    path("prestamos/entrega/", v.entrega_nueva, name="entrega_nueva"),
    path("prestamos/<int:pk>/devolucion/", v.devolucion, name="devolucion"),
    path("prestamos/<int:pk>/acta/", v.prestamo_acta, name="prestamo_acta"),

    path("cobros/", v.cobros, name="cobros"),
    path("cobros/exportar.csv", v.cobros_csv, name="cobros_csv"),

    path("mantenimiento/planes/", v.plan_lista, name="plan_lista"),
    path("mantenimiento/planes/nuevo/", v.plan_crear, name="plan_crear"),
    path("mantenimiento/planes/<int:pk>/editar/", v.plan_editar, name="plan_editar"),
    path("mantenimiento/planes/<int:pk>/eliminar/", v.plan_eliminar, name="plan_eliminar"),
    path("mantenimiento/ordenes/", v.orden_lista, name="orden_lista"),
    path("mantenimiento/ordenes/nueva/", v.orden_crear, name="orden_crear"),
    path("mantenimiento/ordenes/<int:pk>/", v.orden_detalle, name="orden_detalle"),
    path("mantenimiento/ordenes/<int:pk>/iniciar/", v.orden_iniciar, name="orden_iniciar"),
    path("mantenimiento/ordenes/<int:pk>/completar/", v.orden_completar, name="orden_completar"),
    path("mantenimiento/ordenes/<int:pk>/cancelar/", v.orden_cancelar, name="orden_cancelar"),

    path("alertas/", v.alerta_lista, name="alerta_lista"),
    path("alertas/revisar/", v.alertas_procesar, name="alertas_procesar"),
    path("alertas/<int:pk>/revisada/", v.alerta_atender, name="alerta_atender"),
]
