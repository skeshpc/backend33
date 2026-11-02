"""Carga datos ficticios para demostrar el sistema. Se puede ejecutar más de una vez."""
import base64
import io
import math
import os
import secrets
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageDraw

from herramientas import roles, services
from herramientas.models import (
    Categoria, Contratista, Herramienta, Obra, OrdenMantenimiento, PlanMantenimiento, Prestamo,
)
from herramientas.validators import digito_verificador

USUARIOS = [
    ("admin", "Administración", "BuildCorp", None, True),
    ("ana.admin", "Ana", "Rojas", roles.ADMINISTRADOR, False),
    ("bruno.bodega", "Bruno", "Muñoz", roles.BODEGUERO, False),
    ("tania.tecnica", "Tania", "Soto", roles.TECNICO, False),
    ("sergio.supervisor", "Sergio", "Vera", roles.SUPERVISOR, False),
]

CATALOGO = [
    ("Demolición y perforación", [
        ("RTM-001", "Rotomartillo SDS Plus", "Bosch", "GBH 2-26", 9500, 280000, 620),
        ("RTM-002", "Rotomartillo SDS Max", "Makita", "HR4013C", 14500, 720000, 410),
        ("DMO-001", "Demoledor eléctrico 15 kg", "Hilti", "TE 800", 32000, 1450000, 880),
        ("TAL-001", "Taladro percutor inalámbrico", "DeWalt", "DCD996", 7000, 240000, 300),
        ("TAL-002", "Taladro magnético", "Milwaukee", "MDE42", 21000, 980000, 150),
    ]),
    ("Corte y desbaste", [
        ("ESM-001", "Esmeril angular 7 pulgadas", "Bosch", "GWS 22-180", 5500, 135000, 455),
        ("ESM-002", "Esmeril angular 4½ pulgadas", "Makita", "9557HN", 3800, 75000, 290),
        ("CRT-001", "Cortadora de pavimento", "Husqvarna", "FS 400", 45000, 2900000, 240),
        ("SIE-001", "Sierra circular 7¼ pulgadas", "DeWalt", "DWE575", 6500, 165000, 180),
        ("SIE-002", "Sierra sable inalámbrica", "Milwaukee", "M18 FSZ", 8000, 320000, 95),
    ]),
    ("Hormigón", [
        ("VIB-001", "Vibrador de inmersión", "Wacker Neuson", "IREN 45", 15000, 690000, 510),
        ("VIB-002", "Vibrador a gasolina", "Honda", "GX160", 13500, 540000, 330),
        ("BET-001", "Betonera 150 litros", "Imer", "Syntesi 150", 18000, 620000, 700),
        ("COM-001", "Placa compactadora", "Wacker Neuson", "WP1550", 28000, 1350000, 275),
        ("COM-002", "Apisonador", "Honda", "GX100", 26000, 1600000, 420),
    ]),
    ("Energía y bombeo", [
        ("GEN-001", "Generador 5,5 kVA", "Honda", "EG5500", 24000, 1150000, 960),
        ("GEN-002", "Generador 3 kVA", "Yamaha", "EF3000", 16000, 780000, 200),
        ("BMB-001", "Motobomba 2 pulgadas", "Honda", "WB20XT", 12500, 460000, 145),
        ("CMP-001", "Compresor 50 litros", "Einhell", "TE-AC 270", 11000, 390000, 365),
    ]),
    ("Medición", [
        ("NIV-001", "Nivel láser rotativo", "Leica", "Rugby 620", 19000, 1250000, 0),
        ("EST-001", "Estación total", "Topcon", "GM-52", 55000, 6500000, 0),
        ("MED-001", "Medidor láser 100 m", "Bosch", "GLM 100-25", 3500, 190000, 0),
    ]),
]

OBRAS = [
    ("Edificio Parque Oriente", "Av. Los Leones 1420", "Providencia"),
    ("Centro logístico Lampa", "Ruta 5 Norte km 22", "Lampa"),
    ("Hospital Sur, torre B", "Gran Avenida 9500", "La Cisterna"),
    ("Condominio Los Maitenes", "Camino Lonquén 3300", "Maipú"),
]

CONTRATISTAS = [
    (76123450, "Excavaciones Andina Ltda.", "Rodrigo Paredes"),
    (76234561, "Hormigones del Maipo SpA", "Carolina Fuentes"),
    (77345672, "Montajes Cordillera SpA", "Felipe Araya"),
    (77456783, "Terminaciones Pacífico Ltda.", "Javiera Lagos"),
    (78567894, "Eléctrica Los Andes SpA", "Matías Toro"),
]


def rut(cuerpo):
    return f"{cuerpo}-{digito_verificador(cuerpo)}"


