#!/bin/bash
# 文档深度研究服务 - 停止脚本
ROOT="$(cd "$(dirname "$0")" && pwd)"
RUN_DIR="$ROOT/.run"

# 停止进程及其子进程
stop_pid() {
  local name=$1
  local pid_file="$RUN_DIR/$name.pid"
  if [ ! -f "$pid_file" ]; then
    echo "$name 未找到 PID 文件"
    return
  fi
  local pid=$(cat "$pid_file")
  rm -f "$pid_file"
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "$name 未在运行 (原 PID: $pid)"
    return
  fi
  # 先杀子进程再杀父进程
  pkill -P "$pid" 2>/dev/null || true
  sleep 0.5
  kill "$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null
  echo "已停止 $name (PID: $pid)"
}

echo "停止文档深度研究服务..."
stop_pid "backend"
stop_pid "frontend"

# 清理可能残留的 vite 进程（工作目录含 research2）
pkill -f "vite.*research2/frontend" 2>/dev/null || true

echo "服务已停止"
