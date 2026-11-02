"""Pruebas de las reglas del caso BuildCorp, ejecutadas sobre PostgreSQL."""
import base64
import io
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image, ImageDraw
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from herramientas import roles, services
from herramientas.models import (
    Alerta, Categoria, Contratista, Firma, Herramienta, MovimientoEstado, Obra,
    OrdenMantenimiento, PlanMantenimiento, Prestamo,
)
from herramientas.validators import digito_verificador, normalizar_rut, validar_rut

RUT_RESPONSABLE = "12345678-5"


def firma_valida():
    imagen = Image.new("RGBA", (400, 120), (0, 0, 0, 0))
    ImageDraw.Draw(imagen).line([(20, 60), (140, 20), (260, 100), (380, 50)], fill=(0, 0, 0, 255), width=4)
    salida = io.BytesIO()
    imagen.save(salida, format="PNG")
    return "data:image/png;base64," + base64.b64encode(salida.getvalue()).decode()


def firma_en_blanco():
    salida = io.BytesIO()
    Image.new("RGBA", (400, 120), (0, 0, 0, 0)).save(salida, format="PNG")
    return "data:image/png;base64," + base64.b64encode(salida.getvalue()).decode()


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        roles.sincronizar_roles()
        User = get_user_model()
        cls.usuarios = {}
        for nombre, rol in (
            ("admin", roles.ADMINISTRADOR), ("bodega", roles.BODEGUERO),
            ("tecnico", roles.TECNICO), ("supervisor", roles.SUPERVISOR),
        ):
            usuario = User.objects.create_user(nombre, password="clave-de-prueba-1", is_staff=nombre == "admin")
            usuario.groups.add(Group.objects.get(name=rol))
            cls.usuarios[nombre] = usuario
        cls.bodega = cls.usuarios["bodega"]
        cls.categoria = Categoria.objects.create(nombre="Perforación")
        cls.obra = Obra.objects.create(nombre="Obra Norte", direccion="Calle 1")
        cls.contratista = Contratista.objects.create(razon_social="Montajes Sur", rut="76123450-" + digito_verificador(76123450))
        cls.otro = Contratista.objects.create(razon_social="Obras Andes", rut="77123450-" + digito_verificador(77123450))
        cls.herramienta = cls.crear_herramienta("TAL-1")

    @classmethod
    def crear_herramienta(cls, codigo, tarifa=10000, valor=500000):
        herramienta = Herramienta.objects.create(
            codigo=codigo, nombre="Taladro", categoria=cls.categoria, tarifa_diaria=tarifa, valor_reposicion=valor
        )
        services.registrar_alta(herramienta, None)
        return herramienta

    def entregar(self, herramienta=None, contratista=None, dias=7, **extra):
        datos = dict(
            herramienta=herramienta or self.herramienta, contratista=contratista or self.contratista, obra=self.obra,
            responsable_nombre="Juana Pérez", responsable_rut=RUT_RESPONSABLE,
            fecha_limite=timezone.localdate() + timedelta(days=dias), firma=firma_valida(), usuario=self.bodega,
        )
        datos.update(extra)
        return services.registrar_entrega(**datos)

    def devolver(self, prestamo, condicion="BUENA", horas=Decimal("5"), **extra):
        datos = dict(
            prestamo=prestamo, condicion=condicion, horas_uso=horas, firma=firma_valida(),
            responsable_nombre="Juana Pérez", responsable_rut=RUT_RESPONSABLE, usuario=self.bodega,
        )
        datos.update(extra)
        return services.registrar_devolucion(**datos)

    def atrasar(self, prestamo, dias_entrega=10, dias_atraso=3):
        Prestamo.objects.filter(pk=prestamo.pk).update(
            fecha_entrega=timezone.now() - timedelta(days=dias_entrega),
            fecha_limite=timezone.localdate() - timedelta(days=dias_atraso),
        )
        prestamo.refresh_from_db()
        return prestamo


class ConexionTests(TestCase):
    def test_la_base_de_datos_es_postgresql(self):
        self.assertEqual(connection.vendor, "postgresql")


class RutTests(TestCase):
    def test_valida_y_normaliza(self):
        validar_rut("12.345.678-5")
        self.assertEqual(normalizar_rut("12.345.678-5"), "12345678-5")
        self.assertEqual(digito_verificador(11111111), "1")

    def test_rechaza_digito_incorrecto(self):
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            validar_rut("12345678-9")


