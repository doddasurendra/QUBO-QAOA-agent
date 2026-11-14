#!/usr/bin/env bash
# Each case runs in a fresh process. Prints OK / CRASH per case. Diagnostic only; always exits 0.
# The API fixture works outside pytest; find which pytest mechanism makes Qiskit segfault on the Linux runner.
cd "$(dirname "$0")/../../backend" || exit 1
python -c "import pytest, anyio, starlette, fastapi; print('pytest', pytest.__version__, 'anyio', anyio.__version__, 'starlette', starlette.__version__, 'fastapi', fastapi.__version__)"
run() {
  local name="$1"; shift
  if timeout 600 python -X faulthandler -m pytest -x -v -p no:randomly "$@" tests/test_api.py >/tmp/case.log 2>&1; then echo "OK     $name"
  else echo "CRASH  $name (exit $?)"; grep -E '^tests/.*(PASSED|FAILED|ERROR)' /tmp/case.log | tail -n 1 | sed 's/^/         last finished: /'; grep -m2 'File ' /tmp/case.log | sed 's/^/         /'; fi
}
run "default"
run "-s (no output capture)"          -s
run "--capture=sys"                   --capture=sys
run "-p no:faulthandler"              -p no:faulthandler
run "--assert=plain"                  --assert=plain
run "-s -p no:faulthandler"           -s -p no:faulthandler
exit 0
