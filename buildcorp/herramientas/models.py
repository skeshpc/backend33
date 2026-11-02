"""Modelos del dominio: catálogo, préstamos con firma, mantenimiento y alertas."""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from .validators import normalizar_rut, validar_rut


class Categoria(models.Model):
    nombre = models.CharField(max_length=80, unique=True)
    descripcion = models.CharField("descripción", max_length=200, blank=True)

    class Meta:
        ordering = ["nombre"]
        verbose_name = "categoría"
        verbose_name_plural = "categorías"

    def __str__(self):
        return self.nombre


class Obra(models.Model):
    nombre = models.CharField(max_length=120, unique=True)
    direccion = models.CharField("dirección", max_length=200)
    comuna = models.CharField(max_length=80, blank=True)
    activa = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Contratista(models.Model):
    razon_social = models.CharField("razón social", max_length=150)
    rut = models.CharField("RUT", max_length=12, unique=True, validators=[validar_rut])
    contacto = models.CharField("persona de contacto", max_length=120, blank=True)
    telefono = models.CharField("teléfono", max_length=20, blank=True)
    email = models.EmailField("correo", blank=True)
    activo = models.BooleanField(default=True)
    bloqueado = models.BooleanField(default=False, editable=False)
    bloqueo_automatico = models.BooleanField(default=False, editable=False)
    motivo_bloqueo = models.CharField(max_length=250, blank=True, editable=False)
    fecha_bloqueo = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["razon_social"]
        permissions = [("gestionar_bloqueo", "Puede bloquear y desbloquear contratistas")]

    def __str__(self):
        return self.razon_social

    def clean(self):
        self.rut = normalizar_rut(self.rut)

    def get_absolute_url(self):
        return reverse("contratista_detalle", args=[self.pk])


