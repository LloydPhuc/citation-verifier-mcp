"""Cleanup is restricted to generated files, with a working dry-run."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(sys.platform != "win32", reason="PowerShell script"),
]


@pytest.fixture
def project(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "clean.ps1"
    (tmp_path / "scripts").mkdir()
    shutil.copyfile(script, tmp_path / "scripts" / "clean.ps1")
    for name in [".pytest_cache", "citation_v2/__pycache__", "cache/raw", "data", ".venv", "tests"]:
        folder = tmp_path / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "keep-or-remove.txt").write_text("sentinel")
    return tmp_path


def run_clean(project, *args, home=None):
    env = os.environ.copy()
    env.pop("CITATION_MCP_HOME", None)
    if home:
        env["CITATION_MCP_HOME"] = str(home)
    return subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(project / "scripts" / "clean.ps1"),
            *args,
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_whatif_does_not_remove_files(project):
    before = {p.relative_to(project) for p in project.rglob("*")}
    result = run_clean(project, "-RuntimeCache", "-WhatIf")
    assert result.returncode == 0, result.stderr
    assert {p.relative_to(project) for p in project.rglob("*")} == before


def test_only_generated_files_are_removed(project):
    result = run_clean(project)
    assert result.returncode == 0, result.stderr
    assert not (project / ".pytest_cache").exists()
    assert not (project / "citation_v2/__pycache__").exists()
    for name in ["cache/raw", "data", ".venv", "tests"]:
        assert (project / name / "keep-or-remove.txt").is_file()
    result = run_clean(project, "-RuntimeCache")
    assert result.returncode == 0, result.stderr
    assert not (project / "cache").exists()
    assert (project / "data/keep-or-remove.txt").is_file()


def test_custom_runtime_rejected_before_any_deletion(project, tmp_path):
    before = {p.relative_to(project) for p in project.rglob("*")}
    result = run_clean(project, "-RuntimeCache", home=tmp_path / "external")
    assert result.returncode != 0
    assert "Custom CITATION_MCP_HOME" in result.stderr
    assert {p.relative_to(project) for p in project.rglob("*")} == before


def test_ancestor_junction_rejected_before_any_deletion(project, tmp_path):
    # The junction sits above __pycache__, so checking only the leaf is insufficient.
    original = project / "citation_v2"
    external = tmp_path / "external"
    original.rename(external)
    command = "New-Item -ItemType Junction -Path $args[0] -Target $args[1] | Out-Null"
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command, str(original), str(external)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    try:
        result = run_clean(project)
        assert result.returncode != 0
        assert "linked path" in result.stderr
        assert (project / ".pytest_cache/keep-or-remove.txt").is_file()
        assert (external / "__pycache__/keep-or-remove.txt").is_file()
    finally:
        os.rmdir(original)  # Remove the fixture junction, leaving its target intact.
