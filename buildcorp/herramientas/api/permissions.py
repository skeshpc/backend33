from rest_framework.permissions import BasePermission, DjangoModelPermissions


class PermisosDeModelo(DjangoModelPermissions):
    """Como DjangoModelPermissions, pero también exige el permiso de ver para leer."""

    perms_map = {
        **DjangoModelPermissions.perms_map,
        "GET": ["%(app_label)s.view_%(model_name)s"],
        "HEAD": ["%(app_label)s.view_%(model_name)s"],
    }


def requiere(codigo):
    """Crea una clase de permiso para una acción puntual, como devolver o completar."""

    class TienePermiso(BasePermission):
        message = "Tu rol no permite esta acción."

        def has_permission(self, request, view):
            return bool(request.user and request.user.is_authenticated and request.user.has_perm(f"herramientas.{codigo}"))

    return TienePermiso
