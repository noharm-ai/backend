#!/bin/sh
# Start (default) or stop the local PostgreSQL in the OSS Scanner image.
# Usage: .oss-scanner/start-db.sh [start|stop]
#   start  start the cluster and wait until it accepts connections (the default; harmless if already up)
#   stop   stop the cluster
set -e
VERSION="$(ls /etc/postgresql)"
case "${1:-start}" in
  start)
    pg_ctlcluster "$VERSION" main start || true
    tries=0
    until pg_isready -h localhost -U postgres -q; do
      tries=$((tries + 1))
      if [ "$tries" -ge 30 ]; then
        echo "PostgreSQL did not accept connections after 30s" >&2
        tail -n 50 "/var/log/postgresql/postgresql-$VERSION-main.log" >&2 || true
        exit 1
      fi
      sleep 1
    done
    ;;
  stop)
    pg_ctlcluster "$VERSION" main stop
    ;;
esac
