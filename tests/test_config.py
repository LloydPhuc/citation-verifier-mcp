"""Tests for citation_v2.config module."""

import os
import tempfile
from pathlib import Path

import pytest

from citation_v2 import config


@pytest.mark.unit
class TestEnvStr:
    def test_default_returned_when_unset(self, monkeypatch):
        monkeypatch.delenv("MY_TEST_STR", raising=False)
        assert config._env_str("MY_TEST_STR", "default") == "default"

    def test_value_returned_when_set(self, monkeypatch):
        monkeypatch.setenv("MY_TEST_STR", "custom")
        assert config._env_str("MY_TEST_STR", "default") == "custom"

    def test_empty_string_returns_default(self, monkeypatch):
        monkeypatch.setenv("MY_TEST_STR", "   ")
        assert config._env_str("MY_TEST_STR", "default") == "default"

    def test_strip_applied(self, monkeypatch):
        monkeypatch.setenv("MY_TEST_STR", "  padded  ")
        assert config._env_str("MY_TEST_STR", "x") == "padded"


@pytest.mark.unit
class TestEnvInt:
    def test_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("MY_TEST_INT", raising=False)
        assert config._env_int("MY_TEST_INT", 42) == 42

    def test_value_returned(self, monkeypatch):
        monkeypatch.setenv("MY_TEST_INT", "7")
        assert config._env_int("MY_TEST_INT", 42) == 7

    def test_invalid_raises_runtime_error(self, monkeypatch):
        monkeypatch.setenv("MY_TEST_INT", "abc")
        with pytest.raises(RuntimeError, match="must be an integer"):
            config._env_int("MY_TEST_INT", 42)

    def test_empty_returns_default(self, monkeypatch):
        monkeypatch.setenv("MY_TEST_INT", "  ")
        assert config._env_int("MY_TEST_INT", 42) == 42

    def test_minimum_enforced(self, monkeypatch):
        monkeypatch.setenv("MY_TEST_INT", "3")
        with pytest.raises(RuntimeError, match="must be >="):
            config._env_int("MY_TEST_INT", 10, minimum=5)

    def test_minimum_boundary_ok(self, monkeypatch):
        monkeypatch.setenv("MY_TEST_INT", "5")
        assert config._env_int("MY_TEST_INT", 10, minimum=5) == 5


@pytest.mark.unit
class TestEnvFloat:
    def test_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("MY_TEST_FLOAT", raising=False)
        assert config._env_float("MY_TEST_FLOAT", 1.5) == 1.5

    def test_value_returned(self, monkeypatch):
        monkeypatch.setenv("MY_TEST_FLOAT", "2.5")
        assert config._env_float("MY_TEST_FLOAT", 1.5) == 2.5

    def test_invalid_raises_runtime_error(self):
        os.environ["MY_TEST_FLOAT_BAD"] = "xyz"
        try:
            with pytest.raises(RuntimeError, match="must be numeric"):
                config._env_float("MY_TEST_FLOAT_BAD", 1.5)
        finally:
            os.environ.pop("MY_TEST_FLOAT_BAD", None)

    def test_maximum_enforced(self, monkeypatch):
        monkeypatch.setenv("MY_TEST_FLOAT", "10.0")
        with pytest.raises(RuntimeError, match="must be <="):
            config._env_float("MY_TEST_FLOAT", 1.0, maximum=5.0)

    def test_range_boundary_ok(self, monkeypatch):
        monkeypatch.setenv("MY_TEST_FLOAT", "5.0")
        assert config._env_float("MY_TEST_FLOAT", 1.0, maximum=5.0) == 5.0


