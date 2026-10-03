from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from .config import (
    CACHE_DIR,
    RAW_CACHE_DIR,
    TEXT_CACHE_DIR,
    SOURCE_CACHE_DIR,
    TEMP_CACHE_DIR,
    initialize_runtime_paths,
)


# ============================================================
# Hashing
# ============================================================

def sha256_text(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError("text must be a string.")

    return hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()


def sha256_file(
    path: str | Path,
    *,
    chunk_size: int = 1024 * 1024,
) -> str:
    path = Path(path)

    if chunk_size <= 0:
        raise ValueError(
            "chunk_size must be > 0."
        )

    if not path.exists():
        raise FileNotFoundError(path)

    if not path.is_file():
        raise ValueError(
            f"Expected a file, got: {path}"
        )

    digest = hashlib.sha256()

    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)

            if not chunk:
                break

            digest.update(chunk)

    return digest.hexdigest()


# ============================================================
# Safe filenames
# ============================================================

def safe_filename(filename: str) -> str:
    """
    Reduce user/source-provided names to a basename only.

    Prevents paths such as:
        ../../secret.txt
        C:\\Windows\\file
    from escaping the cache directory.
    """

    if not isinstance(filename, str):
        raise TypeError(
            "filename must be a string."
        )

    filename = filename.strip()

    if not filename:
        raise ValueError(
            "filename cannot be empty."
        )

    # Handle both Windows and POSIX separators.
    filename = filename.replace("\\", "/")
    filename = filename.rsplit("/", 1)[-1]

    if filename in {"", ".", ".."}:
        raise ValueError(
            "Invalid filename."
        )

    return filename


# ============================================================
# Cache path helpers
# ============================================================

def raw_cache_path(
    filename: str,
) -> Path:
    initialize_runtime_paths()

    return RAW_CACHE_DIR / safe_filename(
        filename
    )


def source_cache_path(
    filename: str,
) -> Path:
    initialize_runtime_paths()

    return SOURCE_CACHE_DIR / safe_filename(
        filename
    )


def temp_cache_path(
    filename: str,
) -> Path:
    initialize_runtime_paths()

    return TEMP_CACHE_DIR / safe_filename(
        filename
    )


def normalized_text_path(
    content_hash: str,
) -> Path:
    initialize_runtime_paths()

    content_hash = content_hash.strip().lower()

    if (
        len(content_hash) != 64
        or any(
            char not in "0123456789abcdef"
            for char in content_hash
        )
    ):
        raise ValueError(
            "content_hash must be a 64-character "
            "SHA-256 hexadecimal string."
        )

    return TEXT_CACHE_DIR / (
        f"{content_hash}.txt"
    )


# ============================================================
# Atomic writing
# ============================================================

def _atomic_write_bytes(
    destination: Path,
    data: bytes,
) -> None:
    """
    Write bytes atomically.

    Data is first written to a temporary file in the
    destination directory and then replaced atomically.

    This prevents half-written cache files if the process
    crashes during a write.
    """

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )

    temporary_path = Path(
        temporary_name
    )

    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(
            temporary_path,
            destination,
        )

    except Exception:
        try:
            temporary_path.unlink(
                missing_ok=True
            )
        except OSError:
            pass

        raise


def _atomic_write_text(
    destination: Path,
    text: str,
) -> None:

    _atomic_write_bytes(
        destination,
        text.encode("utf-8"),
    )


# ============================================================
# Normalized text cache
# ============================================================

def save_normalized_text(
    text: str,
) -> tuple[str, Path]:
    """
    Persist normalized source text by content hash.

    Identical text maps to the same cache file.
    """

    if not isinstance(text, str):
        raise TypeError(
            "text must be a string."
        )

    if not text:
        raise ValueError(
            "Refusing to cache empty text."
        )

    content_hash = sha256_text(text)

    destination = normalized_text_path(
        content_hash
    )

    if destination.exists():

        existing_hash = sha256_file(
            destination
        )

        if existing_hash == content_hash:
            return (
                content_hash,
                destination,
            )

        # A file at a content-addressed path that does
        # not match its name is corruption. Replace it.
        _atomic_write_text(
            destination,
            text,
        )

        return (
            content_hash,
            destination,
        )

    _atomic_write_text(
        destination,
        text,
    )

    return (
        content_hash,
        destination,
    )


def load_normalized_text(
    content_hash: str,
) -> str | None:

    path = normalized_text_path(
        content_hash
    )

    if not path.exists():
        return None

    if not path.is_file():
        raise RuntimeError(
            f"Normalized-text cache path "
            f"is not a file: {path}"
        )

    actual_hash = sha256_file(
        path
    )

    if actual_hash != content_hash.lower():
        raise RuntimeError(
            "Normalized-text cache corruption: "
            f"expected {content_hash}, "
            f"got {actual_hash}."
        )

    try:
        return path.read_text(
            encoding="utf-8"
        )

    except UnicodeDecodeError as exc:
        raise RuntimeError(
            f"Cached normalized text is not "
            f"valid UTF-8: {path}"
        ) from exc


# ============================================================
# Raw/source file cache
# ============================================================

def save_binary_file(
    destination: Path,
    data: bytes,
) -> Path:

    if not isinstance(
        data,
        (bytes, bytearray),
    ):
        raise TypeError(
            "data must be bytes."
        )

    if not data:
        raise ValueError(
            "Refusing to cache an empty file."
        )

    _atomic_write_bytes(
        destination,
        bytes(data),
    )

    return destination


def save_raw_file(
    filename: str,
    data: bytes,
) -> Path:

    return save_binary_file(
        raw_cache_path(filename),
        data,
    )


def save_source_file(
    filename: str,
    data: bytes,
) -> Path:

    return save_binary_file(
        source_cache_path(filename),
        data,
    )


# ============================================================
# Safe deletion
# ============================================================

def delete_cache_file(
    path: str | Path,
) -> bool:
    """
    Delete only files located inside the configured cache tree.

    Returns True if a file was removed.
    Returns False if it did not exist.
    """

    initialize_runtime_paths()

    path = Path(path).resolve()
    cache_root = CACHE_DIR.resolve()

    try:
        path.relative_to(cache_root)
    except ValueError as exc:
        raise ValueError(
            "Refusing to delete a file "
            "outside the cache directory."
        ) from exc

    if not path.exists():
        return False

    if not path.is_file():
        raise ValueError(
            f"Refusing to delete non-file: "
            f"{path}"
        )

    path.unlink()

    return True