class Herramienta(models.Model):
    class Estado(models.TextChoices):
        DISPONIBLE = "DISPONIBLE", "Disponible"
        EN_USO = "EN_USO", "En uso"
        MANTENIMIENTO = "MANTENIMIENTO", "Mantenimiento"
        BAJA = "BAJA", "Dado de baja"

    codigo = models.CharField("código", max_length=20, unique=True)
    nombre = models.CharField(max_length=120)
    categoria = models.ForeignKey(Categoria, on_delete=models.PROTECT, verbose_name="categoría")
    marca = models.CharField(max_length=60, blank=True)
    modelo = models.CharField(max_length=60, blank=True)
    numero_serie = models.CharField("número de serie", max_length=60, blank=True)
    estado = models.CharField(max_length=15, choices=Estado.choices, default=Estado.DISPONIBLE, editable=False)
    ubicacion = models.CharField("ubicación en bodega", max_length=80, blank=True)
    tarifa_diaria = models.PositiveIntegerField("tarifa diaria (CLP)", default=0)
    valor_reposicion = models.PositiveIntegerField("valor de reposición (CLP)", default=0)
    horas_uso = models.DecimalField(
        "horas de uso acumuladas",
        max_digits=10,
        decimal_places=1,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    fecha_adquisicion = models.DateField("fecha de adquisición", null=True, blank=True)
    observaciones = models.TextField(blank=True)
    creada = models.DateTimeField(auto_now_add=True)
    actualizada = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["codigo"]
        permissions = [("cambiar_estado", "Puede cambiar el estado de una herramienta")]
        constraints = [
            models.CheckConstraint(
                condition=Q(estado__in=["DISPONIBLE", "EN_USO", "MANTENIMIENTO", "BAJA"]),
                name="herramienta_estado_valido",
            )
        ]

    def __str__(self):
        return f"{self.codigo} · {self.nombre}"

    def save(self, *args, **kwargs):
        self.codigo = (self.codigo or "").strip().upper()
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("herramienta_detalle", args=[self.pk])

    @property
    def prestamo_activo(self):
        return self.prestamos.filter(fecha_devolucion__isnull=True).select_related("contratista", "obra").first()

    def planes_vencidos(self):
        return [plan for plan in self.planes.filter(activo=True) if plan.situacion == PlanMantenimiento.VENCIDO]


class MovimientoEstado(models.Model):
    """Trazabilidad: cada cambio de estado queda registrado y no se modifica."""

    herramienta = models.ForeignKey(Herramienta, on_delete=models.CASCADE, related_name="movimientos")
    estado_anterior = models.CharField(max_length=15, choices=Herramienta.Estado.choices, blank=True)
    estado_nuevo = models.CharField(max_length=15, choices=Herramienta.Estado.choices)
    motivo = models.CharField(max_length=250)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    fecha = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "movimiento de estado"
        verbose_name_plural = "movimientos de estado"

    def __str__(self):
        return f"{self.herramienta.codigo}: {self.estado_anterior or 'alta'} a {self.estado_nuevo}"


class PrestamoQuerySet(models.QuerySet):
    def activos(self):
        return self.filter(fecha_devolucion__isnull=True)

    def vencidos(self, hoy=None):
        hoy = hoy or timezone.localdate()
        return self.activos().filter(fecha_limite__lt=hoy)

    def morosos(self, hoy=None):
        """Préstamos vencidos que ya superaron los días de gracia."""
        hoy = hoy or timezone.localdate()
        return self.activos().filter(fecha_limite__lt=hoy - timedelta(days=settings.MORA_DIAS_GRACIA))


class Prestamo(models.Model):
    class Condicion(models.TextChoices):
        BUENA = "BUENA", "Buena"
        DESGASTE = "DESGASTE", "Con desgaste"
        DANADA = "DANADA", "Dañada"
        PERDIDA = "PERDIDA", "Extraviada"

    herramienta = models.ForeignKey(Herramienta, on_delete=models.PROTECT, related_name="prestamos")
    contratista = models.ForeignKey(Contratista, on_delete=models.PROTECT, related_name="prestamos")
    obra = models.ForeignKey(Obra, on_delete=models.PROTECT, related_name="prestamos")
    responsable_nombre = models.CharField("responsable de obra", max_length=120)
    responsable_rut = models.CharField("RUT del responsable", max_length=12, validators=[validar_rut])

    fecha_entrega = models.DateTimeField(default=timezone.now)
    fecha_limite = models.DateField("fecha límite de devolución")
    tarifa_pactada = models.PositiveIntegerField("tarifa diaria pactada (CLP)")
    condicion_entrega = models.CharField(
        "condición al entregar", max_length=10, choices=Condicion.choices, default=Condicion.BUENA
    )
    observaciones_entrega = models.CharField("observaciones de la entrega", max_length=250, blank=True)
    entregado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="entregas"
    )

    fecha_devolucion = models.DateTimeField(null=True, blank=True)
    condicion_devolucion = models.CharField(
        "condición al devolver", max_length=10, choices=Condicion.choices, blank=True
    )
    observaciones_devolucion = models.CharField("observaciones de la devolución", max_length=250, blank=True)
    horas_uso = models.DecimalField(
        "horas de uso del préstamo", max_digits=8, decimal_places=1, default=Decimal("0")
    )
    recibido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="recepciones"
    )

    dias_cobrados = models.PositiveIntegerField(default=0)
    dias_mora = models.PositiveIntegerField(default=0)
    monto_arriendo = models.PositiveIntegerField(default=0)
    monto_recargo = models.PositiveIntegerField("recargo por mora", default=0)
    cargo_danos = models.PositiveIntegerField("cargo por daño o extravío", default=0)
    monto_total = models.PositiveIntegerField(default=0)

    objects = PrestamoQuerySet.as_manager()

    class Meta:
        ordering = ["-fecha_entrega"]
        verbose_name = "préstamo"
        verbose_name_plural = "préstamos"
        permissions = [
            ("registrar_entrega", "Puede registrar entregas de herramientas"),
            ("registrar_devolucion", "Puede registrar devoluciones de herramientas"),
            ("ver_cobros", "Puede ver y exportar cobros a contratistas"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["herramienta"],
                condition=Q(fecha_devolucion__isnull=True),
                name="una_entrega_activa_por_herramienta",
            )
        ]

    def __str__(self):
        return f"Préstamo {self.numero} · {self.herramienta.codigo}"

    def get_absolute_url(self):
        return reverse("prestamo_acta", args=[self.pk])

    @property
    def numero(self):
        return f"P-{self.pk:05d}"

    @property
    def activo(self):
        return self.fecha_devolucion is None

    @property
    def dias_atraso(self):
        fin = timezone.localdate(self.fecha_devolucion) if self.fecha_devolucion else timezone.localdate()
        return max(0, (fin - self.fecha_limite).days)

    @property
    def vencido(self):
        return self.activo and self.dias_atraso > 0

    def calcular_cobro(self, fecha_cierre=None, cargo_danos=0):
        """Regla de cobro única, usada al devolver y para estimar préstamos abiertos.

        Días cobrados: días corridos desde la entrega, con un mínimo de 1.
        Recargo: porcentaje de la tarifa por cada día posterior a la fecha límite.
        """
        cierre = fecha_cierre or timezone.localdate()
        dias = max(1, (cierre - timezone.localdate(self.fecha_entrega)).days)
        mora = max(0, (cierre - self.fecha_limite).days)
        arriendo = dias * self.tarifa_pactada
        recargo = round(mora * self.tarifa_pactada * settings.RECARGO_MORA_PORCENTAJE / 100)
        return {
            "dias_cobrados": dias,
            "dias_mora": mora,
            "monto_arriendo": arriendo,
            "monto_recargo": recargo,
            "cargo_danos": cargo_danos,
            "monto_total": arriendo + recargo + cargo_danos,
        }

    @property
    def cobro_a_la_fecha(self):
        if self.activo:
            return self.calcular_cobro()
        return {
            "dias_cobrados": self.dias_cobrados,
            "dias_mora": self.dias_mora,
            "monto_arriendo": self.monto_arriendo,
            "monto_recargo": self.monto_recargo,
            "cargo_danos": self.cargo_danos,
            "monto_total": self.monto_total,
        }


