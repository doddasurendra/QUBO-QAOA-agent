#!/bin/sh
# Container entrypoint. Mounted volumes (Fly.io, Docker named volumes) are often owned by root, while the app runs
# as the unprivileged "qopt" user. When started as root: make the data directory writable for qopt, then drop
# privileges for the actual process. When already started as qopt: just run the command.
set -e
DATA_DIR="${QOPT_DATA_DIR:-/app/data}"
if [ "$(id -u)" = "0" ]; then
  mkdir -p "$DATA_DIR"
  chown -R qopt:qopt "$DATA_DIR"
  exec setpriv --reuid=qopt --regid=qopt --init-groups "$@"
fi
exec "$@"
