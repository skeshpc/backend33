"""Reglas de negocio. Las vistas web, la API y el admin pasan por estas funciones,
así una regla se cumple igual sin importar por dónde entre la operación."""
import base64
import binascii
import hashlib
import io
from datetime import timedelta, timezone as tz
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from PIL import Image, UnidentifiedImageError

from .models import Alerta, Contratista, Firma, Herramienta, MovimientoEstado, OrdenMantenimiento, PlanMantenimiento, Prestamo
from .validators import normalizar_rut, validar_rut

Estado = Herramienta.Estado

# Cambios que una persona puede pedir directamente. EN_USO no aparece porque
# solo se llega a ese estado registrando una entrega con firma.
TRANSICIONES_MANUALES = {
    Estado.DISPONIBLE: {Estado.MANTENIMIENTO, Estado.BAJA},
    Estado.EN_USO: set(),
    Estado.MANTENIMIENTO: {Estado.DISPONIBLE, Estado.BAJA},
    Estado.BAJA: set(),
}

FIRMA_PREFIJO = "data:image/png;base64,"
FIRMA_MAX_BYTES = 1_000_000
FIRMA_MIN_PIXELES = 150


class ReglaNegocio(Exception):
    """Una operación válida en forma, pero que el negocio no permite."""

    codigo_http = 409

    def __init__(self, mensaje):
        super().__init__(mensaje)
        self.mensaje = mensaje


class DatosInvalidos(ReglaNegocio):
    codigo_http = 400


def _devoluciones_vencidas(cantidad):
    return "1 devolución vencida" if cantidad == 1 else f"{cantidad} devoluciones vencidas"


# ---------------------------------------------------------------- Estado


def _registrar_estado(herramienta, nuevo, usuario, motivo):
    anterior = herramienta.estado
    herramienta.estado = nuevo
    herramienta.save(update_fields=["estado", "actualizada"])
    return MovimientoEstado.objects.create(
        herramienta=herramienta, estado_anterior=anterior, estado_nuevo=nuevo, motivo=motivo, usuario=usuario
    )


def registrar_alta(herramienta, usuario):
    MovimientoEstado.objects.create(
        herramienta=herramienta, estado_nuevo=herramienta.estado, motivo="Alta en el catálogo", usuario=usuario
    )


@transaction.atomic
def cambiar_estado(herramienta, nuevo, usuario, motivo):
    herramienta = Herramienta.objects.select_for_update().get(pk=herramienta.pk)
    motivo = (motivo or "").strip()
    if not motivo:
        raise DatosInvalidos("Escribe el motivo del cambio de estado.")
    if nuevo not in TRANSICIONES_MANUALES[herramienta.estado]:
        raise ReglaNegocio(
            f"No se puede pasar de «{herramienta.get_estado_display()}» a «{Estado(nuevo).label}» directamente."
        )
    if herramienta.ordenes.filter(estado=OrdenMantenimiento.Estado.EN_CURSO).exists():
        raise ReglaNegocio("Esta herramienta tiene una orden en curso. Complétala o cancélala primero.")
    movimiento = _registrar_estado(herramienta, nuevo, usuario, motivo)
    if nuevo == Estado.BAJA:
        herramienta.planes.update(activo=False)
        herramienta.ordenes.filter(estado=OrdenMantenimiento.Estado.PROGRAMADA).update(
            estado=OrdenMantenimiento.Estado.CANCELADA
        )
        _resolver_alertas(Q(herramienta=herramienta))
    return movimiento


# ---------------------------------------------------------------- Firma


