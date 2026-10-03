"""Tests for citation_v2.cache module (hashing, safe filenames, atomic writes, cache delete)."""

import hashlib

import pytest

from citation_v2.cache import (
    _atomic_write_bytes,
    _atomic_write_text,
    delete_cache_file,
    load_normalized_text,
    normalized_text_path,
    raw_cache_path,
    safe_filename,
    save_binary_file,
    save_normalized_text,
    save_raw_file,
    save_source_file,
    sha256_file,
    sha256_text,
    source_cache_path,
    temp_cache_path,
)
from citation_v2.config import (
    CACHE_DIR,
    RAW_CACHE_DIR,
    SOURCE_CACHE_DIR,
    TEMP_CACHE_DIR,
    TEXT_CACHE_DIR,
)

KNOWN_HASH = hashlib.sha256(b"hello world").hexdigest()

VALID_HASH = hashlib.sha256(b"test content").hexdigest()


@pytest.mark.unit
class TestSha256Text:
    def test_known_hash(self):
        assert sha256_text("hello world") == KNOWN_HASH

    def test_deterministic(self):
        assert sha256_text("abc") == sha256_text("abc")

    def test_different_inputs_different_hashes(self):
        assert sha256_text("abc") != sha256_text("abd")

    def test_empty_string(self):
        assert sha256_text("") == hashlib.sha256(b"").hexdigest()

    def test_type_error_on_non_string(self):
        with pytest.raises(TypeError, match="must be a string"):
            sha256_text(123)

    def test_type_error_on_none(self):
        with pytest.raises(TypeError, match="must be a string"):
            sha256_text(None)

    def test_type_error_on_bytes(self):
        with pytest.raises(TypeError, match="must be a string"):
            sha256_text(b"hello")

    def test_unicode_text(self):
        text = "héllo wörld"
        assert sha256_text(text) == hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.mark.unit
class TestSha256File:
    def test_known_hash(self, tmp_path):
        p = tmp_path / "file.txt"
        p.write_bytes(b"hello world")
        assert sha256_file(p) == KNOWN_HASH

    def test_deterministic(self, tmp_path):
        p = tmp_path / "file.txt"
        p.write_bytes(b"abc")
        assert sha256_file(p) == sha256_file(p)

    def test_large_file_chunked(self, tmp_path):
        p = tmp_path / "large.bin"
        data = b"x" * (1024 * 1024 * 3)
        p.write_bytes(data)
        expected = hashlib.sha256(data).hexdigest()
        assert sha256_file(p, chunk_size=1024 * 1024) == expected

    def test_custom_chunk_size(self, tmp_path):
        p = tmp_path / "file.txt"
        p.write_bytes(b"hello world")
        assert sha256_file(p, chunk_size=4) == KNOWN_HASH

    def test_chunk_size_must_be_positive(self, tmp_path):
        p = tmp_path / "file.txt"
        p.write_bytes(b"hello")
        with pytest.raises(ValueError, match="chunk_size must be > 0"):
            sha256_file(p, chunk_size=0)

    def test_chunk_size_negative_raises(self, tmp_path):
        p = tmp_path / "file.txt"
        p.write_bytes(b"hello")
        with pytest.raises(ValueError, match="chunk_size must be > 0"):
            sha256_file(p, chunk_size=-1)

    def test_nonexistent_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            sha256_file(tmp_path / "nonexistent.txt")

    def test_directory_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Expected a file"):
            sha256_file(tmp_path)

    def test_accepts_string_path(self, tmp_path):
        p = tmp_path / "file.txt"
        p.write_bytes(b"hello world")
        assert sha256_file(str(p)) == KNOWN_HASH

    def test_accepts_path_object(self, tmp_path):
        p = tmp_path / "file.txt"
        p.write_bytes(b"hello world")
        assert sha256_file(p) == KNOWN_HASH

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.txt"
        p.write_bytes(b"")
        assert sha256_file(p) == hashlib.sha256(b"").hexdigest()


