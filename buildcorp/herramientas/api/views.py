"""API REST. Comparte con la web las mismas reglas, ubicadas en services.py."""
from django.db.models import Count, ProtectedError
from rest_framework import mixins, status, viewsets
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import exception_handler

from .. import services
from ..models import (
    Alerta, Categoria, Contratista, Herramienta, Obra, OrdenMantenimiento, PlanMantenimiento, Prestamo,
)
from ..views import ip_cliente
from . import serializers as s
from .permissions import requiere


def manejar_excepciones(error, contexto):
    """Convierte errores de negocio y borrados protegidos en respuestas claras."""
    if isinstance(error, services.ReglaNegocio):
        return Response({"detail": error.mensaje}, status=error.codigo_http)
    if isinstance(error, ProtectedError):
        return Response(
            {"detail": "No se puede eliminar: tiene registros asociados."}, status=status.HTTP_409_CONFLICT
        )
    return exception_handler(error, contexto)


class TokenView(ObtainAuthToken):
    """Entrega un token a cambio de usuario y contraseña. Limitado a 10 intentos por minuto."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "token"


class AccionesMixin:
    """Permite declarar en cada ViewSet un permiso propio para cada acción."""

    permisos_por_accion = {}

    def get_permissions(self):
        codigo = self.permisos_por_accion.get(self.action)
        if codigo:
            return [requiere(codigo)()]
        return super().get_permissions()


class CategoriaViewSet(viewsets.ModelViewSet):
    queryset = Categoria.objects.all()
    serializer_class = s.CategoriaSerializer


class ObraViewSet(viewsets.ModelViewSet):
    queryset = Obra.objects.all()
    serializer_class = s.ObraSerializer


class ContratistaViewSet(AccionesMixin, viewsets.ModelViewSet):
    queryset = Contratista.objects.all()
    serializer_class = s.ContratistaSerializer
    permisos_por_accion = {"bloquear": "gestionar_bloqueo", "desbloquear": "gestionar_bloqueo"}

    @action(detail=True, methods=["post"])
    def bloquear(self, request, pk=None):
        contratista = services.bloquear_contratista(self.get_object(), request.data.get("motivo"))
        return Response(self.get_serializer(contratista).data)

    @action(detail=True, methods=["post"])
    def desbloquear(self, request, pk=None):
        contratista = services.desbloquear_contratista(self.get_object())
        return Response(self.get_serializer(contratista).data)


class HerramientaViewSet(AccionesMixin, viewsets.ModelViewSet):
    queryset = Herramienta.objects.select_related("categoria")
    serializer_class = s.HerramientaSerializer
    permisos_por_accion = {"cambiar_estado": "cambiar_estado", "trazabilidad": "view_movimientoestado"}

    def get_queryset(self):
        queryset = super().get_queryset()
        estado = self.request.query_params.get("estado")
        if estado:
            queryset = queryset.filter(estado=estado)
        return queryset

    def perform_create(self, serializer):
        services.registrar_alta(serializer.save(), self.request.user)

    @action(detail=True, methods=["post"], url_path="cambiar-estado")
    def cambiar_estado(self, request, pk=None):
        datos = s.CambioEstadoSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        herramienta = self.get_object()
        services.cambiar_estado(herramienta, datos.validated_data["estado"], request.user, datos.validated_data["motivo"])
        herramienta.refresh_from_db()
        return Response(self.get_serializer(herramienta).data)

    @action(detail=True, methods=["get"])
    def trazabilidad(self, request, pk=None):
        movimientos = self.get_object().movimientos.select_related("usuario")
        return Response(s.MovimientoSerializer(movimientos, many=True).data)


class PrestamoViewSet(AccionesMixin, mixins.CreateModelMixin, viewsets.ReadOnlyModelViewSet):
    """POST registra una entrega con firma. Un préstamo no se edita ni se elimina."""

    queryset = Prestamo.objects.select_related("herramienta", "contratista", "obra")
    permisos_por_accion = {"create": "registrar_entrega", "devolver": "registrar_devolucion"}

    def get_serializer_class(self):
        if self.action == "create":
            return s.EntregaSerializer
        if self.action == "devolver":
            return s.DevolucionSerializer
        if self.action == "retrieve":
            return s.PrestamoDetalleSerializer
        return s.PrestamoSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        situacion = self.request.query_params.get("situacion")
        if situacion == "activos":
            queryset = queryset.activos()
        elif situacion == "vencidos":
            queryset = queryset.vencidos()
        return queryset

    def create(self, request, *args, **kwargs):
        datos = s.EntregaSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        prestamo = services.registrar_entrega(
            usuario=request.user, ip=ip_cliente(request), **datos.validated_data
        )
        return Response(s.PrestamoDetalleSerializer(prestamo).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def devolver(self, request, pk=None):
        datos = s.DevolucionSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        prestamo = services.registrar_devolucion(
            prestamo=self.get_object(), usuario=request.user, ip=ip_cliente(request), **datos.validated_data
        )
        return Response(s.PrestamoDetalleSerializer(prestamo).data)


class PlanViewSet(viewsets.ModelViewSet):
    queryset = PlanMantenimiento.objects.select_related("herramienta")
    serializer_class = s.PlanSerializer


class OrdenViewSet(AccionesMixin, viewsets.ModelViewSet):
    queryset = OrdenMantenimiento.objects.select_related("herramienta")
    serializer_class = s.OrdenSerializer
    permisos_por_accion = {"iniciar": "ejecutar_orden", "completar": "ejecutar_orden", "cancelar": "ejecutar_orden"}

    @action(detail=True, methods=["post"])
    def iniciar(self, request, pk=None):
        return Response(self.get_serializer(services.iniciar_orden(self.get_object(), request.user)).data)

    @action(detail=True, methods=["post"])
    def completar(self, request, pk=None):
        datos = s.CompletarOrdenSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        orden = services.completar_orden(
            self.get_object(), request.user, datos.validated_data["trabajo_realizado"], datos.validated_data["costo"]
        )
        return Response(self.get_serializer(orden).data)

    @action(detail=True, methods=["post"])
    def cancelar(self, request, pk=None):
        return Response(self.get_serializer(services.cancelar_orden(self.get_object(), request.user)).data)


class AlertaViewSet(AccionesMixin, viewsets.ReadOnlyModelViewSet):
    queryset = Alerta.objects.all()
    serializer_class = s.AlertaSerializer
    permisos_por_accion = {"atender": "atender_alerta", "procesar": "atender_alerta"}

    def get_queryset(self):
        queryset = super().get_queryset().visibles_para(self.request.user)
        if self.request.query_params.get("abiertas"):
            queryset = queryset.filter(resuelta_en__isnull=True)
        return queryset

    @action(detail=True, methods=["post"])
    def atender(self, request, pk=None):
        return Response(self.get_serializer(services.atender_alerta(self.get_object(), request.user)).data)

    @action(detail=False, methods=["post"])
    def procesar(self, request):
        return Response(services.procesar_alertas())


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def resumen(request):
    """Datos breves que la interfaz consulta en segundo plano para mantener al día el aviso de alertas."""
    conteo = {fila["estado"]: fila["total"] for fila in Herramienta.objects.values("estado").annotate(total=Count("id"))}
    datos = {
        "herramientas": {estado: conteo.get(estado, 0) for estado in Herramienta.Estado.values},
        "alertas_pendientes": 0,
    }
    if request.user.has_perm("herramientas.view_alerta"):
        datos["alertas_pendientes"] = Alerta.objects.visibles_para(request.user).filter(
            resuelta_en__isnull=True, atendida_en__isnull=True
        ).count()
    if request.user.has_perm("herramientas.view_prestamo"):
        datos["prestamos_activos"] = Prestamo.objects.activos().count()
        datos["prestamos_vencidos"] = Prestamo.objects.vencidos().count()
    if request.user.has_perm("herramientas.view_contratista"):
        datos["contratistas_bloqueados"] = Contratista.objects.filter(bloqueado=True).count()
    return Response(datos)
