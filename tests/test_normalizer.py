"""Tests for citation_v2.normalizer module."""

import unicodedata

import pytest

from citation_v2.normalizer import (
    normalize_text,
)


@pytest.mark.unit
class TestNormalizeText:
    def test_type_error_on_non_string(self):
        with pytest.raises(TypeError, match="must be a string"):
            normalize_text(123)

    def test_empty_string_returns_empty(self):
        assert normalize_text("") == ""

    def test_nfc_normalization(self):
        text = "cafe\u0301"
        result = normalize_text(text)
        assert unicodedata.normalize("NFC", "cafe\u0301") == result
        assert "\u0301" not in result

    def test_crlf_normalized_to_lf(self):
        assert normalize_text("a\r\nb") == "a\nb"

    def test_cr_normalized_to_lf(self):
        assert normalize_text("a\rb") == "a\nb"

    def test_form_feed_normalized_to_lf(self):
        assert normalize_text("a\x0cb") == "a\nb"

    def test_nbsp_replaced_with_space(self):
        result = normalize_text("hello\u00a0world")
        assert "\u00a0" not in result
        assert " " in result

    def test_figure_space_replaced(self):
        result = normalize_text("value\u2007100")
        assert "\u2007" not in result

    def test_narrow_nobreak_space_replaced(self):
        result = normalize_text("a\u202fb")
        assert "\u202f" not in result

    def test_control_chars_removed(self):
        result = normalize_text("a\x00\x01b\x02")
        assert result == "ab"

    def test_newlines_preserved(self):
        assert normalize_text("a\nb\nc") == "a\nb\nc"

    def test_tabs_converted_to_spaces(self):
        assert normalize_text("a\tb") == "a b"

    def test_trailing_whitespace_stripped_per_line(self):
        assert normalize_text("hello \n  world  ") == "hello\nworld"

    def test_multiple_spaces_collapsed(self):
        assert normalize_text("a   b") == "a b"

    def test_three_plus_newlines_collapsed_to_two(self):
        assert normalize_text("a\n\n\n\n\nb") == "a\n\nb"

    def test_two_newlines_preserved(self):
        assert normalize_text("a\n\nb") == "a\n\nb"

    def test_document_boundaries_trimmed(self):
        assert normalize_text("  hello  ") == "hello"

    def test_no_dehyphenation(self):
        result = normalize_text("mod-\nern")
        assert "-\n" in result

    def test_case_preserved(self):
        result = normalize_text("Hello WORLD")
        assert result == "Hello WORLD"

    def test_numbers_preserved(self):
        result = normalize_text("The value is 42.5 and 10%")
        assert "42.5" in result
        assert "10%" in result

    def test_unicode_punctuation_preserved(self):
        result = normalize_text("x = y + z")
        assert result == "x = y + z"

    def test_whitespace_only_lines_kept(self):
        result = normalize_text("\n\nhello\n\n")
        assert result == "hello"

    def test_mixed_whitespace_handling(self):
        result = normalize_text("  a  \n  b  \n  c  ")
        assert result == "a\nb\nc"
