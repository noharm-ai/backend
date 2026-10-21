#!/bin/sh
# Entrypoint of the OSS Scanner image: PostgreSQL only runs during the build steps, so start it again
# whenever a container starts, then run the given command.
set -e
/src/.oss-scanner/start-db.sh
exec "$@"
