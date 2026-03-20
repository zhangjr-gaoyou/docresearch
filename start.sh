#!/bin/bash
# 文档深度研究服务 - 启动脚本
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
RUN_DIR="$ROOT/.run"
mkdir -p "$RUN_DIR"

# 检查是否已在运行
if [ -f "$RUN_DIR/backend.pid" ] && kill -0 "$(cat "$RUN_DIR/backend.pid")" 2>/dev/null; then
  echo "后端已在运行 (PID: $(cat "$RUN_DIR/backend.pid"))"
else
  echo "启动后端..."
  cd "$ROOT/backend"
  if [ ! -d ".venv" ]; then
    # 优先使用 Homebrew Python，避免与 Miniconda 架构冲突
    PYTHON="${PYTHON:-/usr/local/bin/python3}"
    [ -x "$PYTHON" ] || PYTHON="$(command -v python3)"
    "$PYTHON" -m venv .venv
  fi
  source .venv/bin/activate
  pip install -q -r requirements.txt
  nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 > "$RUN_DIR/backend.log" 2>&1 &
  echo $! > "$RUN_DIR/backend.pid"
  echo "后端已启动 (PID: $(cat "$RUN_DIR/backend.pid")), 端口 8000"
fi

if [ -f "$RUN_DIR/frontend.pid" ] && kill -0 "$(cat "$RUN_DIR/frontend.pid")" 2>/dev/null; then
  echo "前端已在运行 (PID: $(cat "$RUN_DIR/frontend.pid"))"
else
  echo "启动前端..."
  cd "$ROOT/frontend"
  [ -d node_modules ] || npm install
  nohup npm run dev > "$RUN_DIR/frontend.log" 2>&1 &
  echo $! > "$RUN_DIR/frontend.pid"
  echo "前端已启动 (PID: $(cat "$RUN_DIR/frontend.pid")), 访问 http://localhost:5173"
fi

echo ""
echo "服务已启动:"
echo "  前端: http://localhost:5173"
echo "  后端: http://localhost:8000"
echo "  日志: $RUN_DIR/*.log"
