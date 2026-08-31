#!/bin/sh
set -eu
script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
printf '%s\n' "$script_dir/../../.local/DerivedData"
