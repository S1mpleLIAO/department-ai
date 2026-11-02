#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck disable=SC1091
. "$project_dir/server-common.sh"

harness_dir=${DEPARTMENT_HARNESS_DIR:-"$workspace_dir/deepseek-harness"}
expected_harness_version=$(tr -d '[:space:]' <"$project_dir/harness/HARNESS_VERSION")

if [ "$(uname -s)" != "Linux" ] || [ "$(uname -m)" != "x86_64" ]; then
  echo "本脚本只用于 Linux x86_64 服务器。" >&2
  exit 1
fi

conda_bin=$(find_conda) || {
  echo "未找到 Conda。可设置 DEPARTMENT_CONDA_BIN 指向 conda 可执行文件。" >&2
  exit 1
}

if [ ! -f "$project_dir/.env" ]; then
  echo "缺少 $project_dir/.env，请先从安全备份恢复服务器配置。" >&2
  exit 1
fi
chmod 600 "$project_dir/.env"

if [ ! -f "$harness_dir/package.json" ] || [ ! -d "$harness_dir/.git" ]; then
  echo "未找到官方 DeepSeek Harness Git 仓库：$harness_dir" >&2
  exit 1
fi

current_harness_revision=$(git -C "$harness_dir" describe --tags --always --dirty)
echo "[1/6] 使用当前 DeepSeek Harness：$current_harness_revision"
echo "      项目最后验证版本：$expected_harness_version（仅作兼容性提示，不自动切换版本）"

if "$conda_bin" env list | awk -v name="$conda_env" '$1 == name { found=1 } END { exit !found }'; then
  echo "[2/6] Conda 环境已存在，跳过创建：$conda_env"
else
  echo "[2/6] 创建独立 Conda 环境：$conda_env"
  "$conda_bin" create -y -n "$conda_env" -c conda-forge python=3.11 nodejs=24
fi

echo "[3/6] 检查 pnpm 和 Python 后端依赖"
required_pnpm_version=11.7.0
installed_pnpm_version=$(
  "$conda_bin" run -n "$conda_env" pnpm --version 2>/dev/null | tail -n 1 | tr -d '[:space:]' || true
)
if [ "$installed_pnpm_version" = "$required_pnpm_version" ]; then
  echo "      pnpm $required_pnpm_version 已安装，跳过"
else
  "$conda_bin" run --no-capture-output -n "$conda_env" \
    npm install --global "pnpm@$required_pnpm_version"
fi

python_dependency_state=$(digest_files "$project_dir/backend/pyproject.toml")
if state_matches python-deps.sha256 "$python_dependency_state" \
  && "$conda_bin" run -n "$conda_env" python -c \
    'import fastapi, mcp, psycopg, uvicorn; import app' >/dev/null 2>&1
then
  echo "      Python 后端依赖未变化，跳过"
else
  "$conda_bin" run --no-capture-output -n "$conda_env" \
    python -m pip install -e "$project_dir/backend"
  record_state python-deps.sha256 "$python_dependency_state"
fi

echo "[4/6] 检查 DeepSeek Harness 构建"
harness_source_state=$(
  {
    git -C "$harness_dir" rev-parse HEAD
    git -C "$harness_dir" diff --binary
    git -C "$harness_dir" diff --cached --binary
  } | sha256sum | awk '{print $1}'
)
if state_matches harness-build.revision "$harness_source_state" \
  && [ -d "$harness_dir/node_modules" ] \
  && [ -f "$harness_dir/apps/cli/lib/bin.js" ] \
  && [ -f "$harness_dir/apps/web/dist/index.html" ]
then
  echo "      Harness 源码未变化且构建产物完整，跳过"
else
  (
    cd "$harness_dir"
    "$conda_bin" run --no-capture-output -n "$conda_env" \
      pnpm install --frozen-lockfile
    "$conda_bin" run --no-capture-output -n "$conda_env" pnpm run build
  )
  record_state harness-build.revision "$harness_source_state"
fi

echo "[5/6] 检查 Harness 插件"
plugin_profile_dir="$runtime_dir/dsh-home/profiles/web"
mkdir -p "$plugin_profile_dir"
plugin_profile_state=$(digest_files \
  "$plugin_profile_dir/package.json" \
  "$plugin_profile_dir/pnpm-lock.yaml" \
  "$plugin_profile_dir/pnpm-workspace.yaml")
chmod +x "$harness_dir/apps/cli/lib/bin.js"
ln -sf "$harness_dir/apps/cli/lib/bin.js" /usr/local/bin/dsh

dsh --version
if state_matches plugin-profile.sha256 "$plugin_profile_state" \
  && [ -d "$plugin_profile_dir/node_modules" ]
then
  echo "      插件清单未变化且依赖存在，跳过"
else
  (
    cd "$harness_dir"
    DSH_HOME="$runtime_dir/dsh-home" \
      "$conda_bin" run --no-capture-output -n "$conda_env" \
      pnpm dsh plugin --profile web install --no-frozen-lockfile
  )
  plugin_profile_state=$(digest_files \
    "$plugin_profile_dir/package.json" \
    "$plugin_profile_dir/pnpm-lock.yaml" \
    "$plugin_profile_dir/pnpm-workspace.yaml")
  record_state plugin-profile.sha256 "$plugin_profile_state"
fi

echo "[6/6] 执行离线自检"
chmod +x "$project_dir"/*.sh "$project_dir/backend/start.sh" "$project_dir/harness/start.sh"
sh "$project_dir/tests/server_scripts_check.sh"
sh "$project_dir/tests/deploy_state_check.sh"
(
  cd "$project_dir/backend"
  "$conda_bin" run --no-capture-output -n "$conda_env" python tests/self_check.py
)

if [ "${DEPARTMENT_SKIP_START:-0}" = "1" ]; then
  echo "部署完成。已按 DEPARTMENT_SKIP_START=1 跳过启动。"
else
  echo "部署完成，正在后台启动服务。"
  "$project_dir/start-background.sh"
fi
