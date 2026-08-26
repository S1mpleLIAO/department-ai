#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python_bin="$project_dir/.venv/bin/python"

if [ ! -x "$python_bin" ]; then
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
