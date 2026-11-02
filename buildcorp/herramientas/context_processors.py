from .models import Alerta


def alertas_abiertas(request):
    usuario = getattr(request, "user", None)
    if usuario is None or not usuario.is_authenticated or not usuario.has_perm("herramientas.view_alerta"):
        return {"alertas_pendientes": 0}
    return {
        "alertas_pendientes": Alerta.objects.visibles_para(usuario).filter(resuelta_en__isnull=True, atendida_en__isnull=True).count()
    }
