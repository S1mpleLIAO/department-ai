#!/bin/sh
set -eu

test_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
temporary_dir=$(mktemp -d)
trap 'rm -rf "$temporary_dir"' EXIT INT TERM

DEPARTMENT_RUNTIME_DIR="$temporary_dir/runtime"
export DEPARTMENT_RUNTIME_DIR

# shellcheck disable=SC1091
. "$test_dir/../server-common.sh"

if state_matches example abc; then
  echo "missing state must not match" >&2
  exit 1
fi

record_state example abc
state_matches example abc

if state_matches example def; then
  echo "changed state must not match" >&2
  exit 1
fi

test "$(cat "$deploy_state_dir/example")" = "abc"
echo "deploy state checks passed"
