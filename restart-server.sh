#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
"$project_dir/stop-server.sh"
"$project_dir/start-background.sh"