@pytest.mark.unit
class TestSafeFilename:
    def test_simple_filename(self):
        assert safe_filename("document.pdf") == "document.pdf"

    def test_strips_whitespace(self):
        assert safe_filename("  file.txt  ") == "file.txt"

    def test_windows_path_reduces_to_basename(self):
        assert safe_filename("C:\\Users\\admin\\file.txt") == "file.txt"

    def test_posix_path_reduces_to_basename(self):
        assert safe_filename("/home/user/file.txt") == "file.txt"

    def test_relative_path_traversal(self):
        assert safe_filename("../../secret.txt") == "secret.txt"

    def test_backslash_traversal(self):
        assert safe_filename("..\\..\\secret.txt") == "secret.txt"

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            safe_filename("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            safe_filename("   ")

    def test_dot_raises(self):
        with pytest.raises(ValueError, match="Invalid filename"):
            safe_filename(".")

    def test_double_dot_raises(self):
        with pytest.raises(ValueError, match="Invalid filename"):
            safe_filename("..")

    def test_dot_after_strip_raises(self):
        with pytest.raises(ValueError, match="Invalid filename"):
            safe_filename("  ..  ")

    def test_type_error_on_non_string(self):
        with pytest.raises(TypeError, match="must be a string"):
            safe_filename(123)

    def test_type_error_on_none(self):
        with pytest.raises(TypeError, match="must be a string"):
            safe_filename(None)

    def test_mixed_separators(self):
        result = safe_filename("C:\\Users/admin\\file.txt")
        assert result == "file.txt"

    def test_filename_with_spaces(self):
        result = safe_filename("my document.pdf")
        assert result == "my document.pdf"

    def test_trailing_slash_raises(self):
        with pytest.raises(ValueError, match="Invalid filename"):
            safe_filename("path/")

    def test_deeply_nested_path(self):
        assert safe_filename("a/b/c/d/file.txt") == "file.txt"

    def test_windows_drive_letter_stripped(self):
        result = safe_filename("C:/Windows/system32/config/file.txt")
        assert result == "file.txt"


@pytest.mark.unit
class TestNormalizedTextPath:
    def test_valid_hash_returns_path(self):
        path = normalized_text_path(VALID_HASH)
        assert path == TEXT_CACHE_DIR / f"{VALID_HASH}.txt"

    def test_uppercase_hash_normalized(self):
        upper_hash = VALID_HASH.upper()
        path = normalized_text_path(upper_hash)
        assert path == TEXT_CACHE_DIR / f"{VALID_HASH}.txt"

    def test_hash_stripped(self):
        padded_hash = f"  {VALID_HASH}  "
        path = normalized_text_path(padded_hash)
        assert path == TEXT_CACHE_DIR / f"{VALID_HASH}.txt"

    def test_short_hash_raises(self):
        with pytest.raises(ValueError, match="64-character"):
            normalized_text_path("abc123")

    def test_long_hash_raises(self):
        with pytest.raises(ValueError, match="64-character"):
            normalized_text_path("a" * 65)

    def test_non_hex_chars_raises(self):
        bad_hash = "g" + "a" * 63
        with pytest.raises(ValueError, match="64-character"):
            normalized_text_path(bad_hash)

    def test_uppercase_hex_accepted(self):
        upper_hash = VALID_HASH.upper()
        path = normalized_text_path(upper_hash)
        assert path.name == VALID_HASH + ".txt"

    def test_empty_hash_raises(self):
        with pytest.raises(ValueError, match="64-character"):
            normalized_text_path("")


@pytest.mark.unit
class TestAtomicWriteBytes:
    def test_creates_destination_directory(self, tmp_path):
        dest = tmp_path / "subdir" / "deeper" / "file.bin"
        _atomic_write_bytes(dest, b"hello")
        assert dest.read_bytes() == b"hello"

    def test_overwrites_existing(self, tmp_path):
        dest = tmp_path / "file.bin"
        dest.write_bytes(b"old")
        _atomic_write_bytes(dest, b"new")
        assert dest.read_bytes() == b"new"

    def test_no_temp_file_left_behind(self, tmp_path):
        dest = tmp_path / "file.bin"
        _atomic_write_bytes(dest, b"hello")
        temp_files = [
            f for f in dest.parent.iterdir()
            if f.name.startswith("." + dest.name + ".")
        ]
        assert len(temp_files) == 0

    def test_empty_bytes(self, tmp_path):
        dest = tmp_path / "file.bin"
        _atomic_write_bytes(dest, b"")
        assert dest.read_bytes() == b""

    def test_large_bytes(self, tmp_path):
        dest = tmp_path / "file.bin"
        data = b"x" * 10000
        _atomic_write_bytes(dest, data)
        assert dest.read_bytes() == data

    def test_unicode_bytes(self, tmp_path):
        dest = tmp_path / "file.bin"
        text = "héllo wörld".encode()
        _atomic_write_bytes(dest, text)
        assert dest.read_bytes() == text


@pytest.mark.unit
class TestAtomicWriteText:
    def test_writes_text_utf8(self, tmp_path):
        dest = tmp_path / "file.txt"
        _atomic_write_text(dest, "hello world")
        assert dest.read_text(encoding="utf-8") == "hello world"

    def test_unicode_text(self, tmp_path):
        dest = tmp_path / "file.txt"
        text = "héllo wörld 你好"
        _atomic_write_text(dest, text)
        assert dest.read_text(encoding="utf-8") == text

    def test_overwrites_existing(self, tmp_path):
        dest = tmp_path / "file.txt"
        dest.write_text("old", encoding="utf-8")
        _atomic_write_text(dest, "new")
        assert dest.read_text(encoding="utf-8") == "new"

    def test_empty_string(self, tmp_path):
        dest = tmp_path / "file.txt"
        _atomic_write_text(dest, "")
        assert dest.read_text(encoding="utf-8") == ""


@pytest.mark.unit
class TestSaveNormalizedText:
    def test_saves_and_returns_hash_and_path(self):
        text = "sample text content"
        content_hash, path = save_normalized_text(text)
        expected_hash = sha256_text(text)
        assert content_hash == expected_hash
        assert path == TEXT_CACHE_DIR / f"{expected_hash}.txt"
        assert path.exists()
        assert path.read_text(encoding="utf-8") == text

    def test_idempotent_same_text(self):
        text = "same text"
        hash1, path1 = save_normalized_text(text)
        hash2, path2 = save_normalized_text(text)
        assert hash1 == hash2
        assert path1 == path2
        assert path2.exists()

    def test_corrupted_file_replaced(self):
        text = "correct text"
        content_hash, path = save_normalized_text(text)
        path.write_bytes(b"corrupted data")
        hash2, path2 = save_normalized_text(text)
        assert hash2 == content_hash
        assert path2 == path
        assert path2.read_text(encoding="utf-8") == text

    def test_type_error_on_non_string(self):
        with pytest.raises(TypeError, match="must be a string"):
            save_normalized_text(123)

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="Refusing to cache empty text"):
            save_normalized_text("")

    def test_different_text_different_paths(self):
        h1, p1 = save_normalized_text("text one")
        h2, p2 = save_normalized_text("text two")
        assert h1 != h2
        assert p1 != p2
        assert p1.exists()
        assert p2.exists()

    def test_creates_text_cache_directory(self):
        TEXT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        save_normalized_text("test content for dir")
        assert TEXT_CACHE_DIR.exists()

    def test_unicode_content(self):
        text = "héllo wörld 你好世界"
        content_hash, path = save_normalized_text(text)
        assert path.read_text(encoding="utf-8") == text
        assert sha256_text(text) == content_hash


