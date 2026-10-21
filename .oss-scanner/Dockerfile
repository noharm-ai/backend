# Build image for Anthropic's OSS Scanner (https://github.com/anthropics/oss-scanner).
# The scanner builds this with the repository as the build context, then runs the audit with no network,
# so everything the app and its tests need (Python packages, PostgreSQL and the noharm-ai/database schema
# and seed data) is fetched and loaded here.
FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates git curl postgresql postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies before copying the source so the layer is cached across source changes.
COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

# scanner contract: the checkout lives inside the image, at /src
COPY . /src
WORKDIR /src

# Local-only settings, the same as CI (see .github/workflows/build.yml). No production credentials or
# AWS access are needed; tests that call AWS stub it.
ENV ENV=test \
    SECRET_KEY=oss-scanner-local-only-not-a-production-secret \
    POTGRESQL_CONNECTION_STRING=postgresql://postgres@localhost/noharm \
    REPORT_CONNECTION_STRING=postgresql://postgres@localhost/noharm \
    TEST_DATABASE_URL=postgresql://postgres@localhost/noharm \
    AWS_DEFAULT_REGION=sa-east-1

# The schema and seed data live in a separate repository; fetch it now, while the network is available.
RUN git clone --depth 1 https://github.com/noharm-ai/database /opt/noharm-database

# Trust local connections (as docker-compose.test.yml does), create the database and load it.
RUN chmod +x /src/.oss-scanner/start-db.sh \
    && PG_HBA="$(ls /etc/postgresql/*/main/pg_hba.conf)" \
    && printf 'local all all trust\nhost all all 127.0.0.1/32 trust\nhost all all ::1/128 trust\n' > "$PG_HBA" \
    && /src/.oss-scanner/start-db.sh \
    && psql -U postgres -h localhost -c "CREATE DATABASE noharm" \
    && for f in noharm-public noharm-create noharm-newuser noharm-triggers noharm-insert noharm-create-regulation; do \
         psql -U postgres -h localhost -d noharm -q -v ON_ERROR_STOP=1 -f "/opt/noharm-database/$f.sql" > /dev/null || exit 1; \
       done \
    && /src/.oss-scanner/start-db.sh stop

# Run the tests so the build log shows the image works, but do not let a failing test abort the build.
RUN ruff check . || echo "WARNING: ruff reported problems"
RUN /src/.oss-scanner/start-db.sh \
    && (python -m pytest -q -p no:cacheprovider || echo "WARNING: pytest reported failures") \
    && /src/.oss-scanner/start-db.sh stop

# PostgreSQL does not survive past the RUN that started it; start it in every container, before the command.
RUN chmod +x /src/.oss-scanner/entrypoint.sh
ENTRYPOINT ["/src/.oss-scanner/entrypoint.sh"]
CMD ["sleep", "infinity"]
