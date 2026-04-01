#!/bin/bash
# Start Neo4j in Docker for local development
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
RUN_DIR="$ROOT/.run"
mkdir -p "$RUN_DIR"

CONTAINER_NAME="${NEO4J_CONTAINER_NAME:-llmdemo-neo4j}"
NEO4J_PORT_HTTP="${NEO4J_PORT_HTTP:-7474}"
NEO4J_PORT_BOLT="${NEO4J_PORT_BOLT:-7687}"
NEO4J_USER="${NEO4J_USER:-neo4j}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-neo4j12345}"

if ! command -v docker >/dev/null 2>&1; then
  echo "未检测到 docker，请先安装 Docker Desktop。"
  exit 1
fi

if docker ps --format '{{.Names}}' | rg -x "$CONTAINER_NAME" >/dev/null 2>&1; then
  echo "Neo4j 已在运行: $CONTAINER_NAME"
  exit 0
fi

if docker ps -a --format '{{.Names}}' | rg -x "$CONTAINER_NAME" >/dev/null 2>&1; then
  echo "启动已存在容器: $CONTAINER_NAME"
  docker start "$CONTAINER_NAME" >/dev/null
else
  echo "创建并启动 Neo4j 容器: $CONTAINER_NAME"
  docker run -d \
    --name "$CONTAINER_NAME" \
    -p "$NEO4J_PORT_HTTP":7474 \
    -p "$NEO4J_PORT_BOLT":7687 \
    -e NEO4J_AUTH="$NEO4J_USER/$NEO4J_PASSWORD" \
    -v "$ROOT/data/neo4j/data:/data" \
    -v "$ROOT/data/neo4j/logs:/logs" \
    -v "$ROOT/data/neo4j/import:/import" \
    -v "$ROOT/data/neo4j/plugins:/plugins" \
    neo4j:5 >/dev/null
fi

echo "Neo4j 启动完成"
echo "  HTTP: http://localhost:$NEO4J_PORT_HTTP"
echo "  Bolt: bolt://localhost:$NEO4J_PORT_BOLT"
echo "  用户: $NEO4J_USER"
echo "  密码: $NEO4J_PASSWORD"
echo ""
echo "请在 backend/.env 中配置："
echo "NEO4J_URI=bolt://localhost:$NEO4J_PORT_BOLT"
echo "NEO4J_USER=$NEO4J_USER"
echo "NEO4J_PASSWORD=$NEO4J_PASSWORD"
echo "NEO4J_DATABASE=neo4j"