def firma_simulada(semilla):
    """Dibuja un trazo que imita una firma manuscrita, solo para los datos de ejemplo."""
    imagen = Image.new("RGBA", (560, 180), (0, 0, 0, 0))
    lapiz = ImageDraw.Draw(imagen)
    puntos = []
    for i in range(240):
        t = i / 239
        x = 40 + t * 460
        y = 92 + math.sin(t * (9 + semilla) * math.pi) * (46 - 26 * t) + math.sin(t * 31 + semilla) * 13
        puntos.append((x, y))
    lapiz.line(puntos, fill=(22, 33, 31, 255), width=3, joint="curve")
    lapiz.line([(70, 136), (250, 128), (470, 142)], fill=(22, 33, 31, 255), width=2)
    salida = io.BytesIO()
    imagen.save(salida, format="PNG")
    return "data:image/png;base64," + base64.b64encode(salida.getvalue()).decode()


class Command(BaseCommand):
    help = "Crea usuarios por rol y datos ficticios para demostrar el sistema."

    def add_arguments(self, parser):
        parser.add_argument("--password", help="Contraseña común para los usuarios de ejemplo. También acepta DEMO_PASSWORD.")

    def handle(self, *args, **options):
        roles.sincronizar_roles()
        clave = options["password"] or os.getenv("DEMO_PASSWORD") or secrets.token_urlsafe(12)
        usuarios = self._usuarios(clave)
        if Herramienta.objects.exists():
            self.stdout.write("El catálogo ya tiene datos: solo se actualizaron usuarios y roles.")
        else:
            with transaction.atomic():
                self._datos(usuarios)
            self.stdout.write(self.style.SUCCESS(f"Datos de ejemplo cargados: {Herramienta.objects.count()} herramientas."))
        self.stdout.write(f"Usuarios: {', '.join(u[0] for u in USUARIOS)}")
        if not options["password"] and not os.getenv("DEMO_PASSWORD"):
            self.stdout.write(f"Contraseña generada: {clave}")

    def _usuarios(self, clave):
        creados = {}
        User = get_user_model()
        for nombre, primero, apellido, rol, es_super in USUARIOS:
            usuario, _ = User.objects.get_or_create(username=nombre)
            usuario.first_name, usuario.last_name = primero, apellido
            usuario.is_superuser = es_super
            usuario.is_staff = es_super or rol == roles.ADMINISTRADOR
            usuario.set_password(clave)
            usuario.save()
            if rol:
                usuario.groups.set([Group.objects.get(name=rol)])
            creados[nombre] = usuario
        return creados

    def _datos(self, usuarios):
        admin = usuarios["ana.admin"]
        bodega = usuarios["bruno.bodega"]
        tecnica = usuarios["tania.tecnica"]
        hoy = timezone.localdate()

        herramientas = {}
        for nombre_categoria, items in CATALOGO:
            categoria = Categoria.objects.create(nombre=nombre_categoria)
            for numero, (codigo, nombre, marca, modelo, tarifa, valor, horas) in enumerate(items, start=1):
                herramienta = Herramienta.objects.create(
                    codigo=codigo, nombre=nombre, categoria=categoria, marca=marca, modelo=modelo,
                    numero_serie=f"{codigo.replace('-', '')}{2200 + numero * 37}", tarifa_diaria=tarifa, valor_reposicion=valor,
                    horas_uso=Decimal(horas), ubicacion=f"Pasillo {categoria.pk}, gancho {numero}",
                    fecha_adquisicion=hoy - timedelta(days=200 + numero * 45),
                )
                services.registrar_alta(herramienta, admin)
                herramientas[codigo] = herramienta

        obras = [Obra.objects.create(nombre=n, direccion=d, comuna=c) for n, d, c in OBRAS]
        contratistas = [
            Contratista.objects.create(
                razon_social=nombre, rut=rut(cuerpo), contacto=contacto,
                telefono=f"+56 9 5{cuerpo % 10000000:07d}",
                email=f"contacto{indice}@ejemplo.cl",
            )
            for indice, (cuerpo, nombre, contacto) in enumerate(CONTRATISTAS, start=1)
        ]

        def entregar(codigo, contratista, obra, responsable, cuerpo_rut, dias_plazo=7):
            return services.registrar_entrega(
                herramienta=herramientas[codigo], contratista=contratistas[contratista], obra=obras[obra],
                responsable_nombre=responsable, responsable_rut=rut(cuerpo_rut),
                fecha_limite=hoy + timedelta(days=dias_plazo), firma=firma_simulada(cuerpo_rut % 7),
                usuario=bodega, ip="127.0.0.1",
            )

        def retroceder(prestamo, dias_entrega, dias_limite):
            """Ubica un préstamo en el pasado para mostrar casos de atraso reales."""
            Prestamo.objects.filter(pk=prestamo.pk).update(
                fecha_entrega=timezone.now() - timedelta(days=dias_entrega),
                fecha_limite=hoy + timedelta(days=dias_limite),
            )
            prestamo.refresh_from_db()
            return prestamo

        # Historial de préstamos cerrados, con cobros variados.
        cerrado = entregar("ESM-002", 0, 0, "Pedro Saavedra", 15234876)
        retroceder(cerrado, 12, -5)
        services.registrar_devolucion(
            prestamo=cerrado, condicion="BUENA", horas_uso=Decimal("31.5"), firma=firma_simulada(2),
            responsable_nombre="Pedro Saavedra", responsable_rut=rut(15234876), usuario=bodega, ip="127.0.0.1",
        )
        cerrado = entregar("SIE-001", 3, 2, "Daniela Pizarro", 16345987)
        retroceder(cerrado, 6, 1)
        services.registrar_devolucion(
            prestamo=cerrado, condicion="DESGASTE", horas_uso=Decimal("18"), firma=firma_simulada(4),
            observaciones="Disco gastado", responsable_nombre="Daniela Pizarro",
            responsable_rut=rut(16345987), usuario=bodega, ip="127.0.0.1",
        )
        cerrado = entregar("VIB-002", 1, 1, "Luis Contreras", 13456098)
        retroceder(cerrado, 9, -2)
        services.registrar_devolucion(
            prestamo=cerrado, condicion="DANADA", horas_uso=Decimal("40"), firma=firma_simulada(5),
            cargo_danos=85000, observaciones="Manguera del vibrador cortada",
            responsable_nombre="Luis Contreras", responsable_rut=rut(13456098), usuario=bodega, ip="127.0.0.1",
        )

        # Préstamos abiertos: dos contratistas con atraso, que la revisión bloqueará.
        demoledor = entregar("DMO-001", 0, 1, "Pedro Saavedra", 15234876)
        compactadora = entregar("COM-001", 0, 1, "Pedro Saavedra", 15234876)
        generador = entregar("GEN-002", 2, 3, "Camila Rivas", 17567109)
        retroceder(demoledor, 14, -4)
        retroceder(compactadora, 10, -1)
        retroceder(generador, 16, -9)
        entregar("BET-001", 1, 2, "Luis Contreras", 13456098, dias_plazo=1)
        entregar("RTM-001", 3, 0, "Daniela Pizarro", 16345987, dias_plazo=5)
        entregar("TAL-001", 3, 0, "Daniela Pizarro", 16345987, dias_plazo=10)
        entregar("NIV-001", 4, 2, "Matías Toro", 18678210, dias_plazo=14)
        entregar("CMP-001", 1, 3, "Valentina Bravo", 14789321, dias_plazo=3)

        # Planes de mantenimiento por fecha, por uso o por ambos.
        planes = [
            ("GEN-001", "Cambio de aceite y filtros", None, Decimal("250"), hoy - timedelta(days=120), Decimal("730")),
            ("RTM-002", "Revisión de carbones y engrase", None, Decimal("200"), hoy - timedelta(days=60), Decimal("350")),
            ("CRT-001", "Cambio de correa y revisión del disco", 90, Decimal("150"), hoy - timedelta(days=84), Decimal("170")),
            ("EST-001", "Calibración anual certificada", 365, None, hoy - timedelta(days=372), Decimal("0")),
            ("BMB-001", "Revisión de sello y sistema de arranque", 180, None, hoy - timedelta(days=30), Decimal("145")),
            ("VIB-001", "Inspección del eje flexible", 120, Decimal("300"), hoy - timedelta(days=40), Decimal("400")),
            ("COM-002", "Cambio de aceite del motor", None, Decimal("100"), hoy - timedelta(days=30), Decimal("310")),
        ]
        for codigo, nombre, dias, horas, ultima, horas_base in planes:
            PlanMantenimiento.objects.create(
                herramienta=herramientas[codigo], nombre=nombre, intervalo_dias=dias,
                intervalo_horas=horas, ultima_fecha=ultima, ultimas_horas=horas_base,
            )

        # Una orden correctiva cerrada y una herramienta dada de baja dejan historia visible.
        orden = OrdenMantenimiento.objects.create(
            herramienta=herramientas["SIE-002"], tipo=OrdenMantenimiento.Tipo.CORRECTIVA,
            descripcion="Revisar batería que no carga", fecha_programada=hoy - timedelta(days=3), tecnico=tecnica,
        )
        services.iniciar_orden(orden, tecnica)
        services.completar_orden(orden, tecnica, "Se reemplazó el cargador y se probó la batería.", 42000)
        services.cambiar_estado(
            herramientas["MED-001"], Herramienta.Estado.BAJA, admin, "Cayó de altura y perdió la calibración"
        )
        services.procesar_alertas()
