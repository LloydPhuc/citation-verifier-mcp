"""Tests for citation_v2.nli module (label resolution and validation)."""

import pytest

from citation_v2.nli import (
    NLIError,
    NLIInputError,
    NLIInputTooLongError,
    NLIModelError,
    NLIResult,
    _normalize_label,
    _resolve_label_indices,
    _validate_text,
)


@pytest.mark.unit
class TestNormalizeLabel:
    def test_basic(self):
        assert _normalize_label("entailment") == "entailment"

    def test_with_hyphens(self):
        assert _normalize_label(
            "non-entailment"
        ) == "non_entailment"

    def test_with_spaces(self):
        assert _normalize_label(
            "not entailment"
        ) == "not_entailment"

    def test_uppercase(self):
        assert _normalize_label(
            "Entailment"
        ) == "entailment"

    def test_stripped(self):
        assert _normalize_label("  entailment  ") == (
            "entailment"
        )


@pytest.mark.unit
class TestResolveLabelIndices:
    def test_standard_labels(self):
        id2label = {
            "0": "contradiction",
            "1": "entailment",
            "2": "neutral",
        }
        result = _resolve_label_indices(id2label)
        assert result == {
            "contradiction": 0,
            "entailment": 1,
            "neutral": 2,
        }

    def test_labels_with_hyphens(self):
        id2label = {
            "0": "contradiction",
            "1": "entailment",
            "2": "neutral",
        }
        result = _resolve_label_indices(id2label)
        assert len(result) == 3

    def test_missing_label_raises(self):
        id2label = {
            "0": "contradiction",
            "1": "entailment",
        }
        with pytest.raises(
            NLIModelError, match="Unable to resolve"
        ):
            _resolve_label_indices(id2label)

    def test_duplicate_label_raises(self):
        id2label = {
            "0": "entailment",
            "1": "entailment",
            "2": "neutral",
        }
        with pytest.raises(
            NLIModelError, match="Duplicate"
        ):
            _resolve_label_indices(id2label)

    def test_non_integer_key_skipped(self):
        id2label = {
            "0": "contradiction",
            "1": "entailment",
            "2": "neutral",
            "not_index": "extra",
        }
        result = _resolve_label_indices(id2label)
        assert len(result) == 3

    def test_indices_must_be_distinct(self):
        id2label = {
            "0": "contradiction",
            "00": "entailment",
            "2": "neutral",
        }
        with pytest.raises(
            NLIModelError, match="distinct"
        ):
            _resolve_label_indices(id2label)


@pytest.mark.unit
class TestValidateText:
    def test_valid_text(self):
        assert _validate_text("hello", name="test") == "hello"

    def test_non_string_raises(self):
        with pytest.raises(
            NLIInputError, match="must be a string"
        ):
            _validate_text(123, name="test")

    def test_empty_raises(self):
        with pytest.raises(
            NLIInputError, match="cannot be empty"
        ):
            _validate_text("", name="test")

    def test_whitespace_raises(self):
        with pytest.raises(
            NLIInputError, match="cannot be empty"
        ):
            _validate_text("   ", name="test")

    def test_stripped(self):
        assert _validate_text(
            "  hello  ", name="test"
        ) == "hello"


@pytest.mark.unit
class TestNLIResult:
    def test_confidence_is_max(self):
        result = NLIResult(
            contradiction=0.1,
            entailment=0.8,
            neutral=0.1,
            predicted_label="entailment",
            premise_truncated=False,
            model_id="test/model",
        )
        assert result.confidence == 0.8

    def test_to_dict_includes_confidence(self):
        result = NLIResult(
            contradiction=0.1,
            entailment=0.8,
            neutral=0.1,
            predicted_label="entailment",
            premise_truncated=False,
            model_id="test/model",
        )
        d = result.to_dict()
        assert d["confidence"] == 0.8
        assert d["entailment"] == 0.8
        assert d["model_id"] == "test/model"


@pytest.mark.unit
class TestNLIErrorHierarchy:
    def test_nli_input_too_long_is_input_error(self):
        assert issubclass(
            NLIInputTooLongError, NLIInputError
        )
        assert issubclass(NLIInputError, NLIError)

    def test_nli_model_error_is_nli_error(self):
        assert issubclass(NLIModelError, NLIError)

    def test_nli_input_error_is_nli_error(self):
        assert issubclass(NLIInputError, NLIError)

    def test_all_are_runtime_errors(self):
        assert issubclass(NLIError, RuntimeError)