class TrazabilidadTests(Base):
    def test_cada_cambio_queda_registrado(self):
        services.cambiar_estado(self.herramienta, "MANTENIMIENTO", self.bodega, "Ruido anormal")
        services.cambiar_estado(self.herramienta, "DISPONIBLE", self.bodega, "Revisada")
        estados = list(self.herramienta.movimientos.order_by("id").values_list("estado_nuevo", flat=True))
        self.assertEqual(estados, ["DISPONIBLE", "MANTENIMIENTO", "DISPONIBLE"])

    def test_transiciones_prohibidas(self):
        services.cambiar_estado(self.herramienta, "BAJA", self.bodega, "Rota")
        with self.assertRaises(services.ReglaNegocio):
            services.cambiar_estado(self.herramienta, "DISPONIBLE", self.bodega, "Volver")

    def test_en_uso_solo_se_alcanza_con_una_entrega(self):
        with self.assertRaises(services.ReglaNegocio):
            services.cambiar_estado(self.herramienta, "EN_USO", self.bodega, "A mano")

    def test_exige_motivo(self):
        with self.assertRaises(services.DatosInvalidos):
            services.cambiar_estado(self.herramienta, "BAJA", self.bodega, "  ")


class EntregaYFirmaTests(Base):
    def test_entrega_cambia_estado_y_guarda_firma_integra(self):
        prestamo = self.entregar()
        self.herramienta.refresh_from_db()
        self.assertEqual(self.herramienta.estado, "EN_USO")
        firma = prestamo.firmas.get()
        self.assertEqual(firma.tipo, Firma.Tipo.ENTREGA)
        self.assertEqual(len(firma.huella), 64)
        self.assertTrue(Firma.objects.get(pk=firma.pk).es_integra)

    def test_alterar_una_firma_se_detecta(self):
        firma = self.entregar().firmas.get()
        Firma.objects.filter(pk=firma.pk).update(nombre="Otra persona")
        self.assertFalse(Firma.objects.get(pk=firma.pk).es_integra)

    def test_rechaza_firma_en_blanco_ausente_o_falsa(self):
        for mala in (firma_en_blanco(), "", "data:image/png;base64,no-es-base64!", "data:image/png;base64,QUJD"):
            with self.subTest(firma=mala[:30]), self.assertRaises(services.DatosInvalidos):
                self.entregar(firma=mala)
        self.herramienta.refresh_from_db()
        self.assertEqual(self.herramienta.estado, "DISPONIBLE")
        self.assertFalse(Prestamo.objects.exists())

    def test_no_entrega_una_herramienta_en_uso(self):
        self.entregar()
        with self.assertRaises(services.ReglaNegocio):
            self.entregar(contratista=self.otro)

    def test_la_base_impide_dos_prestamos_abiertos(self):
        self.entregar()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Prestamo.objects.create(
                herramienta=self.herramienta, contratista=self.otro, obra=self.obra,
                responsable_nombre="X", responsable_rut=RUT_RESPONSABLE,
                fecha_limite=timezone.localdate(), tarifa_pactada=1,
            )

    def test_rechaza_fecha_limite_pasada(self):
        with self.assertRaises(services.DatosInvalidos):
            self.entregar(dias=-1)

    def test_rechaza_rut_invalido(self):
        with self.assertRaises(services.DatosInvalidos):
            self.entregar(responsable_rut="12345678-9")


