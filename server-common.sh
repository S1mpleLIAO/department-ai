#!/bin/sh

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
workspace_dir=$(dirname -- "$project_dir")
runtime_dir=${DEPARTMENT_RUNTIME_DIR:-"$project_dir/runtime-data"}
pid_dir="$runtime_dir/pids"
log_dir="$runtime_dir/logs"
pid_file="$pid_dir/department-ai.pid"
log_file="$log_dir/department-ai.log"
conda_env=${DEPARTMENT_CONDA_ENV:-department-ai}

find_conda() {
  if [ -n "${DEPARTMENT_CONDA_BIN:-}" ] && [ -x "$DEPARTMENT_CONDA_BIN" ]; then
    printf '%s\n' "$DEPARTMENT_CONDA_BIN"
    return 0
  fi
  if command -v conda >/dev/null 2>&1; then
    command -v conda
    return 0
  fi
  for candidate in \
    "$HOME/anaconda3/bin/conda" \
    "$HOME/miniconda3/bin/conda" \
    /opt/conda/bin/conda
  do
    if [ -x "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

is_ready() {
  curl --fail --silent --output /dev/null "$1" 2>/dev/null
}

read_owned_pid() {
  if [ -f "$pid_file" ]; then
    cat "$pid_file"
  fi
}
