# BuildCorp: sistema de alquiler y control de herramientas

Aplicación web para el pañol de una constructora. Registra dónde está cada herramienta, quién firmó por ella, cuánto se debe cobrar y cuándo le toca mantención. Bloquea automáticamente a los contratistas con devoluciones vencidas.

- **Asignatura:** Desarrollo Backend, Evaluación 3
- **Estudiante:** COMPLETAR
- **Aplicación en AWS EC2:** http://54.197.29.100/
- **Administrador de Django:** http://54.197.29.100/admin/
- **API:** http://54.197.29.100/api/v1/

Las credenciales de acceso se entregan directamente al docente y no se publican en este repositorio.

## Cómo responde al caso

| Requerimiento | Solución | Dónde está |
|---|---|---|
| Catálogo con trazabilidad de estado | Estados Disponible, En uso, Mantenimiento y Dado de baja. Cada cambio queda con fecha, usuario y motivo | `Herramienta`, `MovimientoEstado`, `services.cambiar_estado` |
| Entrega y devolución con firma digital | El responsable firma en pantalla. Se guarda el trazo con su huella SHA-256 y se genera un acta imprimible | `Prestamo`, `Firma`, `services.registrar_entrega`, `services.registrar_devolucion`, `static/herramientas/js/firma.js` |
| Mantenimientos preventivos por uso o fecha | Planes por días, por horas de uso o ambos. Generan órdenes y alertas. Con el plan vencido, la herramienta no se entrega | `PlanMantenimiento`, `OrdenMantenimiento`, `services.procesar_alertas` |
| Alertas de morosidad y bloqueo automático | Revisión cada 15 minutos y comprobación en cada entrega. El bloqueo se levanta al devolver lo vencido | `Alerta`, `services.actualizar_bloqueo`, comando `procesar_alertas` |
| Cobros inexactos a subcontratistas | Tarifa fijada al entregar. Días, mora y daños se calculan con una sola regla, y se exportan a CSV | `Prestamo.calcular_cobro`, vista `cobros` |

### Regla de cobro

```
Días cobrados = días corridos desde la entrega, con un mínimo de 1
Arriendo      = días cobrados × tarifa pactada
Recargo       = días posteriores a la fecha límite × tarifa pactada × 50 %
Total         = arriendo + recargo + cargo por daño o extravío
```

Si la herramienta se declara extraviada y no se indica un cargo, se cobra su valor de reposición.

## Tecnologías

Python 3.12, Django 5.2, Django REST Framework 3.16, PostgreSQL 16, Gunicorn, Nginx, HTML, CSS y JavaScript sin frameworks.

## Arquitectura

```
Navegador ──> Nginx :80 ──> Gunicorn :8001 ──> Django ──> PostgreSQL :5432

Dentro de Django:
  vistas web ───┐
  API REST ─────┼──> services.py ──> modelos (ORM)
  Django Admin ─┘
```

Todo corre dentro de una única instancia EC2. Las tres entradas usan las mismas funciones de `services.py`, así que una regla se cumple igual desde cualquiera de ellas. La base de datos refuerza lo más importante: una herramienta no puede tener dos préstamos abiertos.

```
config/                  Configuración de Django
herramientas/
  models.py              Modelos del dominio
  services.py            Reglas de negocio
  views.py, urls.py      Interfaz web y CRUD con funciones
  admin.py               Django Admin personalizado
  roles.py               Grupos y permisos
  api/                   API REST
  management/commands/   procesar_alertas y cargar_demo
  templates/, static/    Interfaz
  tests/                 Pruebas automatizadas
deploy/                  Scripts y servicios para EC2
```

## Roles

| Rol | Puede |
|---|---|
| Administrador | Todo, incluido el administrador de Django y los bloqueos manuales |
| Bodeguero | Registrar entregas y devoluciones, gestionar el catálogo, ver cobros y atender alertas |
| Técnico | Gestionar planes y órdenes, cambiar estados y atender alertas de mantención. No ve contratistas ni cobros |
| Supervisor | Consultar todo y exportar cobros, sin modificar |

Usuarios de ejemplo: `admin`, `ana.admin`, `bruno.bodega`, `tania.tecnica` y `sergio.supervisor`.

## Despliegue en AWS Academy

### 1. Crear la instancia

En EC2, lanza una instancia con:

- **Imagen:** Ubuntu Server 24.04 LTS
- **Tipo:** `t2.micro` o superior
- **Par de claves:** `vockey`
- **Grupo de seguridad:** permite SSH (22) y HTTP (80). No abras el puerto 5432: PostgreSQL solo atiende dentro de la instancia

### 2. Conectarse e instalar

Conéctate con EC2 Instance Connect o por SSH con `labsuser.pem`:

```bash
ssh -i labsuser.pem ubuntu@IP-PUBLICA
git clone URL-DEL-REPOSITORIO buildcorp
cd buildcorp
sudo bash deploy/install_ec2.sh
```

El script instala PostgreSQL, Nginx y Python, crea la base de datos con una contraseña aleatoria, aplica las migraciones, carga los datos de ejemplo y deja los servicios activos. Se puede repetir sin perder datos. Al terminar muestra la dirección del sitio. La contraseña de los usuarios queda en `~/credenciales_buildcorp.txt`.

