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
require_text deploy-server.sh 'plugin --profile web install --no-frozen-lockfile'
require_text deploy-server.sh 'pnpm --version'
require_text deploy-server.sh 'python-deps.sha256'
require_text deploy-server.sh 'harness-build.revision'
require_text deploy-server.sh 'plugin-profile.sha256'
require_text deploy-server.sh '--no-capture-output'
require_text deploy-server.sh '仅作兼容性提示，不自动切换版本'
reject_text deploy-server.sh 'git -C "$harness_dir" fetch'
reject_text deploy-server.sh 'git -C "$harness_dir" checkout'
reject_text deploy-server.sh 'plugin --profile web install --frozen-lockfile'
require_text start-background.sh 'nohup'
require_text server-common.sh 'runtime-data'
require_text server-common.sh 'deploy-state'
require_text server-common.sh 'pids'
require_text server-common.sh 'logs'
require_text harness/start.sh '--no-open'
require_text backend/start.sh 'DEPARTMENT_PYTHON_BIN'
require_file AGENTS.md
require_file docs/architecture.md
require_text AGENTS.md 'backend/app/main.py'
require_text AGENTS.md 'frontend/js/main.js'
require_text AGENTS.md "When operating in an isolated worktree, use that active worktree's corresponding Aliyun path and never execute against another checkout."
require_text AGENTS.md 'Shared `core` and `ui` modules must not import concrete feature modules.'
require_text docs/architecture.md 'main -> features -> core'
require_text docs/architecture.md '新增功能入口'
require_text docs/architecture.md 'Frontend `knowledge` -> backend `catalog` + `documents` + `search`.'

test_root=$(mktemp -d)
cleanup_timeout_test() {
  if [ -f "$test_root/background/runtime-data/pids/department-ai.pid" ]; then
    timeout_test_pid=$(cat "$test_root/background/runtime-data/pids/department-ai.pid")
    /bin/kill -TERM -- "-$timeout_test_pid" 2>/dev/null || true
  fi
  rm -rf "$test_root"
}
trap cleanup_timeout_test EXIT INT TERM

mkdir -p "$test_root/http-status-bin" "$test_root/status"
printf '%s\n' '#!/bin/sh' 'case " $* " in' '  *" --write-out "*) printf "401"; exit 0 ;;' '  *) exit 22 ;;' 'esac' >"$test_root/http-status-bin/curl"
chmod +x "$test_root/http-status-bin/curl"

if ! PATH="$test_root/http-status-bin:$PATH" sh -c '. "$1"; is_harness_ready "http://127.0.0.1:3080/"' sh "$project_dir/server-common.sh"; then
  echo "server-common.sh should treat Harness HTTP 401 as ready" >&2
  exit 1
fi

cp "$project_dir/server-common.sh" "$test_root/status/server-common.sh"
cp "$project_dir/status-server.sh" "$test_root/status/status-server.sh"
chmod +x "$test_root/status/status-server.sh"
PATH="$test_root/http-status-bin:$PATH" sh "$test_root/status/status-server.sh" >"$test_root/status.log" 2>&1 || true
if ! grep -F 'DeepSeek Harness：正常' "$test_root/status.log" >/dev/null; then
  echo "status-server.sh should report Harness HTTP 401 as ready" >&2
  exit 1
fi

mkdir -p "$test_root/start-401/backend" "$test_root/start-401/harness" "$test_root/start-401-bin"
cp "$project_dir/start.sh" "$test_root/start-401/start.sh"
cp "$project_dir/server-common.sh" "$test_root/start-401/server-common.sh"
printf '%s\n' '#!/bin/sh' 'case "$*" in' '  *3081/health*) exit 0 ;;' '  *--write-out*) printf "401"; exit 0 ;;' '  *) exit 22 ;;' 'esac' >"$test_root/start-401-bin/curl"
printf '%s\n' '#!/bin/sh' 'printf "started\n" >"$HARNESS_START_MARKER"' >"$test_root/start-401/harness/start.sh"
printf '%s\n' '#!/bin/sh' 'exit 1' >"$test_root/start-401/backend/start.sh"
chmod +x "$test_root/start-401-bin/curl" "$test_root/start-401/start.sh" "$test_root/start-401/backend/start.sh" "$test_root/start-401/harness/start.sh"

if ! PATH="$test_root/start-401-bin:$PATH" HARNESS_START_MARKER="$test_root/harness-start-marker" sh "$test_root/start-401/start.sh" >"$test_root/start-401.log" 2>&1; then
  echo "start.sh should accept Harness HTTP 401 as an already running service" >&2
  exit 1
fi
if [ -f "$test_root/harness-start-marker" ]; then
  echo "start.sh restarted a Harness service that was already returning HTTP 401" >&2
  exit 1
fi

mkdir -p "$test_root/background-401" "$test_root/background-401-bin"
cp "$project_dir/start-background.sh" "$test_root/background-401/start-background.sh"
cp "$project_dir/server-common.sh" "$test_root/background-401/server-common.sh"
printf '%s\n' '#!/bin/sh' 'case "$*" in' '  *--write-out*) printf "401"; exit 0 ;;' '  *) exit 22 ;;' 'esac' >"$test_root/background-401-bin/curl"
printf '%s\n' '#!/bin/sh' 'exit 0' >"$test_root/background-401/start-server.sh"
chmod +x "$test_root/background-401-bin/curl" "$test_root/background-401/start-background.sh" "$test_root/background-401/start-server.sh"
PATH="$test_root/background-401-bin:$PATH" DEPARTMENT_BACKGROUND_STARTUP_TIMEOUT=1 sh "$test_root/background-401/start-background.sh" >"$test_root/background-401.log" 2>&1 || true
if ! grep -F '检测到 3080 或 3081 端口已有服务' "$test_root/background-401.log" >/dev/null; then
  echo "start-background.sh should detect an existing Harness that returns HTTP 401" >&2
  exit 1