def decodificar_firma(data_url):
    """Valida que el trazo sea un PNG real y no esté en blanco. Devuelve el PNG limpio."""
    if not data_url or not data_url.startswith(FIRMA_PREFIJO):
        raise DatosInvalidos("Falta la firma del responsable.")
    try:
        contenido = base64.b64decode(data_url[len(FIRMA_PREFIJO):], validate=True)
    except (binascii.Error, ValueError):
        raise DatosInvalidos("La firma recibida está dañada. Pide al responsable que firme de nuevo.")
    if len(contenido) > FIRMA_MAX_BYTES:
        raise DatosInvalidos("La firma pesa más de 1 MB. Limpia el recuadro y firma de nuevo.")
    try:
        imagen = Image.open(io.BytesIO(contenido))
        if imagen.format != "PNG" or imagen.width > 4000 or imagen.height > 2000:
            raise DatosInvalidos("La firma debe ser una imagen PNG de tamaño normal.")
        imagen = imagen.convert("RGBA")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise DatosInvalidos("La firma recibida no es una imagen válida.")
    # El lienzo es transparente: los píxeles visibles son el trazo.
    visibles = imagen.getchannel("A").point(lambda a: 255 if a > 32 else 0).histogram()[255]
    if visibles < FIRMA_MIN_PIXELES:
        raise DatosInvalidos("La firma está en blanco. Pide al responsable que firme en el recuadro.")
    salida = io.BytesIO()
    imagen.save(salida, format="PNG", optimize=True)
    return salida.getvalue()


def calcular_huella(firma):
    """SHA-256 que une el trazo con los datos del préstamo: si algo cambia, deja de coincidir."""
    prestamo = firma.prestamo
    fecha = firma.fecha.astimezone(tz.utc).isoformat()
    datos = "|".join(
        [str(prestamo.pk), firma.tipo, firma.nombre, firma.rut, fecha, prestamo.herramienta.codigo, prestamo.contratista.rut]
    )
    return hashlib.sha256(datos.encode() + base64.b64decode(firma.imagen_base64)).hexdigest()


def _guardar_firma(prestamo, tipo, nombre, rut, data_url, ip):
    png = decodificar_firma(data_url)
    firma = Firma(
        prestamo=prestamo, tipo=tipo, nombre=nombre, rut=rut,
        imagen_base64=base64.b64encode(png).decode(), ip=ip, fecha=timezone.now(),
    )
    firma.huella = calcular_huella(firma)
    firma.save()
    return firma


def _limpiar_responsable(nombre, rut):
    nombre = (nombre or "").strip()
    if not nombre:
        raise DatosInvalidos("Escribe el nombre del responsable de obra.")
    try:
        validar_rut(rut)
    except ValidationError as error:
        raise DatosInvalidos(error.messages[0])
    return nombre, normalizar_rut(rut)


# ---------------------------------------------------------------- Entrega y devolución


def registrar_entrega(*, contratista, **datos):
    # La morosidad se revisa en el momento, sin esperar la revisión programada. Va en su
    # propia transacción para que el bloqueo quede guardado aunque se rechace la entrega.
    with transaction.atomic():
        actualizar_bloqueo(Contratista.objects.select_for_update().get(pk=contratista.pk))
    return _crear_entrega(contratista=contratista, **datos)


@transaction.atomic
def _crear_entrega(*, herramienta, contratista, obra, responsable_nombre, responsable_rut, fecha_limite,
                   firma, usuario, condicion=Prestamo.Condicion.BUENA, observaciones="", ip=None):
    herramienta = Herramienta.objects.select_for_update().get(pk=herramienta.pk)
    contratista = Contratista.objects.select_for_update().get(pk=contratista.pk)
    nombre, rut = _limpiar_responsable(responsable_nombre, responsable_rut)

    if contratista.bloqueado:
        raise ReglaNegocio(f"{contratista.razon_social} está bloqueado: {contratista.motivo_bloqueo}")
    if not contratista.activo:
        raise ReglaNegocio(f"{contratista.razon_social} está inactivo.")
    if not obra.activa:
        raise ReglaNegocio(f"La obra {obra.nombre} está inactiva.")
    if herramienta.estado != Estado.DISPONIBLE:
        raise ReglaNegocio(f"{herramienta.codigo} no está disponible: su estado es «{herramienta.get_estado_display()}».")
    vencidos = herramienta.planes_vencidos()
    if vencidos:
        raise ReglaNegocio(f"{herramienta.codigo} tiene una mantención vencida ({vencidos[0].nombre}). Realízala antes de entregarla.")
    if fecha_limite < timezone.localdate():
        raise DatosInvalidos("La fecha límite no puede ser anterior a hoy.")

    prestamo = Prestamo.objects.create(
        herramienta=herramienta, contratista=contratista, obra=obra,
        responsable_nombre=nombre, responsable_rut=rut,
        fecha_limite=fecha_limite, tarifa_pactada=herramienta.tarifa_diaria,
        condicion_entrega=condicion, observaciones_entrega=observaciones, entregado_por=usuario,
    )
    _guardar_firma(prestamo, Firma.Tipo.ENTREGA, nombre, rut, firma, ip)
    _registrar_estado(herramienta, Estado.EN_USO, usuario, f"Entrega {prestamo.numero}")
    return prestamo


