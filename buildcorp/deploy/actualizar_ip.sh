#!/usr/bin/env bash
# Lee la IP pública y el DNS de la instancia y los autoriza en el archivo .env de Django.
# Si no hay metadatos disponibles, deja el archivo como estaba.
set -u

DIRECTORIO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$DIRECTORIO/.env"
METADATOS="${METADATOS:-http://169.254.169.254/latest}"

token="$(curl -fsS -m 2 -X PUT "$METADATOS/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 60" 2>/dev/null || true)"
if [ -z "$token" ]; then
  echo "actualizar_ip: sin metadatos de EC2, se conserva la configuración actual."
  exit 0
fi

leer() {
  curl -fsS -m 2 -H "X-aws-ec2-metadata-token: $token" "$METADATOS/meta-data/$1" 2>/dev/null || true
}

ip="$(leer public-ipv4)"
dns="$(leer public-hostname)"

hosts="127.0.0.1,localhost"
origenes="http://127.0.0.1,http://localhost"
for destino in "$ip" "$dns"; do
  if [ -n "$destino" ]; then
    hosts="$hosts,$destino"
    origenes="$origenes,http://$destino"
  fi
done

# Reescribe el contenido sin reemplazar el archivo, para conservar dueño y permisos.
contenido="$(grep -vE '^(ALLOWED_HOSTS|CSRF_TRUSTED_ORIGINS)=' "$ENV_FILE")"
{
  printf '%s\n' "$contenido"
  printf 'ALLOWED_HOSTS=%s\n' "$hosts"
  printf 'CSRF_TRUSTED_ORIGINS=%s\n' "$origenes"
} > "$ENV_FILE"

echo "actualizar_ip: IP pública ${ip:-sin asignar}"
