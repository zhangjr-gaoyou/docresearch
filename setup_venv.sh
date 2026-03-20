#!/bin/bash
# 重建后端 venv，解决 Miniconda 与 venv 架构冲突
# 用法: ./setup_venv.sh  或  PYTHON=/path/to/python ./setup_venv.sh
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT/backend"

# 优先使用 Homebrew Python（避免 conda 的 x86_64/arm64 混用）
PYTHON="${PYTHON:-/usr/local/bin/python3}"
if [ ! -x "$PYTHON" ]; then
  PYTHON="$(command -v python3)"
fi
echo "使用 Python: $PYTHON"
"$PYTHON" --version

echo "删除旧 venv..."
rm -rf .venv

echo "创建新 venv..."
"$PYTHON" -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "venv 已就绪，可运行 ./start.sh 启动服务"