@transaction.atomic
def registrar_devolucion(*, prestamo, condicion, horas_uso, firma, responsable_nombre, responsable_rut,
                         usuario, cargo_danos=None, observaciones="", ip=None):
    prestamo = Prestamo.objects.select_for_update().get(pk=prestamo.pk)
    if not prestamo.activo:
        raise ReglaNegocio(f"El préstamo {prestamo.numero} ya fue cerrado.")
    herramienta = Herramienta.objects.select_for_update().get(pk=prestamo.herramienta_id)
    nombre, rut = _limpiar_responsable(responsable_nombre, responsable_rut)
    horas_uso = Decimal(str(horas_uso or 0))
    if horas_uso < 0:
        raise DatosInvalidos("Las horas de uso no pueden ser negativas.")
    if cargo_danos is not None and cargo_danos < 0:
        raise DatosInvalidos("El cargo no puede ser negativo.")
    extraviada = condicion == Prestamo.Condicion.PERDIDA
    if condicion in {Prestamo.Condicion.DANADA, Prestamo.Condicion.PERDIDA} and not (observaciones or "").strip():
        raise DatosInvalidos("Describe el daño o las circunstancias del extravío en las observaciones.")
    if cargo_danos is None:
        cargo_danos = herramienta.valor_reposicion if extraviada else 0

    ahora = timezone.now()
    cobro = prestamo.calcular_cobro(timezone.localdate(ahora), cargo_danos)
    for campo, valor in cobro.items():
        setattr(prestamo, campo, valor)
    prestamo.fecha_devolucion = ahora
    prestamo.condicion_devolucion = condicion
    prestamo.observaciones_devolucion = observaciones
    prestamo.horas_uso = horas_uso
    prestamo.recibido_por = usuario
    prestamo.save()
    _guardar_firma(prestamo, Firma.Tipo.DEVOLUCION, nombre, rut, firma, ip)

    herramienta.horas_uso += horas_uso
    herramienta.save(update_fields=["horas_uso", "actualizada"])

    if extraviada:
        _registrar_estado(herramienta, Estado.BAJA, usuario, f"Extravío declarado en {prestamo.numero}")
        herramienta.planes.update(activo=False)
        herramienta.ordenes.filter(estado=OrdenMantenimiento.Estado.PROGRAMADA).update(
            estado=OrdenMantenimiento.Estado.CANCELADA
        )
        _resolver_alertas(Q(herramienta=herramienta))
    elif condicion == Prestamo.Condicion.DANADA:
        _registrar_estado(herramienta, Estado.MANTENIMIENTO, usuario, f"Devuelta con daño en {prestamo.numero}")
        OrdenMantenimiento.objects.create(
            herramienta=herramienta, prestamo_origen=prestamo, tipo=OrdenMantenimiento.Tipo.CORRECTIVA,
            descripcion=f"Reparar daño informado en {prestamo.numero}: {observaciones}"[:250],
            estado=OrdenMantenimiento.Estado.EN_CURSO, fecha_inicio=ahora,
        )
    else:
        _registrar_estado(herramienta, Estado.DISPONIBLE, usuario, f"Devolución {prestamo.numero}")

    _resolver_alertas(Q(prestamo=prestamo))
    contratista = Contratista.objects.select_for_update().get(pk=prestamo.contratista_id)
    actualizar_bloqueo(contratista)
    return prestamo


# ---------------------------------------------------------------- Bloqueo de contratistas


