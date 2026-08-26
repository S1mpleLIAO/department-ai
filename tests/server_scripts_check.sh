#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

require_file() {
  if [ ! -f "$project_dir/$1" ]; then
    echo "missing: $1" >&2
    exit 1
  fi
}

require_text() {
  file=$1
  text=$2
  if ! grep -F -- "$text" "$project_dir/$file" >/dev/null; then
    echo "$file missing required text: $text" >&2
    exit 1
  fi
}

reject_text() {
  file=$1
  text=$2
  if grep -F -- "$text" "$project_dir/$file" >/dev/null; then
    echo "$file contains forbidden text: $text" >&2
    exit 1
  fi
}

for script in \
  deploy-server.sh \
  start-server.sh \
  start-background.sh \
  stop-server.sh \
  restart-server.sh \
  status-server.sh \
  logs-server.sh
do
  require_file "$script"
  sh -n "$project_dir/$script"
done

require_text deploy-server.sh 'create -y -n "$conda_env"'
require_text deploy-server.sh 'pnpm install --frozen-lockfile'
require_text deploy-server.sh 'pnpm run build'
require_text deploy-server.sh 'plugin --profile web install --frozen-lockfile'
require_text deploy-server.sh 'backend/.venv'
require_text deploy-server.sh '仅作兼容性提示，不自动切换版本'
reject_text deploy-server.sh 'git -C "$harness_dir" fetch'
reject_text deploy-server.sh 'git -C "$harness_dir" checkout'
require_text start-background.sh 'nohup'
require_text server-common.sh 'runtime-data'
require_text server-common.sh 'pids'
require_text server-common.sh 'logs'
require_text harness/start.sh '--no-open'
require_text backend/start.sh 'DEPARTMENT_PYTHON_BIN'

echo "server script checks passed"
