#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck disable=SC1091
. "$project_dir/server-common.sh"

mkdir -p "$log_dir"
touch "$log_file"
exec tail -n "${DEPARTMENT_LOG_LINES:-100}" -f "$log_file"
