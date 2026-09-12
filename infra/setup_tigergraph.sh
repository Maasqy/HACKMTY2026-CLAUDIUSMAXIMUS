#!/usr/bin/env bash
# HACKMTY2026-CLAUDIUSMAXIMUS — Paso 1: TigerGraph local en Docker/Colima
#
# Uso:
#   chmod +x infra/setup_tigergraph.sh
#   ./infra/setup_tigergraph.sh
#
# Qué hace:
#   1. Instala Homebrew si falta.
#   2. Instala Colima + Docker CLI + docker-compose (vía brew).
#   3. Arranca una VM de Colima (con Rosetta si estás en Apple Silicon, porque
#      la imagen de TigerGraph es x86_64-only).
#   4. Descarga tigergraph/community (Community Edition, sin license key).
#   5. Levanta el contenedor con los puertos de SSH, GSQL/REST y GraphStudio.
#   6. Arranca los servicios internos (gadmin start all).
#
# Requisitos: macOS con al menos 4 CPU / 8GB libres para la VM de Colima
# (recomendado 8 CPU / 24GB para uso cómodo).

set -euo pipefail

CONTAINER_NAME="tigergraph"
DATA_DIR="$HOME/tigergraph-data"
ARCH="$(uname -m)"

echo "== 1/6 Homebrew =="
if ! command -v brew &>/dev/null; then
  echo "Homebrew no encontrado, instalando..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  if [ -x /opt/homebrew/bin/brew ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [ -x /usr/local/bin/brew ]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
else
  echo "Homebrew ya instalado."
fi

echo "== 2/6 Colima + Docker CLI =="
brew list colima &>/dev/null || brew install colima
brew list docker &>/dev/null || brew install docker
brew list docker-compose &>/dev/null || brew install docker-compose

echo "== 3/6 Arrancando Colima =="
if colima status &>/dev/null; then
  echo "Colima ya está corriendo."
else
  if [ "$ARCH" = "arm64" ]; then
    echo "Apple Silicon detectado ($ARCH): arrancando Colima con Rosetta para poder correr la imagen x86_64 de TigerGraph."
    colima start --cpu 4 --memory 8 --disk 60 --vm-type=vz --vz-rosetta
  else
    colima start --cpu 4 --memory 8 --disk 60
  fi
fi

echo "== 4/6 Descargando imagen tigergraph/community =="
docker pull --platform linux/amd64 tigergraph/community:latest

echo "== 5/6 Levantando contenedor TigerGraph =="
mkdir -p "$DATA_DIR"
if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
  echo "El contenedor '$CONTAINER_NAME' ya existe, lo arranco si estaba detenido..."
  docker start "$CONTAINER_NAME" >/dev/null
else
  docker run -d \
    --platform linux/amd64 \
    -p 14022:22 \
    -p 9000:9000 \
    -p 14240:14240 \
    --name "$CONTAINER_NAME" \
    --ulimit nofile=1000000:1000000 \
    -v "$DATA_DIR":/home/tigergraph/mydata \
    -v tg-data:/home/tigergraph \
    -t tigergraph/community:latest
fi

echo "== 6/6 Verificando servicios internos =="
echo "Esta imagen arranca los servicios sola vía su entrypoint (no usa gadmin)."
echo "Esperando a que el contenedor termine de inicializar..."
sleep 20
docker exec "$CONTAINER_NAME" bash -lc 'curl -s --max-time 5 http://localhost:9000/echo || echo "(REST++ aún no responde, dale unos segundos mas y prueba: curl http://localhost:9000/echo)"'

cat <<'EOF'

✅ TigerGraph Community Edition está corriendo localmente.

  GraphStudio (UI):     http://localhost:14240
  REST++ / GSQL API:    http://localhost:9000
  SSH al contenedor:    ssh -p 14022 tigergraph@localhost   (user/pass: tigergraph/tigergraph)

⚠️  Cambia las contraseñas por defecto (usuario Linux y superusuario de la base
    de datos) antes de exponer esto fuera de tu máquina.

Siguiente paso: correr el script de ingesta (Listado_completo_69-B.csv +
AMLSim) para insertar vértices/aristas en TigerGraph.
EOF
