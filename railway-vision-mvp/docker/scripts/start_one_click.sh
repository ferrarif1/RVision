#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT_DIR"

if [ ! -f docker/.env ]; then
  cp docker/.env.example docker/.env
  echo "[start_one_click] 已从 .env.example 生成 docker/.env"
fi

echo "[start_one_click] 启动中心端服务（postgres/redis/backend/frontend）..."
docker compose --env-file docker/.env -f docker/docker-compose.yml up -d --build

echo "[start_one_click] 等待 backend 健康检查..."
for i in $(seq 1 40); do
  if curl -fsS http://localhost:8000/api/health >/dev/null 2>&1; then
    echo "[start_one_click] backend 已就绪：http://localhost:8000/api/health"
    break
  fi
  sleep 2
  if [ "$i" -eq 40 ]; then
    echo "[start_one_click] backend 启动超时，请检查: docker compose -f docker/docker-compose.yml logs -f backend"
    exit 1
  fi
done

echo "[start_one_click] frontend: http://localhost:8080"
echo "[start_one_click] backend docs: http://localhost:8000/docs"
