#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck disable=SC1091
. "$project_dir/server-common.sh"

service_pid=$(read_owned_pid || true)
if [ -z "$service_pid" ]; then
  echo "没有找到本脚本管理的后台进程。"
  exit 0
fi

if ! kill -0 "$service_pid" 2>/dev/null; then
  rm -f "$pid_file"
  echo "后台进程已退出，已清理旧 PID 文件。"
  exit 0
fi

/bin/kill -TERM -- "-$service_pid" 2>/dev/null || kill -TERM "$service_pid" 2>/dev/null || true

attempt=0
while [ "$attempt" -lt 20 ] && kill -0 "$service_pid" 2>/dev/null; do
  attempt=$((attempt + 1))
  sleep 1
done

if kill -0 "$service_pid" 2>/dev/null; then
  /bin/kill -KILL -- "-$service_pid" 2>/dev/null || kill -KILL "$service_pid" 2>/dev/null || true
fi

rm -f "$pid_file"
echo "部门 AI 已停止。"
