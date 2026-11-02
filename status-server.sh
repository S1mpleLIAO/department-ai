#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck disable=SC1091
. "$project_dir/server-common.sh"

service_pid=$(read_owned_pid || true)
if [ -n "$service_pid" ] && kill -0 "$service_pid" 2>/dev/null; then
  echo "后台进程：运行中（PID: $service_pid）"
else
  echo "后台进程：未运行"
fi

failed=0
if is_ready "http://127.0.0.1:3081/health"; then
  echo "Python 管理服务：正常（127.0.0.1:3081）"
else
  echo "Python 管理服务：不可用"
  failed=1
fi

if is_harness_ready "http://127.0.0.1:3080/"; then
  echo "DeepSeek Harness：正常（127.0.0.1:3080）"
else
  echo "DeepSeek Harness：不可用"
  failed=1
fi

echo "日志：$log_file"
exit "$failed"
