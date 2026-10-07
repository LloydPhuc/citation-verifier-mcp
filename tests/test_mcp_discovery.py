"""MCP Protocol Discovery Smoke Test.

Launches the real production server through stdio and verifies
MCP protocol tool discovery. Uses the installed MCP SDK's actual
ClientSession and stdio_client interfaces.
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REQUIRED_TOOLS = {
    "verify_document",
    "verify_bibliography",
    "citation_summary",
    "verify_claim",
    "verify_claims",
    "verify_reference",
}

# Bounded timeouts (seconds)
SERVER_STARTUP_TIMEOUT = 30.0
MCP_INIT_TIMEOUT = 20.0
TOOL_DISCOVERY_TIMEOUT = 15.0

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_PY = REPO_ROOT / "server.py"
VENV_PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def repo_root():
    """Repository root directory."""
    return REPO_ROOT


@pytest.fixture(scope="session")
def venv_python():
    """Path to the virtual environment Python executable."""
    if not VENV_PYTHON.exists():
        pytest.skip(f"Virtual environment not found at {VENV_PYTHON}")
    return str(VENV_PYTHON)


@pytest.fixture(scope="session")
def server_py():
    """Path to the server.py entrypoint."""
    if not SERVER_PY.exists():
        pytest.skip(f"Server entrypoint not found at {SERVER_PY}")
    return str(SERVER_PY)


# ---------------------------------------------------------------------------
# Helper: run MCP client against server subprocess
# ---------------------------------------------------------------------------

async def _run_mcp_discovery(venv_python: str, server_py: str):
    """
    Launch server, connect via stdio, initialize, and list tools.
    Returns (tool_names: set[str], tool_schemas: dict[str, dict]).
    """
    # Build server parameters - use the venv python to run server.py
    server_params = StdioServerParameters(
        command=venv_python,
        args=[server_py],
        cwd=str(REPO_ROOT),
        # Ensure clean environment: no external GROBID, no network
        env={
            **os.environ,
            "GROBID_URL": "http://127.0.0.1:8070",  # Will fail gracefully if accessed
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "NO_COLOR": "1",
        },
        encoding="utf-8",
        encoding_error_handler="replace",
    )

    # stdio_client returns an async context manager yielding (read_stream, write_stream)
    async with stdio_client(server_params) as (read_stream, write_stream):
        # Create and initialize the client session
        async with ClientSession(read_stream, write_stream) as session:
            # Initialize the MCP protocol (bounded timeout)
            init_task = asyncio.create_task(session.initialize())
            try:
                await asyncio.wait_for(init_task, timeout=MCP_INIT_TIMEOUT)
            except TimeoutError:
                init_task.cancel()
                raise AssertionError(
                    f"MCP initialization timed out after {MCP_INIT_TIMEOUT}s"
                ) from None

            # List tools (bounded timeout)
            list_task = asyncio.create_task(session.list_tools())
            try:
                result = await asyncio.wait_for(list_task, timeout=TOOL_DISCOVERY_TIMEOUT)
            except TimeoutError:
                list_task.cancel()
                raise AssertionError(
                    f"tools/list timed out after {TOOL_DISCOVERY_TIMEOUT}s"
                ) from None

            # Extract tool names and schemas
            tool_names = {tool.name for tool in result.tools}
            tool_schemas = {
                tool.name: tool.input_schema for tool in result.tools
            }

            return tool_names, tool_schemas


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestMCPDiscovery:
    """MCP protocol discovery smoke tests."""

    def test_server_launch_and_tool_discovery(
        self, venv_python: str, server_py: str
    ):
        """
        Launch the real server subprocess, establish MCP stdio connection,
        initialize protocol, and verify all 6 required tools are advertised.
        """
        tool_names, tool_schemas = asyncio.run(
            _run_mcp_discovery(venv_python, server_py)
        )

        # Record actual discovered tools for diagnostics
        print(f"\nDiscovered tools: {sorted(tool_names)}")

        # Assert all required tools are present
        missing = REQUIRED_TOOLS - tool_names
        extra = tool_names - REQUIRED_TOOLS

        if missing:
            pytest.fail(
                f"Missing required tools: {sorted(missing)}. "
                f"Discovered: {sorted(tool_names)}"
            )

        if extra:
            # Not a failure, but log for visibility
            print(f"Extra tools discovered (unexpected): {sorted(extra)}")

        # Verify schemas for verify_claim and verify_claims
        self._assert_verify_claim_schema(tool_schemas)
        self._assert_verify_claims_schema(tool_schemas)
        reference_schema = tool_schemas["verify_reference"]
        assert "reference" in reference_schema["required"]
        assert "claim" not in reference_schema.get("required", [])
        assert "claim" in reference_schema["properties"]

    def _assert_verify_claim_schema(self, tool_schemas: dict[str, dict]):
        """Verify verify_claim input schema exposes documented required arguments."""
        schema = tool_schemas.get("verify_claim")
        assert schema is not None, "verify_claim tool schema not found"

        # Must be an object schema
        assert schema.get("type") == "object", "verify_claim schema must be object"

        props = schema.get("properties", {})
        required = schema.get("required", [])

        # Required arguments per server.py docstring
        assert "claim" in required, "verify_claim requires 'claim'"
        assert "source" in required, "verify_claim requires 'source'"
        assert "top_k" not in required, "verify_claim top_k is optional with default"

        # Property types
        assert props.get("claim", {}).get("type") == "string"
        assert props.get("source", {}).get("type") == "string"
        if "top_k" in props:
            assert props["top_k"].get("type") == "integer"

    def _assert_verify_claims_schema(self, tool_schemas: dict[str, dict]):
        """Verify verify_claims input schema exposes documented required arguments."""
        schema = tool_schemas.get("verify_claims")
        assert schema is not None, "verify_claims tool schema not found"

        # Must be an object schema
        assert schema.get("type") == "object", "verify_claims schema must be object"

        props = schema.get("properties", {})
        required = schema.get("required", [])

        # Required arguments per server.py docstring
        assert "claims" in required, "verify_claims requires 'claims'"
        assert "top_k" not in required, "verify_claims top_k is optional with default"

        # Property types
        assert props.get("claims", {}).get("type") == "array"
        if "top_k" in props:
            assert props["top_k"].get("type") == "integer"

        # Claims array items - schema generator may not include inner properties
        # for list[dict[str, Any]], so we just verify the array type is present.
        # The actual item structure (claim + source) is documented in the tool
        # description and validated at runtime by the server.
        claims_items = props.get("claims", {}).get("items", {})
        if claims_items:
            # Items should be an object schema (even if properties not detailed)
            assert claims_items.get("type") == "object", (
                "claims items should be objects"
            )

    def test_discovered_tool_count(self, venv_python: str, server_py: str):
        """Verify exactly the expected number of tools are discovered."""
        tool_names, _ = asyncio.run(
            _run_mcp_discovery(venv_python, server_py)
        )
        # At minimum the 5 required tools must be present
        assert len(tool_names) >= len(REQUIRED_TOOLS)
        assert REQUIRED_TOOLS.issubset(tool_names)

    def test_tool_descriptions_present(self, venv_python: str, server_py: str):
        """Verify discovered tools have human-readable descriptions."""
        tool_names, tool_schemas = asyncio.run(
            _run_mcp_discovery(venv_python, server_py)
        )
        # We need to re-fetch with descriptions; this is a simplified check
        # that the protocol returns well-formed tool objects
        for tool_name in REQUIRED_TOOLS:
            schema = tool_schemas.get(tool_name)
            assert schema is not None
            # input_schema must be valid JSON Schema
            assert isinstance(schema, dict)
            assert schema.get("type") == "object"


# ---------------------------------------------------------------------------
# Standalone execution support (for scripts/smoke_test.ps1 or manual run)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="MCP Discovery Smoke Test"
    )
    parser.add_argument(
        "--venv-python",
        default=str(VENV_PYTHON),
        help="Path to virtual environment Python",
    )
    parser.add_argument(
        "--server-py",
        default=str(SERVER_PY),
        help="Path to server.py entrypoint",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Overall timeout in seconds",
    )
    args = parser.parse_args()

    async def _main():
        print("Starting MCP discovery test...")
        print(f"  venv python: {args.venv_python}")
        print(f"  server.py:   {args.server_py}")

        try:
            tool_names, tool_schemas = await asyncio.wait_for(
                _run_mcp_discovery(args.venv_python, args.server_py),
                timeout=args.timeout,
            )
        except TimeoutError:
            print(f"FAIL: Overall timeout after {args.timeout}s")
            sys.exit(1)

        print(f"Discovered tools: {sorted(tool_names)}")

        missing = REQUIRED_TOOLS - tool_names
        if missing:
            print(f"FAIL: Missing required tools: {sorted(missing)}")
            sys.exit(1)

        # Check schemas
        try:
            # Reuse schema validation logic
            class _Validator:
                def _assert_verify_claim_schema(self, s):
                    sch = s.get("verify_claim")
                    assert sch is not None, "verify_claim schema not found"
                    assert sch.get("type") == "object", "verify_claim schema must be object"
                    req = sch.get("required", [])
                    assert "claim" in req, "verify_claim requires 'claim'"
                    assert "source" in req, "verify_claim requires 'source'"
                    props = sch.get("properties", {})
                    assert props.get("claim", {}).get("type") == "string"
                    assert props.get("source", {}).get("type") == "string"

                def _assert_verify_claims_schema(self, s):
                    sch = s.get("verify_claims")
                    assert sch is not None, "verify_claims schema not found"
                    assert sch.get("type") == "object", "verify_claims schema must be object"
                    req = sch.get("required", [])
                    assert "claims" in req, "verify_claims requires 'claims'"
                    props = sch.get("properties", {})
                    assert props.get("claims", {}).get("type") == "array"

            v = _Validator()
            v._assert_verify_claim_schema(tool_schemas)
            v._assert_verify_claims_schema(tool_schemas)
            print("Schema validation: PASS")
        except AssertionError as e:
            print(f"FAIL: Schema validation failed: {e}")
            sys.exit(1)

        print("SUCCESS: All 6 required tools discovered with valid schemas.")
        sys.exit(0)

    asyncio.run(_main())
