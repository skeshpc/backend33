from rest_framework import serializers

from ..models import (
    Alerta, Categoria, Contratista, Firma, Herramienta, MovimientoEstado, Obra,
    OrdenMantenimiento, PlanMantenimiento, Prestamo,
)
from ..validators import normalizar_rut, validar_rut


class CategoriaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Categoria
        fields = ["id", "nombre", "descripcion"]


class ObraSerializer(serializers.ModelSerializer):
    class Meta:
        model = Obra
        fields = ["id", "nombre", "direccion", "comuna", "activa"]


class ContratistaSerializer(serializers.ModelSerializer):
    prestamos_activos = serializers.SerializerMethodField()
    prestamos_vencidos = serializers.SerializerMethodField()

    class Meta:
        model = Contratista
        fields = [
            "id", "razon_social", "rut", "contacto", "telefono", "email", "activo",
            "bloqueado", "bloqueo_automatico", "motivo_bloqueo", "fecha_bloqueo",
            "prestamos_activos", "prestamos_vencidos",
        ]
        read_only_fields = ["bloqueado", "bloqueo_automatico", "motivo_bloqueo", "fecha_bloqueo"]

    def validate_rut(self, valor):
        return normalizar_rut(valor)

    def get_prestamos_activos(self, obj):
        return obj.prestamos.activos().count()

    def get_prestamos_vencidos(self, obj):
        return obj.prestamos.vencidos().count()


class HerramientaSerializer(serializers.ModelSerializer):
    estado_nombre = serializers.CharField(source="get_estado_display", read_only=True)
    categoria_nombre = serializers.CharField(source="categoria.nombre", read_only=True)

    class Meta:
        model = Herramienta
        fields = [
            "id", "codigo", "nombre", "categoria", "categoria_nombre", "marca", "modelo", "numero_serie",
            "estado", "estado_nombre", "ubicacion", "tarifa_diaria", "valor_reposicion", "horas_uso",
            "fecha_adquisicion", "observaciones", "creada", "actualizada",
        ]
        read_only_fields = ["estado", "creada", "actualizada"]


class MovimientoSerializer(serializers.ModelSerializer):
    usuario = serializers.StringRelatedField()

    class Meta:
        model = MovimientoEstado
        fields = ["id", "estado_anterior", "estado_nuevo", "motivo", "usuario", "fecha"]


class CambioEstadoSerializer(serializers.Serializer):
    estado = serializers.ChoiceField(choices=Herramienta.Estado.choices)
    motivo = serializers.CharField(max_length=250)


class FirmaSerializer(serializers.ModelSerializer):
    imagen = serializers.CharField(source="imagen_data_url", read_only=True)
    integra = serializers.BooleanField(source="es_integra", read_only=True)

    class Meta:
        model = Firma
        fields = ["tipo", "nombre", "rut", "fecha", "ip", "huella", "integra", "imagen"]


class PrestamoSerializer(serializers.ModelSerializer):
    numero = serializers.CharField(read_only=True)
    herramienta_codigo = serializers.CharField(source="herramienta.codigo", read_only=True)
    contratista_nombre = serializers.CharField(source="contratista.razon_social", read_only=True)
    obra_nombre = serializers.CharField(source="obra.nombre", read_only=True)
    vencido = serializers.BooleanField(read_only=True)
    dias_atraso = serializers.IntegerField(read_only=True)
    cobro = serializers.DictField(source="cobro_a_la_fecha", read_only=True)

    class Meta:
        model = Prestamo
        fields = [
            "id", "numero", "herramienta", "herramienta_codigo", "contratista", "contratista_nombre",
            "obra", "obra_nombre", "responsable_nombre", "responsable_rut", "fecha_entrega", "fecha_limite",
            "fecha_devolucion", "tarifa_pactada", "condicion_entrega", "condicion_devolucion", "horas_uso",
            "vencido", "dias_atraso", "cobro",
        ]
        read_only_fields = fields