fi

mkdir -p "$test_root/bin" "$test_root/foreground/backend" "$test_root/foreground/harness"
printf '%s\n' '#!/bin/sh' 'count=$(cat "$FAKE_CURL_COUNT")' 'printf "%s\n" "$((count + 1))" >"$FAKE_CURL_COUNT"' 'exit 1' >"$test_root/bin/curl"
printf '%s\n' '#!/bin/sh' 'exit 0' >"$test_root/bin/sleep"
printf '%s\n' '#!/bin/sh' 'exec /bin/sleep 30' >"$test_root/foreground/backend/start.sh"
printf '%s\n' '#!/bin/sh' 'exec /bin/sleep 30' >"$test_root/foreground/harness/start.sh"
chmod +x "$test_root/bin/curl" "$test_root/bin/sleep" "$test_root/foreground/backend/start.sh" "$test_root/foreground/harness/start.sh"
cp "$project_dir/start.sh" "$test_root/foreground/start.sh"
cp "$project_dir/server-common.sh" "$test_root/foreground/server-common.sh"
printf '0\n' >"$test_root/foreground-curl-count"

if PATH="$test_root/bin:$PATH" FAKE_CURL_COUNT="$test_root/foreground-curl-count" DEPARTMENT_STARTUP_TIMEOUT=2 sh "$test_root/foreground/start.sh" >"$test_root/foreground.log" 2>&1; then
  echo "start.sh should time out when readiness never succeeds" >&2
  exit 1
fi
foreground_curl_count=$(cat "$test_root/foreground-curl-count")
if [ "$foreground_curl_count" -ne 3 ]; then
  echo "start.sh ignored DEPARTMENT_STARTUP_TIMEOUT: expected 3 readiness checks, got $foreground_curl_count" >&2
  exit 1
fi

mkdir -p "$test_root/background"
cp "$project_dir/start-background.sh" "$test_root/background/start-background.sh"
cp "$project_dir/server-common.sh" "$test_root/background/server-common.sh"
printf '%s\n' '#!/bin/sh' 'printf "%s\n" "$$" >"$FAKE_SERVICE_PID_FILE"' 'exec /bin/sleep 30' >"$test_root/background/start-server.sh"
chmod +x "$test_root/background/start-background.sh" "$test_root/background/start-server.sh"
printf '0\n' >"$test_root/background-curl-count"

if PATH="$test_root/bin:$PATH" FAKE_CURL_COUNT="$test_root/background-curl-count" FAKE_SERVICE_PID_FILE="$test_root/background-service-pid" DEPARTMENT_BACKGROUND_STARTUP_TIMEOUT=2 sh "$test_root/background/start-background.sh" >"$test_root/background.log" 2>&1; then
  echo "start-background.sh should time out when readiness never succeeds" >&2
  exit 1
fi
background_pid=$(cat "$test_root/background-service-pid")
if kill -0 "$background_pid" 2>/dev/null; then
  echo "start-background.sh left its service process running after timeout" >&2
  exit 1
fi
if [ -f "$test_root/background/runtime-data/pids/department-ai.pid" ]; then
  echo "start-background.sh left a stale PID file after timeout" >&2
  exit 1
fi
background_curl_count=$(cat "$test_root/background-curl-count")
if [ "$background_curl_count" -ne 4 ]; then
  echo "start-background.sh ignored DEPARTMENT_BACKGROUND_STARTUP_TIMEOUT: expected 4 readiness checks, got $background_curl_count" >&2
  exit 1
fi

mkdir -p "$test_root/launcher/department-ai/harness/presets/department" "$test_root/launcher/deepseek-harness" "$test_root/launcher-bin"
cp "$project_dir/harness/start.sh" "$test_root/launcher/department-ai/harness/start.sh"
printf '{}\n' >"$test_root/launcher/deepseek-harness/package.json"
printf 'preset\n' >"$test_root/launcher/department-ai/harness/presets/department/preset.yml"
printf 'agent\n' >"$test_root/launcher/department-ai/harness/presets/department/agent.cordis.yml"
printf '%s\n' '#!/bin/sh' 'printf "node %s\n" "$*" >"$HARNESS_LAUNCH_RECORD"' >"$test_root/launcher-bin/node"
printf '%s\n' '#!/bin/sh' 'printf "pnpm %s\n" "$*" >"$HARNESS_LAUNCH_RECORD"' >"$test_root/launcher-bin/pnpm"
chmod +x "$test_root/launcher-bin/node" "$test_root/launcher-bin/pnpm" "$test_root/launcher/department-ai/harness/start.sh"

PATH="$test_root/launcher-bin:$PATH" HARNESS_LAUNCH_RECORD="$test_root/harness-launch-record" DEPARTMENT_RUNTIME_DIR="$test_root/launcher-runtime" sh "$test_root/launcher/department-ai/harness/start.sh"
harness_launch=$(cat "$test_root/harness-launch-record")
case "$harness_launch" in
  'node --import tsx/esm apps/cli/src/bin.ts --profile web --patch '*) ;;
  *)
    echo "harness/start.sh must exec the Node service directly, got: $harness_launch" >&2
    exit 1
    ;;
esac

echo "server script checks passed"
