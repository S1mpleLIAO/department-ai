#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck disable=SC1091
. "$project_dir/server-common.sh"

conda_bin=$(find_conda) || {
  echo "未找到 Conda。可设置 DEPARTMENT_CONDA_BIN 指向 conda 可执行文件。" >&2
  exit 1
}

env_prefix=$(
  "$conda_bin" run -n "$conda_env" python -c 'import sys; print(sys.prefix)'
) || {
  echo "Conda 环境 $conda_env 不存在，请先运行 ./deploy-server.sh。" >&2
  exit 1
}

export PATH="$env_prefix/bin:$PATH"
export DEPARTMENT_PYTHON_BIN="$env_prefix/bin/python"

exec "$project_dir/start.sh"
