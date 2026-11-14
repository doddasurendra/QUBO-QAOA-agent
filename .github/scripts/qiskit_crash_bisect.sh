#!/usr/bin/env bash
# Diagnostic only; always exits 0. Native (gdb) backtrace of the Qiskit segfault under pytest on the Linux runner.
cd "$(dirname "$0")/../../backend" || exit 1
command -v gdb >/dev/null || { sudo apt-get update -qq >/dev/null 2>&1; sudo apt-get install -y -qq gdb 2>&1 | tail -n 3; }
echo "GDB| gdb: $(command -v gdb || echo MISSING)"
for n in 1 2 3 4 5 6; do
  gdb -q -batch -ex "set pagination off" -ex "set disable-randomization off" -ex "handle SIGPIPE nostop noprint" \
    -ex run -ex "bt 40" -ex "info registers rip rsp" -ex "x/6i \$pc" \
    --args python -m pytest -x -q -p no:faulthandler tests/test_api.py -k bootstrap_only >/tmp/gdb.log 2>&1
  if grep -q "SIGSEGV" /tmp/gdb.log; then echo "GDB| crashed on attempt $n"
    grep -vE '^\[(New|Thread .* exited)|^\[Inferior|libthread_db|Using host' /tmp/gdb.log | grep -A70 SIGSEGV | sed 's/^/GDB| /'; break
  else echo "GDB| attempt $n: no crash"; fi
done
exit 0