class CobroYDevolucionTests(Base):
    def test_devolucion_en_plazo_cobra_solo_arriendo(self):
        prestamo = self.atrasar(self.entregar(), dias_entrega=4, dias_atraso=-3)
        cerrado = self.devolver(prestamo)
        self.assertEqual((cerrado.dias_cobrados, cerrado.dias_mora), (4, 0))
        self.assertEqual(cerrado.monto_arriendo, 40000)
        self.assertEqual(cerrado.monto_total, 40000)
        self.herramienta.refresh_from_db()
        self.assertEqual(self.herramienta.estado, "DISPONIBLE")
        self.assertEqual(self.herramienta.horas_uso, Decimal("5"))

    def test_mismo_dia_cobra_un_dia(self):
        self.assertEqual(self.devolver(self.entregar()).monto_total, 10000)

    @override_settings(RECARGO_MORA_PORCENTAJE=50)
    def test_atraso_agrega_recargo(self):
        cerrado = self.devolver(self.atrasar(self.entregar(), dias_entrega=10, dias_atraso=3))
        self.assertEqual(cerrado.dias_mora, 3)
        self.assertEqual(cerrado.monto_arriendo, 100000)
        self.assertEqual(cerrado.monto_recargo, 15000)
        self.assertEqual(cerrado.monto_total, 115000)

    def test_tarifa_pactada_no_cambia_si_cambia_el_catalogo(self):
        prestamo = self.entregar()
        Herramienta.objects.filter(pk=self.herramienta.pk).update(tarifa_diaria=99999)
        self.assertEqual(self.devolver(prestamo).monto_arriendo, 10000)

    def test_dano_abre_orden_correctiva(self):
        cerrado = self.devolver(self.entregar(), condicion="DANADA", cargo_danos=30000, observaciones="Carcasa rota")
        self.assertEqual(cerrado.monto_total, 40000)
        self.herramienta.refresh_from_db()
        self.assertEqual(self.herramienta.estado, "MANTENIMIENTO")
        orden = self.herramienta.ordenes.get()
        self.assertEqual((orden.tipo, orden.estado), ("CORRECTIVA", "EN_CURSO"))

    def test_dano_exige_observaciones(self):
        with self.assertRaises(services.DatosInvalidos):
            self.devolver(self.entregar(), condicion="DANADA")

    def test_extravio_da_de_baja_y_cobra_reposicion(self):
        cerrado = self.devolver(self.entregar(), condicion="PERDIDA", observaciones="Robada en obra")
        self.assertEqual(cerrado.cargo_danos, 500000)
        self.herramienta.refresh_from_db()
        self.assertEqual(self.herramienta.estado, "BAJA")

    def test_no_se_devuelve_dos_veces(self):
        prestamo = self.entregar()
        self.devolver(prestamo)
        with self.assertRaises(services.ReglaNegocio):
            self.devolver(prestamo)
        self.herramienta.refresh_from_db()
        self.assertEqual(self.herramienta.horas_uso, Decimal("5"))

    def test_rechazo_de_firma_no_deja_cambios_parciales(self):
        prestamo = self.entregar()
        with self.assertRaises(services.DatosInvalidos):
            self.devolver(prestamo, firma=firma_en_blanco())
        prestamo.refresh_from_db()
        self.herramienta.refresh_from_db()
        self.assertTrue(prestamo.activo)
        self.assertEqual(self.herramienta.horas_uso, 0)
        self.assertEqual(self.herramienta.estado, "EN_USO")


class MorosidadTests(Base):
    def test_revision_bloquea_al_moroso_y_crea_alertas(self):
        self.atrasar(self.entregar())
        resumen = services.procesar_alertas()
        self.contratista.refresh_from_db()
        self.assertTrue(self.contratista.bloqueado)
        self.assertTrue(self.contratista.bloqueo_automatico)
        self.assertEqual(resumen["contratistas_bloqueados"], 1)
        tipos = set(Alerta.objects.filter(resuelta_en__isnull=True).values_list("tipo", flat=True))
        self.assertEqual(tipos, {"MOROSIDAD", "BLOQUEO"})

    def test_revision_repetida_no_duplica(self):
        self.atrasar(self.entregar())
        services.procesar_alertas()
        total = Alerta.objects.count()
        resumen = services.procesar_alertas()
        self.assertEqual(Alerta.objects.count(), total)
        self.assertEqual(resumen["alertas_nuevas"], 0)

    def test_moroso_no_recibe_herramientas_aunque_no_corra_la_revision(self):
        self.atrasar(self.entregar())
        otra = self.crear_herramienta("TAL-2")
        with self.assertRaises(services.ReglaNegocio) as contexto:
            self.entregar(herramienta=otra)
        self.assertIn("bloqueado", contexto.exception.mensaje)
        # El bloqueo queda guardado aunque la entrega se haya rechazado.
        self.contratista.refresh_from_db()
        self.assertTrue(self.contratista.bloqueado)
        otra.refresh_from_db()
        self.assertEqual(otra.estado, "DISPONIBLE")

    def test_devolver_todo_desbloquea_y_resuelve_alertas(self):
        prestamo = self.atrasar(self.entregar())
        services.procesar_alertas()
        self.devolver(prestamo)
        self.contratista.refresh_from_db()
        self.assertFalse(self.contratista.bloqueado)
        self.assertFalse(Alerta.objects.filter(resuelta_en__isnull=True).exists())

    def test_sigue_bloqueado_si_le_quedan_vencidas(self):
        p1 = self.entregar()
        p2 = self.entregar(herramienta=self.crear_herramienta("TAL-2"))
        self.atrasar(p1)
        self.atrasar(p2)
        services.procesar_alertas()
        self.devolver(p1)
        self.contratista.refresh_from_db()
        self.assertTrue(self.contratista.bloqueado)

    def test_bloqueo_manual_no_se_levanta_solo(self):
        services.bloquear_contratista(self.contratista, "Deuda administrativa")
        services.procesar_alertas()
        self.contratista.refresh_from_db()
        self.assertTrue(self.contratista.bloqueado)
        services.desbloquear_contratista(self.contratista)
        self.contratista.refresh_from_db()
        self.assertFalse(self.contratista.bloqueado)

    def test_no_se_desbloquea_a_mano_con_mora(self):
        self.atrasar(self.entregar())
        services.procesar_alertas()
        with self.assertRaises(services.ReglaNegocio):
            services.desbloquear_contratista(self.contratista)

    @override_settings(MORA_DIAS_GRACIA=5)
    def test_dias_de_gracia(self):
        self.atrasar(self.entregar(), dias_atraso=3)
        services.procesar_alertas()
        self.contratista.refresh_from_db()
        self.assertFalse(self.contratista.bloqueado)

    def test_aviso_antes_del_vencimiento(self):
        self.entregar(dias=1)
        services.procesar_alertas()
        self.assertTrue(Alerta.objects.filter(tipo="VENCE_PRONTO", resuelta_en__isnull=True).exists())