def actualizar_bloqueo(contratista):
    """Bloquea si hay devoluciones morosas; levanta solo los bloqueos automáticos."""
    morosos = contratista.prestamos.morosos().select_related("herramienta")
    cantidad = morosos.count()
    if cantidad and not contratista.bloqueado:
        contratista.bloqueado = True
        contratista.bloqueo_automatico = True
        contratista.motivo_bloqueo = _devoluciones_vencidas(cantidad)
        contratista.fecha_bloqueo = timezone.now()
        contratista.save(update_fields=["bloqueado", "bloqueo_automatico", "motivo_bloqueo", "fecha_bloqueo"])
        _abrir_alerta(
            f"bloqueo-{contratista.pk}", Alerta.Tipo.BLOQUEO, Alerta.Nivel.CRITICO,
            f"{contratista.razon_social} quedó bloqueado por {_devoluciones_vencidas(cantidad)}.",
            contratista=contratista,
        )
    elif cantidad and contratista.bloqueo_automatico:
        motivo = _devoluciones_vencidas(cantidad)
        if contratista.motivo_bloqueo != motivo:
            contratista.motivo_bloqueo = motivo
            contratista.save(update_fields=["motivo_bloqueo"])
    elif not cantidad and contratista.bloqueado and contratista.bloqueo_automatico:
        _quitar_bloqueo(contratista)


def _quitar_bloqueo(contratista):
    contratista.bloqueado = False
    contratista.bloqueo_automatico = False
    contratista.motivo_bloqueo = ""
    contratista.fecha_bloqueo = None
    contratista.save(update_fields=["bloqueado", "bloqueo_automatico", "motivo_bloqueo", "fecha_bloqueo"])
    _resolver_alertas(Q(clave=f"bloqueo-{contratista.pk}"))


@transaction.atomic
def bloquear_contratista(contratista, motivo):
    contratista = Contratista.objects.select_for_update().get(pk=contratista.pk)
    motivo = (motivo or "").strip()
    if not motivo:
        raise DatosInvalidos("Escribe el motivo del bloqueo.")
    if contratista.bloqueado:
        raise ReglaNegocio(f"{contratista.razon_social} ya está bloqueado.")
    contratista.bloqueado = True
    contratista.bloqueo_automatico = False
    contratista.motivo_bloqueo = motivo
    contratista.fecha_bloqueo = timezone.now()
    contratista.save(update_fields=["bloqueado", "bloqueo_automatico", "motivo_bloqueo", "fecha_bloqueo"])
    _abrir_alerta(
        f"bloqueo-{contratista.pk}", Alerta.Tipo.BLOQUEO, Alerta.Nivel.AVISO,
        f"{contratista.razon_social} fue bloqueado manualmente: {motivo}"[:300], contratista=contratista,
    )
    return contratista


@transaction.atomic
def desbloquear_contratista(contratista):
    contratista = Contratista.objects.select_for_update().get(pk=contratista.pk)
    if not contratista.bloqueado:
        raise ReglaNegocio(f"{contratista.razon_social} no está bloqueado.")
    cantidad = contratista.prestamos.morosos().count()
    if cantidad:
        raise ReglaNegocio(f"No se puede desbloquear: tiene {_devoluciones_vencidas(cantidad)}. Registra primero la devolución.")
    _quitar_bloqueo(contratista)
    return contratista


# ---------------------------------------------------------------- Mantenimiento


@transaction.atomic
def iniciar_orden(orden, usuario):
    orden = OrdenMantenimiento.objects.select_for_update().get(pk=orden.pk)
    herramienta = Herramienta.objects.select_for_update().get(pk=orden.herramienta_id)
    if orden.estado != OrdenMantenimiento.Estado.PROGRAMADA:
        raise ReglaNegocio(f"La orden {orden.numero} no está programada.")
    if herramienta.estado == Estado.EN_USO:
        raise ReglaNegocio(f"{herramienta.codigo} está en uso. Registra su devolución antes de iniciar la orden.")
    if herramienta.estado == Estado.BAJA:
        raise ReglaNegocio(f"{herramienta.codigo} está dada de baja.")
    orden.estado = OrdenMantenimiento.Estado.EN_CURSO
    orden.fecha_inicio = timezone.now()
    orden.tecnico = orden.tecnico or usuario
    orden.save()
    if herramienta.estado != Estado.MANTENIMIENTO:
        _registrar_estado(herramienta, Estado.MANTENIMIENTO, usuario, f"Inicio de {orden.numero}")
    return orden


