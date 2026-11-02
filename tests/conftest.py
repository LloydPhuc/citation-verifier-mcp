"""
Shared test fixtures and configuration.

Sets up isolated filesystem and database paths BEFORE any
citation_v2 modules are imported, ensuring tests never touch
the real project database or cache.
"""

import gc
import os
import tempfile
from pathlib import Path

import pytest

# Never inherit production paths. One disposable home per test process, removed
# on exit; no fixed shared directory or stale database across repeated runs.
_runtime = tempfile.TemporaryDirectory(prefix="citation-tests-")
_TEST_HOME = Path(_runtime.name).resolve()
os.environ["CITATION_MCP_HOME"] = str(_TEST_HOME)
os.environ["CITATION_MCP_DB_PATH"] = str(_TEST_HOME / "data" / "tests.db")


def pytest_unconfigure(config):
    # Release SQLite cursor cycles before Windows removes the disposable home.
    gc.collect()
    _runtime.cleanup()


@pytest.fixture
def db_conn():
    """Provide a raw SQLite connection to the isolated test DB."""
    from citation_v2.database import (
        get_connection,
        initialize_database,
    )

    initialize_database()
    conn = get_connection()
    yield conn
    conn.close()


@pytest.fixture
def clean_db():
    """Initialize the schema and yield a connection."""
    from citation_v2.database import (
        get_connection,
        initialize_database,
    )

    initialize_database()
    conn = get_connection()
    yield conn
    conn.close()
