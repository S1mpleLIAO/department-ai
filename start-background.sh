#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck disable=SC1091
. "$project_dir/server-common.sh"

mkdir -p "$pid_dir" "$log_dir"

old_pid=$(read_owned_pid || true)
if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
  echo "部门 AI 已在后台运行，PID: $old_pid"
  exit 0
fi
rm -f "$pid_file"

if is_ready "http://127.0.0.1:3080/" || is_ready "http://127.0.0.1:3081/health"; then
  echo "检测到 3080 或 3081 端口已有服务，但它不是本脚本管理的进程。" >&2
  echo "请先停止原服务，再执行 ./start-background.sh。" >&2
  exit 1
fi

if ! command -v setsid >/dev/null 2>&1; then
  echo "缺少 setsid（Ubuntu 通常由 util-linux 提供）。" >&2
  exit 1
fi

nohup setsid "$project_dir/start-server.sh" >>"$log_file" 2>&1 &
service_pid=$!
printf '%s\n' "$service_pid" >"$pid_file"

attempt=0
while [ "$attempt" -lt 90 ]; do
  if ! kill -0 "$service_pid" 2>/dev/null; then
    echo "启动失败，最近日志：" >&2
    tail -n 60 "$log_file" >&2 || true
    rm -f "$pid_file"
    exit 1
  fi
  if is_ready "http://127.0.0.1:3080/" && is_ready "http://127.0.0.1:3081/health"; then
    echo "部门 AI 已后台启动，PID: $service_pid"
    echo "管理页面：http://127.0.0.1:3081/department"
    echo "AI 助手：http://127.0.0.1:3080/"
    echo "日志：$log_file"
    exit 0
  fi
  attempt=$((attempt + 1))
  sleep 1
done

echo "服务启动超时，最近日志：" >&2
tail -n 60 "$log_file" >&2 || true
exit 1