@pytest.mark.unit
class TestDefaults:
    def test_pipeline_version(self):
        assert config.PIPELINE_VERSION == "2.1.0"

    def test_nli_entailment_threshold(self):
        assert config.NLI_ENTAILMENT_THRESHOLD == 0.70

    def test_nli_contradiction_threshold(self):
        assert config.NLI_CONTRADICTION_THRESHOLD == 0.70

    def test_bm25_top_k(self):
        assert config.BM25_TOP_K == 5

    def test_chunk_target_chars(self):
        assert config.CHUNK_TARGET_CHARS == 4000

    def test_chunk_overlap_chars(self):
        assert config.CHUNK_OVERLAP_CHARS == 600

    def test_nli_model_id(self):
        assert config.NLI_MODEL_ID == (
            "cross-encoder/nli-deberta-v3-small"
        )

    def test_http_user_agent(self):
        assert "CitationMCP" in config.HTTP_USER_AGENT

    def test_required_directories_includes_all(self):
        for d in config.REQUIRED_DIRECTORIES:
            assert d is not None


@pytest.mark.unit
class TestPathResolution:
    def test_base_dir_under_test_home(self):
        assert config.BASE_DIR == _TEST_HOME

    def test_db_path_under_test_home(self):
        assert str(config.DB_PATH).startswith(
            str(_TEST_HOME)
        )

    def test_cache_dir_under_test_home(self):
        assert config.CACHE_DIR == _TEST_HOME / "cache"

    def test_raw_cache_dir(self):
        assert (
            config.RAW_CACHE_DIR
            == _TEST_HOME / "cache" / "raw"
        )

    def test_text_cache_dir(self):
        assert (
            config.TEXT_CACHE_DIR
            == _TEST_HOME / "cache" / "text"
        )

    def test_source_cache_dir(self):
        assert (
            config.SOURCE_CACHE_DIR
            == _TEST_HOME / "cache" / "source"
        )

    def test_temp_cache_dir(self):
        assert (
            config.TEMP_CACHE_DIR
            == _TEST_HOME / "cache" / "temp"
        )


@pytest.mark.unit
class TestValidateConfig:
    def test_validate_passes(self):
        config.validate_config()

    def test_overlap_must_be_smaller_than_target(self, monkeypatch):
        original = config.CHUNK_OVERLAP_CHARS
        try:
            monkeypatch.setattr(
                config,
                "CHUNK_OVERLAP_CHARS",
                5000,
            )
            with pytest.raises(
                RuntimeError,
                match="CHUNK_OVERLAP_CHARS must be smaller",
            ):
                config.validate_config()
        finally:
            monkeypatch.setattr(
                config,
                "CHUNK_OVERLAP_CHARS",
                original,
            )

    def test_empty_nli_model_id_raises(self, monkeypatch):
        monkeypatch.setattr(
            config, "NLI_MODEL_ID", "  "
        )
        with pytest.raises(
            RuntimeError, match="NLI_MODEL_ID cannot be empty"
        ):
            config.validate_config()

    def test_grobid_url_must_have_scheme(self, monkeypatch):
        monkeypatch.setattr(
            config, "GROBID_URL", "ftp://invalid"
        )
        with pytest.raises(
            RuntimeError, match="must use http or https"
        ):
            config.validate_config()


@pytest.mark.unit
class TestInitializeRuntimePaths:
    def test_creates_directories(self):
        config.initialize_runtime_paths()
        for d in config.REQUIRED_DIRECTORIES:
            assert d.exists()
            assert d.is_dir()

    def test_ensure_directories_raises_on_file(self, monkeypatch):
        blocking_file = _TEST_HOME / "blocking_file"
        blocking_file.write_text("not a dir")

        monkeypatch.setattr(
            config,
            "REQUIRED_DIRECTORIES",
            (blocking_file,),
        )

        with pytest.raises(
            RuntimeError, match="not a directory"
        ):
            config.ensure_directories()


@pytest.mark.unit
class TestRuntimeSummary:
    def test_summary_contains_expected_keys(self):
        summary = config.runtime_summary()
        assert summary["pipeline_version"] == "2.1.0"
        assert "base_dir" in summary
        assert "database" in summary
        assert "cache_dir" in summary
        assert "grobid_url" in summary
        assert "bm25_top_k" in summary
        assert "nli_model" in summary
        assert "nli_entailment_threshold" in summary


# Resolve the actual test home path set by conftest.py
_TEST_HOME = Path(
    os.environ.get(
        "CITATION_MCP_HOME",
        os.path.join(
            tempfile.gettempdir(),
            "citation_mcp_test_env",
        ),
    )
)
