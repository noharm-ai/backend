"""Pytest plugin for the OSS Scanner image: start the local PostgreSQL before the tests run.

The scanner runs its own image built on top of ours with the entrypoint reset, so the database is not running
when a container starts. The image enables this plugin through PYTEST_PLUGINS.
"""

import subprocess


def pytest_load_initial_conftests(early_config, parser, args):  # noqa: ARG001
    """Start PostgreSQL if it is not accepting connections yet (before tests/conftest.py, which connects on import)."""
    ready = subprocess.run(
        ["pg_isready", "-h", "localhost", "-U", "postgres", "-q"], check=False
    )
    if ready.returncode != 0:
        subprocess.run(["/src/.oss-scanner/start-db.sh"], check=True)
