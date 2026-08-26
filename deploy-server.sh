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
echo "[1/7] 使用当前 DeepSeek Harness：$current_harness_revision"
echo "      项目最后验证版本：$expected_harness_version（仅作兼容性提示，不自动切换版本）"

echo "[2/7] 清理不能跨平台复用的本机环境和插件依赖"
rm -rf \
  "$project_dir/backend/.venv" \
  "$runtime_dir/dsh-home/profiles/node_modules" \
  "$runtime_dir/dsh-home/profiles/web/node_modules"
find "$project_dir" -name .DS_Store -type f -delete

if "$conda_bin" env list | awk -v name="$conda_env" '$1 == name { found=1 } END { exit !found }'; then
  echo "[3/7] 复用已有 Conda 环境：$conda_env"
else
  echo "[3/7] 创建独立 Conda 环境：$conda_env"
  "$conda_bin" create -y -n "$conda_env" -c conda-forge python=3.11 nodejs=24
fi

echo "[4/7] 安装固定版本 pnpm 和 Python 后端"
"$conda_bin" run -n "$conda_env" npm install --global pnpm@11.7.0
"$conda_bin" run -n "$conda_env" python -m pip install -e "$project_dir/backend"

echo "[5/7] 安装并构建 DeepSeek Harness"
(
  cd "$harness_dir"
  "$conda_bin" run -n "$conda_env" pnpm install --frozen-lockfile
  "$conda_bin" run -n "$conda_env" pnpm run build
)

echo "[6/7] 按 Linux x86_64 重新安装 Harness 插件"
mkdir -p "$runtime_dir/dsh-home/profiles/web"
(
  cd "$harness_dir"
  DSH_HOME="$runtime_dir/dsh-home" \
    "$conda_bin" run -n "$conda_env" \
    pnpm dsh plugin --profile web install --frozen-lockfile
)

echo "[7/7] 执行离线自检"
chmod +x "$project_dir"/*.sh "$project_dir/backend/start.sh" "$project_dir/harness/start.sh"
sh "$project_dir/tests/server_scripts_check.sh"
(
  cd "$project_dir/backend"
  "$conda_bin" run -n "$conda_env" python tests/self_check.py
)

if [ "${DEPARTMENT_SKIP_START:-0}" = "1" ]; then
  echo "部署完成。已按 DEPARTMENT_SKIP_START=1 跳过启动。"
else
  echo "部署完成，正在后台启动服务。"
  "$project_dir/start-background.sh"
fi