class PrestamoDetalleSerializer(PrestamoSerializer):
    firmas = FirmaSerializer(many=True, read_only=True)

    class Meta(PrestamoSerializer.Meta):
        fields = PrestamoSerializer.Meta.fields + ["observaciones_entrega", "observaciones_devolucion", "firmas"]
        read_only_fields = fields


class EntregaSerializer(serializers.Serializer):
    herramienta = serializers.PrimaryKeyRelatedField(queryset=Herramienta.objects.all())
    contratista = serializers.PrimaryKeyRelatedField(queryset=Contratista.objects.all())
    obra = serializers.PrimaryKeyRelatedField(queryset=Obra.objects.all())
    responsable_nombre = serializers.CharField(max_length=120)
    responsable_rut = serializers.CharField(max_length=12, validators=[validar_rut])
    fecha_limite = serializers.DateField()
    condicion = serializers.ChoiceField(
        choices=[Prestamo.Condicion.BUENA, Prestamo.Condicion.DESGASTE], default=Prestamo.Condicion.BUENA
    )
    observaciones = serializers.CharField(max_length=250, required=False, allow_blank=True, default="")
    firma = serializers.CharField(help_text="Imagen PNG como data URL: data:image/png;base64,...")


class DevolucionSerializer(serializers.Serializer):
    condicion = serializers.ChoiceField(choices=Prestamo.Condicion.choices)
    horas_uso = serializers.DecimalField(max_digits=8, decimal_places=1, min_value=0)
    cargo_danos = serializers.IntegerField(min_value=0, required=False, allow_null=True, default=None)
    observaciones = serializers.CharField(max_length=250, required=False, allow_blank=True, default="")
    responsable_nombre = serializers.CharField(max_length=120)
    responsable_rut = serializers.CharField(max_length=12, validators=[validar_rut])
    firma = serializers.CharField()


class PlanSerializer(serializers.ModelSerializer):
    herramienta_codigo = serializers.CharField(source="herramienta.codigo", read_only=True)
    proxima_fecha = serializers.DateField(read_only=True)
    proximas_horas = serializers.DecimalField(max_digits=10, decimal_places=1, read_only=True)
    situacion = serializers.CharField(read_only=True)

    class Meta:
        model = PlanMantenimiento
        fields = [
            "id", "herramienta", "herramienta_codigo", "nombre", "instrucciones", "intervalo_dias",
            "intervalo_horas", "ultima_fecha", "ultimas_horas", "activo", "proxima_fecha", "proximas_horas", "situacion",
        ]

    def validate(self, datos):
        dias = datos.get("intervalo_dias", getattr(self.instance, "intervalo_dias", None))
        horas = datos.get("intervalo_horas", getattr(self.instance, "intervalo_horas", None))
        if not dias and not horas:
            raise serializers.ValidationError("Define un intervalo en días, en horas de uso o en ambos.")
        return datos


class OrdenSerializer(serializers.ModelSerializer):
    numero = serializers.CharField(read_only=True)
    herramienta_codigo = serializers.CharField(source="herramienta.codigo", read_only=True)

    class Meta:
        model = OrdenMantenimiento
        fields = [
            "id", "numero", "herramienta", "herramienta_codigo", "plan", "tipo", "estado", "descripcion",
            "fecha_programada", "tecnico", "fecha_inicio", "fecha_termino", "trabajo_realizado", "costo",
        ]
        read_only_fields = ["estado", "fecha_inicio", "fecha_termino", "trabajo_realizado", "costo"]

    def validate_herramienta(self, herramienta):
        if herramienta.estado == Herramienta.Estado.BAJA:
            raise serializers.ValidationError("Esta herramienta está dada de baja.")
        return herramienta


class CompletarOrdenSerializer(serializers.Serializer):
    trabajo_realizado = serializers.CharField()
    costo = serializers.IntegerField(min_value=0, default=0)


class AlertaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Alerta
        fields = [
            "id", "tipo", "nivel", "mensaje", "herramienta", "contratista", "prestamo", "plan",
            "creada", "atendida_en", "resuelta_en",
        ]
