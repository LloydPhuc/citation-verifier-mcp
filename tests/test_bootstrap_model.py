"""Exercise bootstrap model diagnostics without installing or downloading anything."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BOOTSTRAP = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap.ps1"
POWERSHELL = shutil.which("powershell.exe")
pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(
        sys.platform != "win32" or POWERSHELL is None,
        reason="Bootstrap targets Windows PowerShell",
    ),
]


@pytest.mark.parametrize("scenario", ["cached", "downloaded", "download_error", "import_error"])
def test_model_preparation_guidance(tmp_path: Path, scenario: str) -> None:
    source = BOOTSTRAP.read_text(encoding="utf-8")
    helpers = source.split("# ---------- Helper Functions ----------", 1)[1].split(
        "# ---------- [1/7] Checking Python ----------", 1
    )[0]
    model_stage = source.split("# ---------- [5/7] Preparing NLI model ----------", 1)[1].split(
        "# ---------- [6/7] Checking application imports ----------", 1
    )[0]
    # Run the actual readiness summary, without executing other installation stages.
    summary = source.split("if ($NLIModelReady) {", 1)[1].split('Write-Host "  No API keys', 1)[0]
    summary = "if ($NLIModelReady) {" + summary

    fake_module = tmp_path / "transformers.py"
    fake_module.write_text(
        """import os
scenario = os.environ['MODEL_TEST_SCENARIO']
if scenario == 'import_error':
    raise ImportError('synthetic missing dependency')

class FakeLoader:
    @classmethod
    def from_pretrained(cls, model_id, **kwargs):
        cached = kwargs.get('local_files_only', False)
        with open(os.environ['MODEL_TEST_CALLS'], 'a') as calls:
            calls.write(f'{cls.__name__}:{cached}\\n')
        if scenario != 'cached' and cached:
            raise OSError('synthetic cache miss')
        if scenario == 'download_error':
            raise OSError('synthetic download failure')
        return object()

class AutoTokenizer(FakeLoader):
    pass

class AutoModelForSequenceClassification(FakeLoader):
    pass
""",
        encoding="utf-8",
    )
    interpreter = sys.executable.replace("'", "''")
    runner = tmp_path / "model-stage.ps1"
    runner.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        + f"$VenvPython = '{interpreter}'\n"
        + "$NLIModelId = 'cross-encoder/nli-deberta-v3-small'\n"
        + helpers
        + model_stage
        + summary,
        encoding="utf-8-sig",
    )
    calls_file = tmp_path / "calls.txt"
    env = {
        **os.environ,
        "PYTHONPATH": str(tmp_path),
        "MODEL_TEST_SCENARIO": scenario,
        "MODEL_TEST_CALLS": str(calls_file),
        "HF_HUB_OFFLINE": "1",
    }
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(runner)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "downloaded on first" not in output
    if scenario in {"cached", "downloaded"}:
        assert "is cached locally" in output
        assert "V2 verification is not ready" not in output
        assert "runtime does not download" not in output
    else:
        assert "runtime does not download" in output
        assert "rerun .\\scripts\\bootstrap.ps1" in output
        assert "V2 verification is not ready" in output
        assert "is cached locally" not in output

    calls = calls_file.read_text(encoding="utf-8").splitlines() if calls_file.exists() else []
    expected_calls = {
        "cached": ["AutoTokenizer:True", "AutoModelForSequenceClassification:True"],
        "downloaded": [
            "AutoTokenizer:True",
            "AutoTokenizer:False",
            "AutoModelForSequenceClassification:False",
        ],
        "download_error": ["AutoTokenizer:True", "AutoTokenizer:False"],
        "import_error": [],
    }
    assert calls == expected_calls[scenario]