### 3. Publicar la IP

Reemplaza `COMPLETAR-IP-PUBLICA` en este archivo por la IP de la instancia y sube el cambio al repositorio.

### Si el laboratorio se reinicia

Al apagar y encender la instancia, los servicios vuelven solos y Django autoriza la IP nueva. Lo que no cambia solo es este archivo: si la IP cambió, actualízala aquí. Para que no cambie, asigna una IP elástica si tu laboratorio lo permite.

### Comandos útiles

```bash
sudo systemctl status buildcorp            # estado de la aplicación
sudo journalctl -u buildcorp -n 50         # registro de la aplicación
systemctl list-timers 'buildcorp-alertas*' # próxima revisión programada
sudo bash deploy/actualizar.sh             # aplicar cambios del repositorio
```

## Ejecución local

Requiere Python 3.12 o superior y PostgreSQL.

```bash
sudo -u postgres psql -c "CREATE ROLE buildcorp LOGIN CREATEDB PASSWORD 'cambia-esta-clave';"
sudo -u postgres createdb -O buildcorp buildcorp

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

python manage.py migrate
python manage.py cargar_demo --password "una-clave-para-probar"
python manage.py runserver
```

Abre http://127.0.0.1:8000/. Para ejecutar las pruebas, que corren sobre PostgreSQL:

```bash
python manage.py test
```

## API REST

Autenticación por sesión o por token. Para obtener un token:

```bash
curl -X POST http://IP/api/v1/auth/token/ -d "username=USUARIO&password=CLAVE"
curl http://IP/api/v1/herramientas/ -H "Authorization: Token EL_TOKEN"
```

| Método y ruta | Uso |
|---|---|
| `GET, POST /api/v1/herramientas/` | Listar y crear. Filtro `?estado=EN_USO` |
| `GET, PUT, PATCH, DELETE /api/v1/herramientas/{id}/` | Consultar, editar y eliminar |
| `POST /api/v1/herramientas/{id}/cambiar-estado/` | Cambiar el estado con motivo |
| `GET /api/v1/herramientas/{id}/trazabilidad/` | Historial de estados |
| `GET /api/v1/prestamos/` | Listar. Filtro `?situacion=activos` o `vencidos` |
| `POST /api/v1/prestamos/` | Registrar una entrega con firma |
| `POST /api/v1/prestamos/{id}/devolver/` | Registrar una devolución con firma |
| `CRUD /api/v1/contratistas/`, `/obras/`, `/categorias/`, `/planes/` | Administración de datos |
| `POST /api/v1/contratistas/{id}/bloquear/`, `/desbloquear/` | Bloqueo manual |
| `CRUD /api/v1/ordenes/` | Órdenes de mantenimiento |
| `POST /api/v1/ordenes/{id}/iniciar/`, `/completar/`, `/cancelar/` | Ciclo de una orden |
| `GET /api/v1/alertas/` | Listar. Filtro `?abiertas=1` |
| `POST /api/v1/alertas/{id}/atender/` | Marcar como revisada |
| `POST /api/v1/alertas/procesar/` | Ejecutar la revisión ahora |
| `GET /api/v1/resumen/` | Totales para la interfaz |

Códigos de error: `400` datos inválidos, `401` sin autenticar, `403` el rol no lo permite, `409` una regla de negocio lo impide.

## Guion de demostración

1. **Tablero:** entra como `bruno.bodega`. Cada placa es una herramienta: las llenas están en bodega, las punteadas en obra, las rayadas en mantenimiento y las rojas tienen la devolución vencida.
2. **Bloqueo:** en *Registrar entrega*, elige *Excavaciones Andina Ltda.* La pantalla consulta la API y avisa que está bloqueado.
3. **Entrega firmada:** elige *Eléctrica Los Andes SpA* y una herramienta disponible, firma y registra. Se abre el acta.
4. **Trazabilidad:** abre la herramienta en el catálogo y revisa su historial.
5. **Desbloqueo y cobro:** en *Préstamos > Vencidos*, registra la devolución de *GEN-002*. *Montajes Cordillera SpA* se desbloquea y el acta muestra el recargo por mora.
6. **Mantenimiento:** entra como `tania.tecnica`, abre *EST-001* e inicia y completa su orden. Su plan vuelve a estar al día.
7. **Administración:** entra como `admin` en `/admin/` y prueba las acciones sobre herramientas.
8. **Permisos:** como `tania.tecnica`, intenta abrir `/cobros/`. La respuesta es 403.

## Limitaciones conocidas

- **Sin HTTPS.** El sitio se publica por HTTP, porque usa la IP de la instancia y no tiene dominio ni certificado. Para producción real se debe agregar un dominio y un certificado, y activar `SESSION_COOKIE_SECURE` y `CSRF_COOKIE_SECURE`.
- **Firma electrónica simple.** El sistema captura el trazo y detecta alteraciones posteriores de los datos firmados, pero no verifica la identidad del firmante con un certificado acreditado.
- **Alertas dentro del sistema.** Las alertas se muestran en la aplicación. No se envían por correo.
