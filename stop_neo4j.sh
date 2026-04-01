#!/bin/bash
# Stop Neo4j Docker container for local development
set -e

CONTAINER_NAME="${NEO4J_CONTAINER_NAME:-llmdemo-neo4j}"

if ! command -v docker >/dev/null 2>&1; then
  echo "未检测到 docker。"
  exit 1
fi

if docker ps --format '{{.Names}}' | rg -x "$CONTAINER_NAME" >/dev/null 2>&1; then
  docker stop "$CONTAINER_NAME" >/dev/null
  echo "已停止 Neo4j 容器: $CONTAINER_NAME"
else
  echo "Neo4j 容器未运行: $CONTAINER_NAME"
fi