class MantenimientoTests(Base):
    def plan(self, **campos):
        datos = dict(herramienta=self.herramienta, nombre="Engrase", ultima_fecha=timezone.localdate())
        datos.update(campos)
        return PlanMantenimiento.objects.create(**datos)

    def test_vence_por_fecha(self):
        plan = self.plan(intervalo_dias=30, ultima_fecha=timezone.localdate() - timedelta(days=30))
        self.assertEqual(plan.situacion, "VENCIDO")

    def test_aviso_previo_por_fecha(self):
        plan = self.plan(intervalo_dias=30, ultima_fecha=timezone.localdate() - timedelta(days=25))
        self.assertEqual(plan.situacion, "PROXIMO")

    def test_vence_por_uso_acumulado_en_prestamos(self):
        plan = self.plan(intervalo_horas=Decimal("10"))
        self.assertEqual(plan.situacion, "AL_DIA")
        self.devolver(self.entregar(), horas=Decimal("9.5"))
        self.assertEqual(PlanMantenimiento.objects.get(pk=plan.pk).situacion, "PROXIMO")
        self.devolver(self.entregar(), horas=Decimal("1"))
        self.assertEqual(PlanMantenimiento.objects.get(pk=plan.pk).situacion, "VENCIDO")

    def test_la_base_exige_algun_intervalo(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.plan()

    def test_plan_vencido_impide_entregar(self):
        self.plan(intervalo_dias=1, ultima_fecha=timezone.localdate() - timedelta(days=5))
        with self.assertRaises(services.ReglaNegocio):
            self.entregar()

    def test_revision_programa_una_sola_orden(self):
        self.plan(intervalo_dias=1, ultima_fecha=timezone.localdate() - timedelta(days=5))
        services.procesar_alertas()
        services.procesar_alertas()
        self.assertEqual(self.herramienta.ordenes.count(), 1)
        self.assertTrue(Alerta.objects.filter(tipo="MANTENCION", nivel="CRITICO").exists())

    def test_ciclo_completo_de_orden_reinicia_el_plan(self):
        plan = self.plan(intervalo_dias=1, ultima_fecha=timezone.localdate() - timedelta(days=5))
        services.procesar_alertas()
        orden = self.herramienta.ordenes.get()
        services.iniciar_orden(orden, self.usuarios["tecnico"])
        self.herramienta.refresh_from_db()
        self.assertEqual(self.herramienta.estado, "MANTENIMIENTO")
        services.completar_orden(orden, self.usuarios["tecnico"], "Engrasada", 15000)
        self.herramienta.refresh_from_db()
        plan.refresh_from_db()
        self.assertEqual(self.herramienta.estado, "DISPONIBLE")
        self.assertEqual(plan.ultima_fecha, timezone.localdate())
        self.assertEqual(plan.situacion, "AL_DIA")
        self.assertFalse(Alerta.objects.filter(plan=plan, resuelta_en__isnull=True).exists())
        self.entregar()

    def test_no_inicia_orden_si_la_herramienta_esta_en_uso(self):
        self.entregar()
        orden = OrdenMantenimiento.objects.create(herramienta=self.herramienta, descripcion="X")
        with self.assertRaises(services.ReglaNegocio):
            services.iniciar_orden(orden, self.usuarios["tecnico"])

    def test_orden_en_curso_impide_liberar_a_mano(self):
        orden = OrdenMantenimiento.objects.create(herramienta=self.herramienta, descripcion="X")
        services.iniciar_orden(orden, self.usuarios["tecnico"])
        with self.assertRaises(services.ReglaNegocio):
            services.cambiar_estado(self.herramienta, "DISPONIBLE", self.bodega, "Lista")

    def test_cancelar_orden_en_curso_libera_la_herramienta(self):
        orden = OrdenMantenimiento.objects.create(herramienta=self.herramienta, descripcion="X")
        services.iniciar_orden(orden, self.usuarios["tecnico"])
        services.cancelar_orden(orden, self.usuarios["tecnico"])
        self.herramienta.refresh_from_db()
        self.assertEqual(self.herramienta.estado, "DISPONIBLE")

    def test_baja_desactiva_planes_y_cancela_ordenes(self):
        plan = self.plan(intervalo_dias=30)
        orden = OrdenMantenimiento.objects.create(herramienta=self.herramienta, plan=plan, descripcion="X")
        services.cambiar_estado(self.herramienta, "BAJA", self.bodega, "Rota")
        plan.refresh_from_db()
        orden.refresh_from_db()
        self.assertFalse(plan.activo)
        self.assertEqual(orden.estado, "CANCELADA")


class WebTests(Base):
    def entrar(self, usuario="bodega"):
        self.client.force_login(self.usuarios[usuario])

    def test_sin_sesion_redirige_al_ingreso(self):
        for nombre in ("panel", "herramienta_lista", "prestamo_lista", "alerta_lista"):
            respuesta = self.client.get(reverse(nombre))
            self.assertEqual(respuesta.status_code, 302)
            self.assertIn("/cuenta/ingresar/", respuesta["Location"])

    def test_ingreso_real_con_usuario_y_contrasena(self):
        respuesta = self.client.post(reverse("login"), {"username": "bodega", "password": "clave-de-prueba-1"})
        self.assertRedirects(respuesta, reverse("panel"))

    def test_todas_las_pantallas_responden_para_administrador(self):
        prestamo = self.entregar()
        orden = OrdenMantenimiento.objects.create(herramienta=self.herramienta, descripcion="X")
        plan = PlanMantenimiento.objects.create(herramienta=self.herramienta, nombre="P", intervalo_dias=30)
        self.entrar("admin")
        urls = [
            reverse(n) for n in (
                "panel", "herramienta_lista", "herramienta_crear", "categoria_lista", "categoria_crear", "obra_lista",
                "obra_crear", "contratista_lista", "contratista_crear", "prestamo_lista", "entrega_nueva", "cobros",
                "plan_lista", "plan_crear", "orden_lista", "orden_crear", "alerta_lista",
            )
        ] + [
            reverse("herramienta_detalle", args=[self.herramienta.pk]),
            reverse("herramienta_editar", args=[self.herramienta.pk]),
            reverse("contratista_detalle", args=[self.contratista.pk]),
            reverse("devolucion", args=[prestamo.pk]),
            reverse("prestamo_acta", args=[prestamo.pk]),
            reverse("orden_detalle", args=[orden.pk]),
            reverse("plan_editar", args=[plan.pk]),
            reverse("prestamo_lista") + "?vista=vencidos",
            reverse("prestamo_lista") + "?vista=historial",
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_crud_de_herramienta(self):
        self.entrar("admin")
        datos = {
            "codigo": "nuevo-1", "nombre": "Sierra", "categoria": self.categoria.pk,
            "tarifa_diaria": 1000, "valor_reposicion": 2000, "horas_uso": "0",
        }
        self.client.post(reverse("herramienta_crear"), datos)
        herramienta = Herramienta.objects.get(codigo="NUEVO-1")
        self.assertTrue(herramienta.movimientos.filter(motivo="Alta en el catálogo").exists())
        datos["nombre"] = "Sierra circular"
        self.client.post(reverse("herramienta_editar", args=[herramienta.pk]), datos)
        herramienta.refresh_from_db()
        self.assertEqual(herramienta.nombre, "Sierra circular")
        self.client.post(reverse("herramienta_eliminar", args=[herramienta.pk]))
        self.assertFalse(Herramienta.objects.filter(pk=herramienta.pk).exists())

    def test_formulario_no_permite_forzar_el_estado(self):
        self.entrar("admin")
        self.client.post(reverse("herramienta_editar", args=[self.herramienta.pk]), {
            "codigo": "TAL-1", "nombre": "T", "categoria": self.categoria.pk, "tarifa_diaria": 1,
            "valor_reposicion": 1, "horas_uso": "0", "estado": "BAJA",
        })
        self.herramienta.refresh_from_db()
        self.assertEqual(self.herramienta.estado, "DISPONIBLE")

    def test_herramienta_con_historial_no_se_elimina(self):
        self.entregar()
        self.entrar("admin")
        self.client.post(reverse("herramienta_eliminar", args=[self.herramienta.pk]))
        self.assertTrue(Herramienta.objects.filter(pk=self.herramienta.pk).exists())

    def test_entrega_y_devolucion_por_formulario(self):
        self.entrar()
        respuesta = self.client.post(reverse("entrega_nueva"), {
            "herramienta": self.herramienta.pk, "contratista": self.contratista.pk, "obra": self.obra.pk,
            "responsable_nombre": "Juana", "responsable_rut": "12.345.678-5",
            "fecha_limite": (timezone.localdate() + timedelta(days=3)).isoformat(),
            "condicion": "BUENA", "firma": firma_valida(),
        })
        prestamo = Prestamo.objects.get()
        self.assertRedirects(respuesta, reverse("prestamo_acta", args=[prestamo.pk]))
        self.assertEqual(prestamo.responsable_rut, "12345678-5")
        respuesta = self.client.post(reverse("devolucion", args=[prestamo.pk]), {
            "condicion": "BUENA", "horas_uso": "2", "responsable_nombre": "Juana",
            "responsable_rut": "12.345.678-5", "firma": firma_valida(),
        })
        self.assertRedirects(respuesta, reverse("prestamo_acta", args=[prestamo.pk]))
        self.assertEqual(Firma.objects.filter(prestamo=prestamo).count(), 2)
        acta = self.client.get(reverse("prestamo_acta", args=[prestamo.pk]))
        self.assertContains(acta, "data:image/png;base64,", count=2)
        self.assertContains(acta, "(verificada)", count=2)

    def test_entrega_sin_firma_muestra_el_error(self):
        self.entrar()
        respuesta = self.client.post(reverse("entrega_nueva"), {
            "herramienta": self.herramienta.pk, "contratista": self.contratista.pk, "obra": self.obra.pk,
            "responsable_nombre": "Juana", "responsable_rut": RUT_RESPONSABLE,
            "fecha_limite": timezone.localdate().isoformat(), "condicion": "BUENA", "firma": "",
        })
        self.assertContains(respuesta, "Falta la firma")
        self.assertFalse(Prestamo.objects.exists())

    def test_permisos_por_rol_en_la_web(self):
        casos = [
            ("tecnico", "entrega_nueva", 403),
            ("tecnico", "cobros", 403),
            ("tecnico", "contratista_lista", 403),
            ("supervisor", "entrega_nueva", 403),
            ("supervisor", "herramienta_crear", 403),
            ("supervisor", "cobros", 200),
            ("bodega", "plan_crear", 403),
            ("bodega", "entrega_nueva", 200),
            ("tecnico", "plan_crear", 200),
        ]
        for usuario, ruta, esperado in casos:
            with self.subTest(usuario=usuario, ruta=ruta):
                self.client.force_login(self.usuarios[usuario])
                self.assertEqual(self.client.get(reverse(ruta)).status_code, esperado)

    def test_panel_funciona_para_todos_los_roles(self):
        self.atrasar(self.entregar())
        services.procesar_alertas()
        for usuario in self.usuarios:
            with self.subTest(usuario=usuario):
                self.client.force_login(self.usuarios[usuario])
                self.assertEqual(self.client.get(reverse("panel")).status_code, 200)

    def test_tecnico_no_ve_datos_del_contratista_en_el_panel(self):
        self.atrasar(self.entregar())
        self.entrar("tecnico")
        self.assertNotContains(self.client.get(reverse("panel")), "Montajes Sur")
        self.assertNotContains(self.client.get(reverse("herramienta_detalle", args=[self.herramienta.pk])), "Montajes Sur")

    def test_tecnico_solo_recibe_alertas_de_mantencion(self):
        self.atrasar(self.entregar())
        PlanMantenimiento.objects.create(
            herramienta=self.crear_herramienta("TAL-3"), nombre="Engrase", intervalo_dias=1,
            ultima_fecha=timezone.localdate() - timedelta(days=5),
        )
        services.procesar_alertas()
        self.entrar("tecnico")
        lista = self.client.get(reverse("alerta_lista"))
        self.assertContains(lista, "Engrase")
        self.assertNotContains(lista, "Montajes Sur")
        cliente = APIClient()
        cliente.force_authenticate(self.usuarios["tecnico"])
        tipos = {a["tipo"] for a in cliente.get("/api/v1/alertas/").data["results"]}
        self.assertEqual(tipos, {"MANTENCION"})

    def test_plan_semanal_no_nace_proximo(self):
        plan = PlanMantenimiento.objects.create(herramienta=self.herramienta, nombre="P", intervalo_dias=7)
        self.assertEqual(plan.situacion, "AL_DIA")

    def test_cambio_de_estado_exige_post(self):
        self.entrar()
        self.assertEqual(self.client.get(reverse("herramienta_cambiar_estado", args=[self.herramienta.pk])).status_code, 405)

    def test_csv_de_cobros_neutraliza_formulas(self):
        Contratista.objects.filter(pk=self.contratista.pk).update(razon_social="=HACK()")
        self.devolver(self.entregar())
        self.entrar()
        contenido = self.client.get(reverse("cobros_csv")).content.decode()
        self.assertIn("'=HACK()", contenido)
        self.assertIn("10000", contenido)

    def test_admin_personalizado_responde(self):
        prestamo = self.entregar()
        superusuario = get_user_model().objects.create_superuser("root", password="clave-de-prueba-1")
        self.client.force_login(superusuario)
        for url in (
            reverse("admin:index"),
            reverse("admin:herramientas_herramienta_changelist"),
            reverse("admin:herramientas_herramienta_change", args=[self.herramienta.pk]),
            reverse("admin:herramientas_prestamo_changelist"),
            reverse("admin:herramientas_prestamo_change", args=[prestamo.pk]),
            reverse("admin:herramientas_firma_changelist"),
            reverse("admin:herramientas_contratista_changelist"),
            reverse("admin:herramientas_planmantenimiento_changelist"),
            reverse("admin:herramientas_ordenmantenimiento_changelist"),
            reverse("admin:herramientas_alerta_changelist"),
            reverse("admin:herramientas_categoria_changelist"),
            reverse("admin:herramientas_movimientoestado_changelist"),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_accion_del_admin_respeta_las_reglas(self):
        self.entregar()
        superusuario = get_user_model().objects.create_superuser("root", password="clave-de-prueba-1")
        self.client.force_login(superusuario)
        self.client.post(reverse("admin:herramientas_herramienta_changelist"), {
            "action": "dar_de_baja", "_selected_action": [self.herramienta.pk],
        })
        self.herramienta.refresh_from_db()
        self.assertEqual(self.herramienta.estado, "EN_USO")


class ApiTests(Base):
    def cliente(self, usuario="bodega"):
        cliente = APIClient()
        cliente.force_authenticate(self.usuarios[usuario])
        return cliente

    def carga_entrega(self):
        return {
            "herramienta": self.herramienta.pk, "contratista": self.contratista.pk, "obra": self.obra.pk,
            "responsable_nombre": "Juana", "responsable_rut": RUT_RESPONSABLE,
            "fecha_limite": (timezone.localdate() + timedelta(days=3)).isoformat(), "firma": firma_valida(),
        }

    def test_sin_autenticar_responde_401(self):
        self.assertEqual(APIClient().get("/api/v1/herramientas/").status_code, 401)

    def test_token_de_acceso(self):
        respuesta = APIClient().post("/api/v1/auth/token/", {"username": "bodega", "password": "clave-de-prueba-1"})
        self.assertEqual(respuesta.status_code, 200)
        cliente = APIClient()
        cliente.credentials(HTTP_AUTHORIZATION=f"Token {respuesta.data['token']}")
        self.assertEqual(cliente.get("/api/v1/herramientas/").status_code, 200)
        self.assertEqual(Token.objects.count(), 1)

    def test_crud_de_herramienta_y_estado_de_solo_lectura(self):
        cliente = self.cliente("admin")
        creada = cliente.post("/api/v1/herramientas/", {
            "codigo": "API-1", "nombre": "Sierra", "categoria": self.categoria.pk, "estado": "BAJA",
        })
        self.assertEqual(creada.status_code, 201)
        self.assertEqual(creada.data["estado"], "DISPONIBLE")
        ruta = f"/api/v1/herramientas/{creada.data['id']}/"
        self.assertEqual(cliente.patch(ruta, {"nombre": "Sierra 2", "estado": "BAJA"}).data["estado"], "DISPONIBLE")
        self.assertEqual(cliente.get(ruta).data["nombre"], "Sierra 2")
        self.assertEqual(len(cliente.get(ruta + "trazabilidad/").data), 1)
        self.assertEqual(cliente.delete(ruta).status_code, 204)

    def test_entrega_y_devolucion(self):
        cliente = self.cliente()
        creada = cliente.post("/api/v1/prestamos/", self.carga_entrega(), format="json")
        self.assertEqual(creada.status_code, 201, creada.data)
        self.assertEqual(len(creada.data["firmas"]), 1)
        devuelta = cliente.post(f"/api/v1/prestamos/{creada.data['id']}/devolver/", {
            "condicion": "BUENA", "horas_uso": "3.5", "responsable_nombre": "Juana",
            "responsable_rut": RUT_RESPONSABLE, "firma": firma_valida(),
        }, format="json")
        self.assertEqual(devuelta.status_code, 200, devuelta.data)
        self.assertEqual(devuelta.data["cobro"]["monto_total"], 10000)
        self.assertEqual(len(devuelta.data["firmas"]), 2)

    def test_reglas_de_negocio_responden_409(self):
        Contratista.objects.filter(pk=self.contratista.pk).update(bloqueado=True, motivo_bloqueo="Prueba")
        respuesta = self.cliente().post("/api/v1/prestamos/", self.carga_entrega(), format="json")
        self.assertEqual(respuesta.status_code, 409)
        self.assertIn("bloqueado", respuesta.data["detail"])

    def test_firma_invalida_responde_400(self):
        carga = self.carga_entrega()
        carga["firma"] = firma_en_blanco()
        self.assertEqual(self.cliente().post("/api/v1/prestamos/", carga, format="json").status_code, 400)

    def test_permisos_por_rol(self):
        self.assertEqual(self.cliente("supervisor").post("/api/v1/prestamos/", self.carga_entrega(), format="json").status_code, 403)
        self.assertEqual(self.cliente("tecnico").get("/api/v1/contratistas/").status_code, 403)
        self.assertEqual(self.cliente("supervisor").get("/api/v1/contratistas/").status_code, 200)
        self.assertEqual(self.cliente("bodega").delete(f"/api/v1/herramientas/{self.herramienta.pk}/").status_code, 403)
        self.assertEqual(self.cliente("bodega").post(f"/api/v1/contratistas/{self.contratista.pk}/bloquear/", {"motivo": "x"}).status_code, 403)

    def test_prestamo_no_se_edita_ni_elimina(self):
        prestamo = self.entregar()
        cliente = self.cliente("admin")
        self.assertEqual(cliente.delete(f"/api/v1/prestamos/{prestamo.pk}/").status_code, 405)
        self.assertEqual(cliente.patch(f"/api/v1/prestamos/{prestamo.pk}/", {"fecha_limite": "2030-01-01"}).status_code, 405)

    def test_filtros_y_listado_sin_firmas(self):
        self.atrasar(self.entregar())
        cliente = self.cliente()
        vencidos = cliente.get("/api/v1/prestamos/?situacion=vencidos")
        self.assertEqual(vencidos.data["count"], 1)
        self.assertNotIn("firmas", vencidos.data["results"][0])

    def test_borrado_protegido_responde_409(self):
        self.entregar()
        respuesta = self.cliente("admin").delete(f"/api/v1/contratistas/{self.contratista.pk}/")
        self.assertEqual(respuesta.status_code, 409)

    def test_ciclo_de_orden_y_alertas(self):
        admin = self.cliente("admin")
        orden = admin.post("/api/v1/ordenes/", {
            "herramienta": self.herramienta.pk, "descripcion": "Revisión", "fecha_programada": timezone.localdate().isoformat(),
        })
        self.assertEqual(orden.status_code, 201, orden.data)
        ruta = f"/api/v1/ordenes/{orden.data['id']}/"
        self.assertEqual(admin.post(ruta + "iniciar/").data["estado"], "EN_CURSO")
        self.assertEqual(admin.post(ruta + "completar/", {"trabajo_realizado": "OK", "costo": 100}).data["estado"], "COMPLETADA")
        self.atrasar(self.entregar())
        self.assertEqual(admin.post("/api/v1/alertas/procesar/").data["contratistas_bloqueados"], 1)
        alerta = admin.get("/api/v1/alertas/?abiertas=1").data["results"][0]
        self.assertIsNotNone(admin.post(f"/api/v1/alertas/{alerta['id']}/atender/").data["atendida_en"])

    def test_plan_sin_intervalo_responde_400(self):
        respuesta = self.cliente("admin").post("/api/v1/planes/", {"herramienta": self.herramienta.pk, "nombre": "P"})
        self.assertEqual(respuesta.status_code, 400)

    def test_resumen(self):
        datos = self.cliente("tecnico").get("/api/v1/resumen/").data
        self.assertEqual(datos["herramientas"]["DISPONIBLE"], 1)
        self.assertNotIn("contratistas_bloqueados", datos)


class ComandosTests(TestCase):
    def test_cargar_demo_es_repetible_y_deja_casos_visibles(self):
        call_command("cargar_demo", password="Clave-De-Prueba-1", verbosity=0)
        total = Herramienta.objects.count()
        call_command("cargar_demo", password="Clave-De-Prueba-1", verbosity=0)
        self.assertEqual(Herramienta.objects.count(), total)
        self.assertEqual(Contratista.objects.filter(bloqueado=True).count(), 2)
        self.assertTrue(Prestamo.objects.vencidos().exists())
        self.assertEqual(
            set(Herramienta.objects.values_list("estado", flat=True)), {"DISPONIBLE", "EN_USO", "MANTENIMIENTO", "BAJA"}
        )
        self.assertTrue(all(f.es_integra for f in Firma.objects.all()))
        self.assertTrue(MovimientoEstado.objects.exists())

    def test_procesar_alertas_por_comando(self):
        call_command("procesar_alertas", verbosity=0, stdout=io.StringIO())
