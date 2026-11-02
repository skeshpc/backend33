#!/usr/bin/env bash
# Instala BuildCorp en una instancia EC2 con Ubuntu 24.04. Se puede repetir sin perder datos.
# Uso, desde la carpeta del repositorio:  sudo bash deploy/install_ec2.sh
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Ejecuta este script con sudo: sudo bash deploy/install_ec2.sh" >&2
  exit 1
fi

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_USER="${SUDO_USER:-ubuntu}"
APP_HOME="$(getent passwd "$APP_USER" | cut -d: -f6)"
CREDENCIALES="$APP_HOME/credenciales_buildcorp.txt"
ENV_FILE="$APP_DIR/.env"
DB_NAME="buildcorp"
DB_USER="buildcorp"

paso() { printf '\n==> %s\n' "$1"; }
aleatorio() { /usr/bin/python3 -c "import secrets; print(secrets.token_urlsafe($1))"; }
como_app() { sudo -u "$APP_USER" -H "$@"; }

paso "Instalando paquetes del sistema"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y -q
apt-get install -y -q python3 python3-venv postgresql nginx curl

# Las instancias pequeñas de AWS Academy tienen 1 GB de RAM: la memoria virtual evita caídas.
if [ "$(swapon --noheadings 2>/dev/null | wc -l)" -eq 0 ] && [ "$(awk '/MemTotal/ {print $2}' /proc/meminfo)" -lt 2000000 ]; then
  paso "Creando 1 GB de memoria virtual"
  if [ ! -f /swapfile ]; then
    fallocate -l 1G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
  fi
  swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

paso "Configurando PostgreSQL"
systemctl enable --now postgresql

if [ -f "$ENV_FILE" ] && grep -q '^DB_PASSWORD=' "$ENV_FILE"; then
  DB_PASSWORD="$(grep '^DB_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)"
else
  DB_PASSWORD="$(aleatorio 24)"
fi

sudo -u postgres psql -v ON_ERROR_STOP=1 -q <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$DB_USER') THEN
    CREATE ROLE $DB_USER LOGIN;
  END IF;
END
\$\$;
ALTER ROLE $DB_USER WITH LOGIN PASSWORD '$DB_PASSWORD';
SQL
if [ "$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'")" != "1" ]; then
  sudo -u postgres createdb -O "$DB_USER" "$DB_NAME"
fi

paso "Preparando la aplicación"
if [ ! -f "$ENV_FILE" ]; then
  umask 077
  cat > "$ENV_FILE" <<ENV
DEBUG=False
SECRET_KEY=$(aleatorio 50)
DB_NAME=$DB_NAME
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASSWORD
DB_HOST=127.0.0.1
DB_PORT=5432
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
MORA_DIAS_GRACIA=0
RECARGO_MORA_PORCENTAJE=50
MANTENCION_AVISO_DIAS=7
ALLOWED_HOSTS=127.0.0.1,localhost
CSRF_TRUSTED_ORIGINS=http://127.0.0.1,http://localhost
ENV
  umask 022
fi
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"
chmod 600 "$ENV_FILE"
bash "$APP_DIR/deploy/actualizar_ip.sh"

como_app /usr/bin/python3 -m venv "$APP_DIR/.venv"
como_app "$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
como_app "$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

cd "$APP_DIR"
como_app "$APP_DIR/.venv/bin/python" manage.py migrate --noinput
como_app "$APP_DIR/.venv/bin/python" manage.py collectstatic --noinput --verbosity 0

if [ ! -f "$CREDENCIALES" ]; then
  paso "Cargando usuarios y datos de ejemplo"
  CLAVE_DEMO="$(aleatorio 12)"
  DEMO_PASSWORD="$CLAVE_DEMO" como_app --preserve-env=DEMO_PASSWORD "$APP_DIR/.venv/bin/python" manage.py cargar_demo
  (
    umask 077
    {
      echo "Contraseña de todos los usuarios de ejemplo: $CLAVE_DEMO"
      echo "Usuarios: admin, ana.admin, bruno.bodega, tania.tecnica, sergio.supervisor"
    } > "$CREDENCIALES"
  )
  chown "$APP_USER":"$APP_USER" "$CREDENCIALES"
fi

paso "Instalando los servicios"
for archivo in buildcorp.service buildcorp-alertas.service buildcorp-alertas.timer; do
  sed -e "s|__APP_DIR__|$APP_DIR|g" -e "s|__APP_USER__|$APP_USER|g" "$APP_DIR/deploy/$archivo" > "/etc/systemd/system/$archivo"
done
cp "$APP_DIR/deploy/nginx.conf" /etc/nginx/sites-available/buildcorp
ln -sf /etc/nginx/sites-available/buildcorp /etc/nginx/sites-enabled/buildcorp
rm -f /etc/nginx/sites-enabled/default
nginx -t

systemctl daemon-reload
systemctl enable --now buildcorp-alertas.timer
systemctl enable buildcorp nginx
systemctl restart buildcorp
systemctl restart nginx

paso "Comprobando el sitio"
estado="000"
for _ in $(seq 1 15); do
  estado="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/cuenta/ingresar/ || true)"
  [ "$estado" = "200" ] && break
  sleep 2
done
if [ "$estado" != "200" ]; then
  echo "El sitio respondió $estado. Revisa el registro con: sudo journalctl -u buildcorp -n 50" >&2
  exit 1
fi

IP_PUBLICA="$(grep '^ALLOWED_HOSTS=' "$ENV_FILE" | cut -d= -f2 | cut -d, -f3)"
echo
echo "Listo. Abre: http://${IP_PUBLICA:-IP-PUBLICA-DE-LA-INSTANCIA}/"
echo "Usuarios y contraseña en: $CREDENCIALES"
echo "Escribe esa IP en el archivo README.md antes de entregar."