@transaction.atomic
def completar_orden(orden, usuario, trabajo_realizado, costo=0):
    orden = OrdenMantenimiento.objects.select_for_update().get(pk=orden.pk)
    herramienta = Herramienta.objects.select_for_update().get(pk=orden.herramienta_id)
    if orden.estado != OrdenMantenimiento.Estado.EN_CURSO:
        raise ReglaNegocio(f"La orden {orden.numero} debe estar en curso para completarla.")
    trabajo_realizado = (trabajo_realizado or "").strip()
    if not trabajo_realizado:
        raise DatosInvalidos("Describe el trabajo realizado.")
    if costo is None or costo < 0:
        raise DatosInvalidos("El costo no puede ser negativo.")
    orden.estado = OrdenMantenimiento.Estado.COMPLETADA
    orden.fecha_termino = timezone.now()
    orden.trabajo_realizado = trabajo_realizado
    orden.costo = costo
    orden.save()
    if orden.plan_id:
        plan = orden.plan
        plan.ultima_fecha = timezone.localdate()
        plan.ultimas_horas = herramienta.horas_uso
        plan.save(update_fields=["ultima_fecha", "ultimas_horas"])
        _resolver_alertas(Q(plan=plan))
    otras_en_curso = herramienta.ordenes.filter(estado=OrdenMantenimiento.Estado.EN_CURSO).exists()
    if herramienta.estado == Estado.MANTENIMIENTO and not otras_en_curso:
        _registrar_estado(herramienta, Estado.DISPONIBLE, usuario, f"Término de {orden.numero}")
    return orden


@transaction.atomic
def cancelar_orden(orden, usuario):
    orden = OrdenMantenimiento.objects.select_for_update().get(pk=orden.pk)
    herramienta = Herramienta.objects.select_for_update().get(pk=orden.herramienta_id)
    if not orden.abierta:
        raise ReglaNegocio(f"La orden {orden.numero} ya está cerrada.")
    estaba_en_curso = orden.estado == OrdenMantenimiento.Estado.EN_CURSO
    orden.estado = OrdenMantenimiento.Estado.CANCELADA
    orden.fecha_termino = timezone.now()
    orden.save()
    otras_en_curso = herramienta.ordenes.filter(estado=OrdenMantenimiento.Estado.EN_CURSO).exists()
    if estaba_en_curso and herramienta.estado == Estado.MANTENIMIENTO and not otras_en_curso:
        _registrar_estado(herramienta, Estado.DISPONIBLE, usuario, f"Cancelación de {orden.numero}")
    return orden


# ---------------------------------------------------------------- Alertas


def _abrir_alerta(clave, tipo, nivel, mensaje, **relaciones):
    alerta, creada = Alerta.objects.get_or_create(
        clave=clave, resuelta_en__isnull=True,
        defaults={"tipo": tipo, "nivel": nivel, "mensaje": mensaje, **relaciones},
    )
    if not creada and (alerta.mensaje != mensaje or alerta.nivel != nivel):
        alerta.mensaje = mensaje
        alerta.nivel = nivel
        alerta.save(update_fields=["mensaje", "nivel"])
    return alerta, creada


def _resolver_alertas(filtro):
    return Alerta.objects.filter(filtro, resuelta_en__isnull=True).update(resuelta_en=timezone.now())


def atender_alerta(alerta, usuario):
    if alerta.atendida_en is None:
        alerta.atendida_en = timezone.now()
        alerta.atendida_por = usuario
        alerta.save(update_fields=["atendida_en", "atendida_por"])
    return alerta


