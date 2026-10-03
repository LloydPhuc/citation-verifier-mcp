"""
Shared test fixtures and configuration.

Sets up isolated filesystem and database paths BEFORE any
citation_v2 modules are imported, ensuring tests never touch
the real project database or cache.
"""

import os
import tempfile
from pathlib import Path

import pytest

# Use a writable temp directory for pytest basetemp
_basetemp = Path(tempfile.gettempdir()) / "citation_pytest_basetemp"
_basetemp.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("PYTEST_BASETEMP", str(_basetemp))

_TEST_HOME = Path(tempfile.gettempdir()) / "citation_mcp_test_env"
_TEST_HOME.mkdir(parents=True, exist_ok=True)

os.environ.setdefault(
    "CITATION_MCP_HOME", str(_TEST_HOME)
)
os.environ.setdefault(
    "CITATION_MCP_DB_PATH",
    str(_TEST_HOME / "data" / "tests.db"),
)


_BASETEMP = Path(tempfile.gettempdir()) / "citation_pytest_basetemp"
_BASETEMP.mkdir(parents=True, exist_ok=True)


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
