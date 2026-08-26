#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if [ -n "${DEPARTMENT_PYTHON_BIN:-}" ]; then
  python_bin=$DEPARTMENT_PYTHON_BIN
elif [ -x "$project_dir/.venv/bin/python" ]; then
  python_bin="$project_dir/.venv/bin/python"
elif command -v python >/dev/null 2>&1; then
  python_bin=$(command -v python)
else
  python_bin=
fi

if [ -z "$python_bin" ] || [ ! -x "$python_bin" ]; then
  echo "尚未安装 Python 环境，请先执行："
  echo "cd \"$project_dir\""
  echo "python3 -m venv .venv"
  echo ".venv/bin/python -m pip install -e ."
  exit 1
fi

cd "$project_dir"
exec "$python_bin" -m uvicorn app.main:app \
  --host "${DEPARTMENT_PYTHON_HOST:-127.0.0.1}" \
  --port "${DEPARTMENT_PYTHON_PORT:-3081}"
