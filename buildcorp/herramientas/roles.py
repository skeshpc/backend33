"""Roles del sistema, creados como grupos de Django después de cada migración."""
from django.contrib.auth.models import Group, Permission

MODELOS = [
    "categoria", "obra", "contratista", "herramienta", "movimientoestado",
    "prestamo", "firma", "planmantenimiento", "ordenmantenimiento", "alerta",
]
SOLO_LECTURA = [f"view_{modelo}" for modelo in MODELOS]

ADMINISTRADOR = "Administrador"
BODEGUERO = "Bodeguero"
TECNICO = "Técnico"
SUPERVISOR = "Supervisor"

ROLES = {
    # Administrador recibe todos los permisos de la aplicación (ver sincronizar_roles).
    ADMINISTRADOR: None,
    BODEGUERO: SOLO_LECTURA + [
        "registrar_entrega", "registrar_devolucion", "ver_cobros", "atender_alerta",
        "add_herramienta", "change_herramienta", "cambiar_estado",
    ],
    TECNICO: [
        "view_categoria", "view_herramienta", "view_movimientoestado", "view_alerta",
        "view_planmantenimiento", "add_planmantenimiento", "change_planmantenimiento", "delete_planmantenimiento",
        "view_ordenmantenimiento", "add_ordenmantenimiento", "change_ordenmantenimiento", "ejecutar_orden",
        "cambiar_estado", "atender_alerta",
    ],
    SUPERVISOR: SOLO_LECTURA + ["ver_cobros"],
}


def sincronizar_roles(**kwargs):
    permisos_app = Permission.objects.filter(content_type__app_label="herramientas")
    for nombre, codigos in ROLES.items():
        grupo, _ = Group.objects.get_or_create(name=nombre)
        if codigos is None:
            grupo.permissions.set(permisos_app)
        else:
            grupo.permissions.set(permisos_app.filter(codename__in=codigos))