class Firma(models.Model):
    class Tipo(models.TextChoices):
        ENTREGA = "ENTREGA", "Entrega"
        DEVOLUCION = "DEVOLUCION", "Devolución"

    prestamo = models.ForeignKey(Prestamo, on_delete=models.PROTECT, related_name="firmas")
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    nombre = models.CharField("firmante", max_length=120)
    rut = models.CharField("RUT", max_length=12, validators=[validar_rut])
    imagen_base64 = models.TextField("trazo de la firma (PNG en base64)")
    huella = models.CharField("huella SHA-256", max_length=64)
    ip = models.GenericIPAddressField("dirección IP", null=True, blank=True)
    fecha = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["fecha"]
        constraints = [models.UniqueConstraint(fields=["prestamo", "tipo"], name="una_firma_por_tipo")]

    def __str__(self):
        return f"Firma de {self.get_tipo_display().lower()} · {self.prestamo.numero}"

    @property
    def imagen_data_url(self):
        return f"data:image/png;base64,{self.imagen_base64}"

    @property
    def es_integra(self):
        from .services import calcular_huella

        return self.huella == calcular_huella(self)


class PlanMantenimiento(models.Model):
    AL_DIA = "AL_DIA"
    PROXIMO = "PROXIMO"
    VENCIDO = "VENCIDO"
    SITUACIONES = {AL_DIA: "Al día", PROXIMO: "Próximo", VENCIDO: "Vencido"}

    herramienta = models.ForeignKey(Herramienta, on_delete=models.CASCADE, related_name="planes")
    nombre = models.CharField(max_length=120)
    instrucciones = models.TextField(blank=True)
    intervalo_dias = models.PositiveIntegerField(
        "cada cuántos días", null=True, blank=True, validators=[MinValueValidator(1)]
    )
    intervalo_horas = models.DecimalField(
        "cada cuántas horas de uso",
        max_digits=8,
        decimal_places=1,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.1"))],
    )
    ultima_fecha = models.DateField("última mantención", default=timezone.localdate)
    ultimas_horas = models.DecimalField("horas en la última mantención", max_digits=10, decimal_places=1, default=0)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["herramienta__codigo", "nombre"]
        verbose_name = "plan de mantenimiento"
        verbose_name_plural = "planes de mantenimiento"
        constraints = [
            models.CheckConstraint(
                condition=Q(intervalo_dias__isnull=False) | Q(intervalo_horas__isnull=False),
                name="plan_con_algun_intervalo",
            )
        ]

    def __str__(self):
        return f"{self.nombre} · {self.herramienta.codigo}"

    @property
    def proxima_fecha(self):
        if self.intervalo_dias:
            return self.ultima_fecha + timedelta(days=self.intervalo_dias)
        return None

    @property
    def proximas_horas(self):
        if self.intervalo_horas:
            return self.ultimas_horas + self.intervalo_horas
        return None

    @property
    def horas_restantes(self):
        if self.intervalo_horas:
            return self.proximas_horas - self.herramienta.horas_uso
        return None

    @property
    def situacion(self):
        hoy = timezone.localdate()
        fecha = self.proxima_fecha
        horas = self.proximas_horas
        uso = self.herramienta.horas_uso
        if (fecha and hoy >= fecha) or (horas is not None and uso >= horas):
            return self.VENCIDO
        # El aviso nunca supera el 20 % del intervalo: un plan semanal no debe nacer "próximo".
        dias_aviso = min(settings.MANTENCION_AVISO_DIAS, (self.intervalo_dias or 0) // 5)
        aviso_fecha = fecha and hoy >= fecha - timedelta(days=dias_aviso)
        aviso_horas = horas is not None and uso >= horas - self.intervalo_horas * Decimal("0.1")
        return self.PROXIMO if aviso_fecha or aviso_horas else self.AL_DIA

    @property
    def situacion_display(self):
        return self.SITUACIONES[self.situacion]


class OrdenMantenimiento(models.Model):
    class Tipo(models.TextChoices):
        PREVENTIVA = "PREVENTIVA", "Preventiva"
        CORRECTIVA = "CORRECTIVA", "Correctiva"

    class Estado(models.TextChoices):
        PROGRAMADA = "PROGRAMADA", "Programada"
        EN_CURSO = "EN_CURSO", "En curso"
        COMPLETADA = "COMPLETADA", "Completada"
        CANCELADA = "CANCELADA", "Cancelada"

    herramienta = models.ForeignKey(Herramienta, on_delete=models.PROTECT, related_name="ordenes")
    plan = models.ForeignKey(
        PlanMantenimiento, null=True, blank=True, on_delete=models.SET_NULL, related_name="ordenes"
    )
    prestamo_origen = models.ForeignKey(
        Prestamo, null=True, blank=True, on_delete=models.SET_NULL, related_name="ordenes"
    )
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.PREVENTIVA)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PROGRAMADA, editable=False)
    descripcion = models.CharField("descripción", max_length=250)
    fecha_programada = models.DateField(default=timezone.localdate)
    tecnico = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="ordenes"
    )
    fecha_inicio = models.DateTimeField(null=True, blank=True, editable=False)
    fecha_termino = models.DateTimeField(null=True, blank=True, editable=False)
    trabajo_realizado = models.TextField(blank=True)
    costo = models.PositiveIntegerField("costo (CLP)", default=0)
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha_programada", "-id"]
        verbose_name = "orden de mantenimiento"
        verbose_name_plural = "órdenes de mantenimiento"
        permissions = [("ejecutar_orden", "Puede iniciar, completar y cancelar órdenes")]

    def __str__(self):
        return f"{self.numero} · {self.herramienta.codigo}"

    @property
    def numero(self):
        return f"OT-{self.pk:05d}"

    @property
    def abierta(self):
        return self.estado in {self.Estado.PROGRAMADA, self.Estado.EN_CURSO}


