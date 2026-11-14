#!/usr/bin/env bash
# Each case runs in a fresh process. Prints OK / CRASH per case. Diagnostic only; always exits 0.
# Question: does Qiskit segfault when it is first imported in a non-main thread, and does threading.stack_size matter?
cd "$(dirname "$0")/../../backend" || exit 1
run() {
  local name="$1"; shift
  if timeout 300 python -X faulthandler -c "$1" >/tmp/case.log 2>&1; then echo "OK     $name"; else echo "CRASH  $name (exit $?)"; grep -m3 'File ' /tmp/case.log | sed 's/^/         /'; fi
}
QC='from qiskit import QuantumCircuit; QuantumCircuit(2)'
T='import threading; t=threading.Thread(target=lambda: exec(QC)); t.start(); t.join()'
run "import in main, use in worker"           "QC='$QC'; exec(QC); $T"
run "first import in worker"                   "QC='$QC'; $T"
run "first import in worker, stack 16 MB"      "import threading; threading.stack_size(16*1024*1024); QC='$QC'; $T"
run "import in main, worker with stack 16 MB"  "import threading; threading.stack_size(16*1024*1024); QC='$QC'; exec(QC); $T"
exit 0
