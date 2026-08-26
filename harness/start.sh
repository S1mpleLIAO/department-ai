#!/bin/sh
set -eu

CONFIG_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname -- "$CONFIG_DIR")
WORKSPACE_DIR=$(dirname -- "$PROJECT_DIR")
PRESET_DIR="$CONFIG_DIR/presets/department"

if [ -f "$PROJECT_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$PROJECT_DIR/.env"
  set +a
fi

HARNESS_DIR=${DEPARTMENT_HARNESS_DIR:-"$WORKSPACE_DIR/deepseek-harness"}
RUNTIME_DIR=${DEPARTMENT_RUNTIME_DIR:-"$PROJECT_DIR/runtime-data"}

export DSH_HOME=${DSH_HOME:-"$RUNTIME_DIR/dsh-home"}
export DEPARTMENT_SKILL_DIR=${DEPARTMENT_SKILL_DIR:-"$RUNTIME_DIR/department-skills"}

if ! command -v node >/dev/null 2>&1 || ! command -v pnpm >/dev/null 2>&1; then
  RUNTIME_ROOT=${DEPARTMENT_NODE_RUNTIME_ROOT:-"$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies"}
  PATH="$RUNTIME_ROOT/node/bin:$RUNTIME_ROOT/bin/fallback:/usr/bin:/bin"
  export PATH
fi

if [ ! -f "$HARNESS_DIR/package.json" ]; then
  echo "DeepSeek Harness not found: $HARNESS_DIR" >&2
  exit 1
fi

mkdir -p "$DSH_HOME/profiles/web" "$DEPARTMENT_SKILL_DIR" "$DSH_HOME/.agent-presets/department"
cp "$PRESET_DIR/preset.yml" "$PRESET_DIR/agent.cordis.yml" "$DSH_HOME/.agent-presets/department/"

cd "$HARNESS_DIR"
exec pnpm dsh --profile web --patch "$CONFIG_DIR/cordis.yml" --no-open