class AlertaQuerySet(models.QuerySet):
    def visibles_para(self, usuario):
        """Quien no puede ver préstamos (técnicos) solo recibe las alertas de mantención."""
        if usuario.has_perm("herramientas.view_prestamo"):
            return self
        return self.filter(tipo=Alerta.Tipo.MANTENCION)


class Alerta(models.Model):
    class Tipo(models.TextChoices):
        VENCE_PRONTO = "VENCE_PRONTO", "Devolución por vencer"
        MOROSIDAD = "MOROSIDAD", "Devolución vencida"
        BLOQUEO = "BLOQUEO", "Contratista bloqueado"
        MANTENCION = "MANTENCION", "Mantención"

    class Nivel(models.TextChoices):
        AVISO = "AVISO", "Aviso"
        CRITICO = "CRITICO", "Crítico"

    tipo = models.CharField(max_length=15, choices=Tipo.choices)
    nivel = models.CharField(max_length=10, choices=Nivel.choices, default=Nivel.AVISO)
    mensaje = models.CharField(max_length=300)
    clave = models.CharField(max_length=80, help_text="Evita duplicar una alerta abierta sobre lo mismo.")
    herramienta = models.ForeignKey(Herramienta, null=True, blank=True, on_delete=models.CASCADE, related_name="alertas")
    contratista = models.ForeignKey(Contratista, null=True, blank=True, on_delete=models.CASCADE, related_name="alertas")
    prestamo = models.ForeignKey(Prestamo, null=True, blank=True, on_delete=models.CASCADE, related_name="alertas")
    plan = models.ForeignKey(PlanMantenimiento, null=True, blank=True, on_delete=models.CASCADE, related_name="alertas")
    creada = models.DateTimeField(auto_now_add=True)
    atendida_en = models.DateTimeField("revisada el", null=True, blank=True)
    atendida_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    resuelta_en = models.DateTimeField(null=True, blank=True)

    objects = AlertaQuerySet.as_manager()

    class Meta:
        ordering = ["-creada", "-id"]
        permissions = [("atender_alerta", "Puede marcar alertas como revisadas y ejecutar la revisión")]
        constraints = [
            models.UniqueConstraint(
                fields=["clave"], condition=Q(resuelta_en__isnull=True), name="una_alerta_abierta_por_clave"
            )
        ]

    def __str__(self):
        return self.mensaje
