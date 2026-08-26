#!/bin/sh
set -eu

root_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python_pid=
harness_pid=

is_ready() {
  curl --fail --silent --output /dev/null "$1" 2>/dev/null
}

stop_started_services() {
  trap - INT TERM EXIT

  if [ -n "$harness_pid" ]; then
    kill "$harness_pid" 2>/dev/null || true
  fi
  if [ -n "$python_pid" ]; then
    kill "$python_pid" 2>/dev/null || true
  fi

  if [ -n "$harness_pid" ]; then
    wait "$harness_pid" 2>/dev/null || true
  fi
  if [ -n "$python_pid" ]; then
    wait "$python_pid" 2>/dev/null || true
  fi
}

wait_until_ready() {
  url=$1
  name=$2
  pid=$3
  attempts=0

  while [ "$attempts" -lt 60 ]; do
    if is_ready "$url"; then
      echo "$name 已就绪"
      return 0
    fi

    if ! kill -0 "$pid" 2>/dev/null; then
      wait "$pid" 2>/dev/null || true
      echo "$name 启动失败，请查看上方日志。" >&2
      exit 1
    fi

    attempts=$((attempts + 1))
    sleep 1
  done

  echo "$name 启动超时，请查看上方日志。" >&2
  exit 1
}

trap stop_started_services INT TERM EXIT

if is_ready "http://127.0.0.1:3081/health"; then
  echo "Python 管理服务已在运行"
else
  echo "正在启动 Python 管理服务..."
  "$root_dir/backend/start.sh" &
  python_pid=$!
  wait_until_ready "http://127.0.0.1:3081/health" "Python 管理服务" "$python_pid"
fi

if is_ready "http://127.0.0.1:3080/"; then
  echo "DeepSeek Harness 已在运行"
else
  echo "正在启动 DeepSeek Harness..."
  "$root_dir/harness/start.sh" &
  harness_pid=$!
  wait_until_ready "http://127.0.0.1:3080/" "DeepSeek Harness" "$harness_pid"
fi

echo ""
echo "项目已启动："
echo "  管理页面  http://127.0.0.1:3081/department"
echo "  AI 助手   http://127.0.0.1:3080/"

if [ -z "$python_pid$harness_pid" ]; then
  echo "两个服务原本就已运行，本脚本未重复启动。"
  trap - INT TERM EXIT
  exit 0
fi

echo "按 Ctrl+C 停止本脚本启动的服务。"

while :; do
  if [ -n "$python_pid" ] && ! kill -0 "$python_pid" 2>/dev/null; then
    echo "Python 管理服务已退出。" >&2
    exit 1
  fi
  if [ -n "$harness_pid" ] && ! kill -0 "$harness_pid" 2>/dev/null; then
    echo "DeepSeek Harness 已退出。" >&2
    exit 1
  fi
  sleep 1
done
