#!/bin/sh
# Start (default) or stop the local PostgreSQL in the OSS Scanner image.
# Usage: .oss-scanner/start-db.sh [start|stop]
#   start  start the cluster and wait until it accepts connections (the default)
#   stop   stop the cluster
set -e
VERSION="$(ls /etc/postgresql)"
case "${1:-start}" in
  start)
    pg_ctlcluster "$VERSION" main start || true
    until pg_isready -h localhost -U postgres -q; do sleep 1; done
    ;;
  stop)
    pg_ctlcluster "$VERSION" main stop
    ;;
esac
