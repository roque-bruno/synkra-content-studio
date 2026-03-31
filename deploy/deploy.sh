#!/bin/bash
# Salk Content Studio — Deploy Script
# Executa no servidor via SSH (usuario deployer ou root)
# Uso: bash deploy.sh [--build]

set -euo pipefail

REPO_URL="https://github.com/roque-bruno/salk-content-studio.git"
INSTALL_DIR="/opt/content-studio"
REPO_DIR="${INSTALL_DIR}/repo"

echo "=== Salk Content Studio Deploy ==="
echo "$(date '+%Y-%m-%d %H:%M:%S')"

# 1. Clone ou update do repositorio
if [ -d "${REPO_DIR}/.git" ]; then
    echo "[1/4] Atualizando repositorio..."
    cd "${REPO_DIR}"
    git fetch origin main
    git reset --hard origin/main
else
    echo "[1/4] Clonando repositorio..."
    git clone --depth 1 --branch main "${REPO_URL}" "${REPO_DIR}"
fi

# 2. Copiar docker-compose de producao e .env
echo "[2/4] Preparando configuracao..."
cp "${REPO_DIR}/deploy/docker-compose.production.yml" "${INSTALL_DIR}/docker-compose.yml"

# Manter .env existente (nao sobrescrever credenciais)
if [ ! -f "${INSTALL_DIR}/.env" ]; then
    echo "ERRO: /opt/content-studio/.env nao encontrado. Crie o arquivo com as credenciais."
    exit 1
fi

# 3. Build e restart
echo "[3/4] Build e restart do container..."
cd "${INSTALL_DIR}"

# Ajustar context path para o repo clonado
sed -i "s|context: ../packages/content-pipeline|context: ${REPO_DIR}/packages/content-pipeline|" docker-compose.yml

docker compose build --no-cache
docker compose up -d

# 4. Health check
echo "[4/4] Aguardando health check..."
for i in $(seq 1 30); do
    if curl -sf http://127.0.0.1:8000/api/health > /dev/null 2>&1; then
        echo ""
        echo "=== Deploy concluido com sucesso ==="
        curl -s http://127.0.0.1:8000/api/health | python3 -m json.tool 2>/dev/null || curl -s http://127.0.0.1:8000/api/health
        echo ""
        docker compose ps
        exit 0
    fi
    printf "."
    sleep 2
done

echo ""
echo "ERRO: Health check falhou apos 60 segundos."
echo "Logs do container:"
docker compose logs --tail 50
exit 1
