#!/usr/bin/env bash
# Aplica en EC2 los últimos cambios del repositorio. Uso: sudo bash deploy/actualizar.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_USER="${SUDO_USER:-ubuntu}"
cd "$APP_DIR"
sudo -u "$APP_USER" -H git pull --ff-only
sudo -u "$APP_USER" -H .venv/bin/pip install --quiet -r requirements.txt
sudo -u "$APP_USER" -H .venv/bin/python manage.py migrate --noinput
sudo -u "$APP_USER" -H .venv/bin/python manage.py collectstatic --noinput --verbosity 0
systemctl restart buildcorp
echo "Actualización aplicada."