@pytest.mark.unit
class TestLoadNormalizedText:
    def test_loads_saved_text(self):
        text = "loadable content"
        content_hash, path = save_normalized_text(text)
        loaded = load_normalized_text(content_hash)
        assert loaded == text

    def test_missing_file_returns_none(self):
        missing_hash = hashlib.sha256(b"not cached").hexdigest()
        result = load_normalized_text(missing_hash)
        assert result is None

    def test_corrupted_content_raises(self):
        text = "original text"
        content_hash, path = save_normalized_text(text)
        path.write_bytes(b"corrupted data that won't decompress properly")
        with pytest.raises(RuntimeError, match="cache corruption"):
            load_normalized_text(content_hash)

    def test_corruption_detects_different_hash(self):
        text = "my text"
        content_hash, path = save_normalized_text(text)
        path.write_bytes(b"different content")
        with pytest.raises(RuntimeError, match="cache corruption"):
            load_normalized_text(content_hash)

    def test_uppercase_hash_works(self):
        text = "uppercase test"
        content_hash, path = save_normalized_text(text)
        upper_hash = content_hash.upper()
        loaded = load_normalized_text(upper_hash)
        assert loaded == text

    def test_roundtrip_consistency(self):
        text = "roundtrip test content"
        content_hash = sha256_text(text)
        save_normalized_text(text)
        loaded = load_normalized_text(content_hash)
        assert loaded == text

    def test_corruption_detected_by_hash_mismatch(self):
        text = "integrity check"
        content_hash, path = save_normalized_text(text)
        path.write_bytes(b"tampered content")
        with pytest.raises(RuntimeError, match="cache corruption"):
            load_normalized_text(content_hash)


@pytest.mark.unit
class TestSaveBinaryFile:
    def test_saves_bytes(self, tmp_path):
        dest = tmp_path / "file.bin"
        data = b"\x00\x01\x02\x03"
        result = save_binary_file(dest, data)
        assert result == dest
        assert dest.read_bytes() == data

    def test_type_error_on_string(self, tmp_path):
        dest = tmp_path / "file.bin"
        with pytest.raises(TypeError, match="must be bytes"):
            save_binary_file(dest, "not bytes")

    def test_type_error_on_none(self, tmp_path):
        dest = tmp_path / "file.bin"
        with pytest.raises(TypeError, match="must be bytes"):
            save_binary_file(dest, None)

    def test_empty_data_raises(self, tmp_path):
        dest = tmp_path / "file.bin"
        with pytest.raises(ValueError, match="empty file"):
            save_binary_file(dest, b"")

    def test_bytearray_accepted(self, tmp_path):
        dest = tmp_path / "file.bin"
        data = bytearray(b"hello")
        save_binary_file(dest, data)
        assert dest.read_bytes() == b"hello"

    def test_creates_parent_directory(self, tmp_path):
        dest = tmp_path / "subdir" / "file.bin"
        data = b"test"
        save_binary_file(dest, data)
        assert dest.read_bytes() == data

    def test_overwrites_existing(self, tmp_path):
        dest = tmp_path / "file.bin"
        dest.write_bytes(b"old")
        save_binary_file(dest, b"new")
        assert dest.read_bytes() == b"new"