@transaction.atomic
def procesar_alertas():
    """Revisión periódica: mora, bloqueos y mantenciones. Se puede repetir sin duplicar."""
    hoy = timezone.localdate()
    resumen = {"alertas_nuevas": 0, "contratistas_bloqueados": 0, "contratistas_desbloqueados": 0, "ordenes_creadas": 0}
    claves_vigentes = set()

    activos = Prestamo.objects.activos().select_related("herramienta", "contratista")
    for prestamo in activos:
        dias = (hoy - prestamo.fecha_limite).days
        if dias > 0:
            clave = f"mora-{prestamo.pk}"
            _, creada = _abrir_alerta(
                clave, Alerta.Tipo.MOROSIDAD, Alerta.Nivel.CRITICO,
                f"{prestamo.contratista.razon_social} lleva {dias} día{'' if dias == 1 else 's'} de atraso con {prestamo.herramienta.codigo} ({prestamo.numero}).",
                prestamo=prestamo, contratista=prestamo.contratista, herramienta=prestamo.herramienta,
            )
        elif dias >= -1:
            clave = f"vence-{prestamo.pk}"
            cuando = "hoy" if dias == 0 else "mañana"
            _, creada = _abrir_alerta(
                clave, Alerta.Tipo.VENCE_PRONTO, Alerta.Nivel.AVISO,
                f"{prestamo.herramienta.codigo} debe volver {cuando} ({prestamo.contratista.razon_social}, {prestamo.numero}).",
                prestamo=prestamo, contratista=prestamo.contratista, herramienta=prestamo.herramienta,
            )
        else:
            continue
        claves_vigentes.add(clave)
        resumen["alertas_nuevas"] += int(creada)

    # Revisa también a quien ya está bloqueado, para levantar bloqueos que dejaron de aplicar.
    afectados = Contratista.objects.select_for_update().filter(
        Q(pk__in=Prestamo.objects.morosos().values("contratista")) | Q(bloqueado=True, bloqueo_automatico=True)
    )
    for contratista in afectados:
        antes = contratista.bloqueado
        actualizar_bloqueo(contratista)
        if contratista.bloqueado and not antes:
            resumen["contratistas_bloqueados"] += 1
            resumen["alertas_nuevas"] += 1
        elif antes and not contratista.bloqueado:
            resumen["contratistas_desbloqueados"] += 1

    planes = PlanMantenimiento.objects.filter(activo=True).exclude(herramienta__estado=Estado.BAJA).select_related("herramienta")
    for plan in planes:
        situacion = plan.situacion
        if situacion == PlanMantenimiento.AL_DIA:
            continue
        clave = f"plan-{plan.pk}"
        claves_vigentes.add(clave)
        vencido = situacion == PlanMantenimiento.VENCIDO
        texto = "vencida" if vencido else "próxima"
        _, creada = _abrir_alerta(
            clave, Alerta.Tipo.MANTENCION, Alerta.Nivel.CRITICO if vencido else Alerta.Nivel.AVISO,
            f"{plan.herramienta.codigo} tiene la mantención «{plan.nombre}» {texto}.",
            plan=plan, herramienta=plan.herramienta,
        )
        resumen["alertas_nuevas"] += int(creada)
        tiene_orden = plan.ordenes.filter(
            estado__in=[OrdenMantenimiento.Estado.PROGRAMADA, OrdenMantenimiento.Estado.EN_CURSO]
        ).exists()
        if not tiene_orden:
            OrdenMantenimiento.objects.create(
                herramienta=plan.herramienta, plan=plan, tipo=OrdenMantenimiento.Tipo.PREVENTIVA,
                descripcion=plan.nombre, fecha_programada=plan.proxima_fecha if plan.proxima_fecha and plan.proxima_fecha > hoy else hoy,
            )
            resumen["ordenes_creadas"] += 1

    # Cierra las alertas cuya condición ya no existe (por ejemplo, un plan reprogramado).
    (
        Alerta.objects.filter(
            resuelta_en__isnull=True,
            tipo__in=[Alerta.Tipo.MOROSIDAD, Alerta.Tipo.VENCE_PRONTO, Alerta.Tipo.MANTENCION],
        )
        .exclude(clave__in=claves_vigentes)
        .update(resuelta_en=timezone.now())
    )
    return resumen
