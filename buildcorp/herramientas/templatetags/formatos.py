from django import template

register = template.Library()


@register.filter
def clp(valor):
    """1234567 se muestra como $1.234.567."""
    try:
        return f"${int(valor):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "$0"


@register.filter
def nombre_de(usuario, si_no_hay="Sin registrar"):
    """Nombre completo o usuario. Tolera campos vacíos, como una orden sin técnico."""
    if not usuario:
        return si_no_hay
    return usuario.get_full_name() or usuario.username


@register.filter
def rol_de(usuario):
    if usuario.is_superuser:
        return "Superusuario"
    grupo = usuario.groups.first()
    return grupo.name if grupo else "Sin rol"