@pytest.mark.unit
class TestSaveRawFile:
    def test_saves_to_raw_cache(self):
        filename = "test_raw.pdf"
        data = b"%PDF-1.4 test content"
        path = save_raw_file(filename, data)
        assert path == raw_cache_path(filename)
        assert path.exists()
        assert path.read_bytes() == data

    def test_path_traversal_sanitized(self):
        filename = "../../evil.txt"
        data = b"evil"
        path = save_raw_file(filename, data)
        assert path.parent == RAW_CACHE_DIR
        assert path.name == "evil.txt"


@pytest.mark.unit
class TestSaveSourceFile:
    def test_saves_to_source_cache(self):
        filename = "source.pdf"
        data = b"%PDF-1.4 source content"
        path = save_source_file(filename, data)
        assert path == source_cache_path(filename)
        assert path.exists()
        assert path.read_bytes() == data

    def test_path_traversal_sanitized(self):
        filename = "..\\..\\evil.bin"
        data = b"evil"
        path = save_source_file(filename, data)
        assert path.parent == SOURCE_CACHE_DIR
        assert path.name == "evil.bin"


@pytest.mark.unit
class TestCachePathHelpers:
    def test_raw_cache_path(self):
        path = raw_cache_path("doc.pdf")
        assert path == RAW_CACHE_DIR / "doc.pdf"

    def test_source_cache_path(self):
        path = source_cache_path("doc.pdf")
        assert path == SOURCE_CACHE_DIR / "doc.pdf"

    def test_temp_cache_path(self):
        path = temp_cache_path("temp.txt")
        assert path == TEMP_CACHE_DIR / "temp.txt"

    def test_raw_cache_sanitizes_path(self):
        path = raw_cache_path("a/b/doc.pdf")
        assert path == RAW_CACHE_DIR / "doc.pdf"

    def test_source_cache_sanitizes_path(self):
        path = source_cache_path("..\\..\\doc.pdf")
        assert path == SOURCE_CACHE_DIR / "doc.pdf"

    def test_temp_cache_sanitizes_path(self):
        path = temp_cache_path("/etc/passwd")
        assert path == TEMP_CACHE_DIR / "passwd"


@pytest.mark.unit
class TestDeleteCacheFile:
    def test_deletes_existing_file(self):
        text = "deletable content"
        content_hash, path = save_normalized_text(text)
        assert path.exists()
        result = delete_cache_file(path)
        assert result is True
        assert not path.exists()

    def test_missing_file_returns_false(self):
        path = TEXT_CACHE_DIR / "nonexistent.txt"
        result = delete_cache_file(path)
        assert result is False

    def test_path_traversal_prevented(self):
        outside = CACHE_DIR.parent / "outside.txt"
        outside.write_bytes(b"do not delete me")
        with pytest.raises(ValueError, match="outside the cache directory"):
            delete_cache_file(outside)
        assert outside.exists()

    def test_path_traversal_prevented_with_file_outside(self, tmp_path):
        outside_file = tmp_path / "outside.txt"
        outside_file.write_text("secret")
        with pytest.raises(ValueError, match="outside the cache directory"):
            delete_cache_file(outside_file)
        assert outside_file.exists()

    def test_directory_raises(self):
        with pytest.raises(ValueError, match="non-file"):
            delete_cache_file(CACHE_DIR)

    def test_deletes_raw_cache_file(self):
        path = save_raw_file("todelete.pdf", b"data")
        assert path.exists()
        result = delete_cache_file(path)
        assert result is True
        assert not path.exists()

    def test_double_delete_returns_false(self):
        text = "double delete"
        _, path = save_normalized_text(text)
        assert delete_cache_file(path) is True
        assert delete_cache_file(path) is False

    def test_accepts_string_path(self):
        text = "string path delete"
        _, path = save_normalized_text(text)
        result = delete_cache_file(str(path))
        assert result is True
        assert not path.exists()

    def test_non_existent_link_returns_false(self):
        link = CACHE_DIR / "nonexistent_link.txt"
        assert delete_cache_file(link) is False
