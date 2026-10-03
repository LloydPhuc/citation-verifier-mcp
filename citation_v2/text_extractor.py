from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pdfplumber
from pdfminer.pdfdocument import (
    PDFEncryptionError,
    PDFPasswordIncorrect,
)
from pdfminer.pdfparser import PDFSyntaxError

from .normalizer import normalize_text

# ============================================================
# Exceptions
# ============================================================

class PDFExtractionError(RuntimeError):
    """Base error for PDF text extraction."""


class PDFEncryptedError(PDFExtractionError):
    """PDF requires a password or authentication failed."""


class PDFNoTextError(PDFExtractionError):
    """
    PDF opened successfully but contains no extractable text.

    This may indicate a scanned/image-only PDF.
    OCR is intentionally NOT performed automatically.
    """


# ============================================================
# Result schemas
# ============================================================

@dataclass(frozen=True)
class ExtractedPage:
    """
    Text and provenance information for one PDF page.

    Character offsets are relative to the final canonical
    document text.

    end_char is exclusive.
    """

    page_number: int
    text: str
    start_char: int
    end_char: int

    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["has_text"] = self.has_text
        return result


@dataclass(frozen=True)
class PDFExtractionResult:
    source_path: str
    page_count: int
    text: str
    pages: tuple[ExtractedPage, ...]
    extraction_method: str = "pdfplumber"

    @property
    def text_char_count(self) -> int:
        return len(self.text)

    @property
    def pages_with_text(self) -> int:
        return sum(
            1
            for page in self.pages
            if page.has_text
        )

    @property
    def blank_pages(self) -> int:
        return (
            self.page_count
            - self.pages_with_text
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "page_count": self.page_count,
            "text": self.text,
            "text_char_count": self.text_char_count,
            "pages_with_text": self.pages_with_text,
            "blank_pages": self.blank_pages,
            "extraction_method": self.extraction_method,
            "pages": [
                page.to_dict()
                for page in self.pages
            ],
        }


# ============================================================
# Path handling
# ============================================================

def _normalize_input_path(
    path: str | Path,
) -> Path:

    if isinstance(path, Path):
        raw = str(path)
    elif isinstance(path, str):
        raw = path
    else:
        raise TypeError(
            "path must be a string or pathlib.Path."
        )

    raw = raw.strip()

    if not raw:
        raise ValueError(
            "PDF path cannot be empty."
        )

    raw = os.path.expandvars(
        os.path.expanduser(raw)
    )

    source = Path(raw).resolve()

    if not source.exists():
        raise FileNotFoundError(
            source
        )

    if not source.is_file():
        raise ValueError(
            f"Expected a PDF file, got: {source}"
        )

    try:
        size = source.stat().st_size
    except OSError as exc:
        raise PDFExtractionError(
            f"Unable to inspect PDF file: {source}"
        ) from exc

    if size <= 0:
        raise PDFExtractionError(
            f"PDF file is empty: {source}"
        )

    return source


# ============================================================
# PDF extraction
# ============================================================

def extract_pdf_text(
    path: str | Path,
    *,
    password: str | None = None,
) -> PDFExtractionResult:
    """
    Extract canonical text from a local PDF.

    Important invariants
    --------------------
    - no OCR is performed;
    - every page is represented in the result;
    - page offsets map exactly to result.text;
    - a failure to extract any page aborts the whole operation;
    - encrypted PDFs require explicit authentication.

    Pages are separated by exactly two newline characters
    in the canonical document text.
    """

    source = _normalize_input_path(
        path
    )

    document = None

    try:
        try:
            document = pdfplumber.open(
                str(source),
                password=password if password is not None else None,
            )

        except Exception as exc:
            wrapped = exc.args[0] if exc.args else None
            if isinstance(
                wrapped,
                PDFPasswordIncorrect | PDFEncryptionError,
            ):
                if password is None:
                    raise PDFEncryptedError(
                        "PDF is encrypted and requires "
                        "a password."
                    ) from exc
                raise PDFEncryptedError(
                    "PDF password was rejected."
                ) from exc

            if isinstance(wrapped, PDFSyntaxError):
                try:
                    with open(source, "rb") as f:
                        header = f.read(1024)
                except OSError:
                    header = b""

                if (
                    b"%PDF" not in header
                    and source.suffix.lower() != ".pdf"
                ):
                    raise PDFExtractionError(
                        f"Input is not a PDF document: "
                        f"{source}"
                    ) from exc

            raise PDFExtractionError(
                f"Unable to open PDF: {source}"
            ) from exc

        page_count = len(document.pages)

        if page_count <= 0:
            raise PDFExtractionError(
                "PDF contains no pages."
            )

        # ----------------------------------------------------
        # Extract each page independently.
        # ----------------------------------------------------

        raw_page_texts: list[str] = []

        for index in range(page_count):

            try:
                page = document.pages[index]

                raw_text = page.extract_text()

            except Exception as exc:
                raise PDFExtractionError(
                    "Failed to extract text from "
                    f"PDF page {index + 1}."
                ) from exc

            if raw_text is None:
                raw_text = ""

            if not isinstance(
                raw_text,
                str,
            ):
                raise PDFExtractionError(
                    "pdfplumber returned unexpected "
                    f"text type for page {index + 1}: "
                    f"{type(raw_text).__name__}"
                )

            normalized = normalize_text(
                raw_text
            )

            raw_page_texts.append(
                normalized
            )

        # ----------------------------------------------------
        # A document with no textual content must not be
        # treated as successfully verified full text.
        # ----------------------------------------------------

        if not any(
            text.strip()
            for text in raw_page_texts
        ):
            raise PDFNoTextError(
                "PDF contains no extractable text. "
                "It may be scanned or image-only. "
                "OCR was not attempted."
            )

        # ----------------------------------------------------
        # Construct canonical document and provenance offsets.
        # ----------------------------------------------------

        document_parts: list[str] = []
        extracted_pages: list[
            ExtractedPage
        ] = []

        cursor = 0

        for index, page_text in enumerate(
            raw_page_texts
        ):

            # Exactly two newlines separate physical pages.
            if index > 0:
                separator = "\n\n"

                document_parts.append(
                    separator
                )

                cursor += len(separator)

            start_char = cursor

            document_parts.append(
                page_text
            )

            cursor += len(
                page_text
            )

            end_char = cursor

            extracted_pages.append(
                ExtractedPage(
                    page_number=index + 1,
                    text=page_text,
                    start_char=start_char,
                    end_char=end_char,
                )
            )

        canonical_text = "".join(
            document_parts
        )

        # ----------------------------------------------------
        # Internal provenance consistency checks.
        #
        # If these ever fail, this is a programming bug.
        # ----------------------------------------------------

        for page in extracted_pages:

            mapped = canonical_text[
                page.start_char:
                page.end_char
            ]

            if mapped != page.text:
                raise PDFExtractionError(
                    "Internal provenance offset "
                    f"mismatch on page "
                    f"{page.page_number}."
                )

            if (
                page.start_char < 0
                or page.end_char
                < page.start_char
                or page.end_char
                > len(canonical_text)
            ):
                raise PDFExtractionError(
                    "Invalid provenance offsets "
                    f"for page {page.page_number}."
                )

        return PDFExtractionResult(
            source_path=str(source),
            page_count=page_count,
            text=canonical_text,
            pages=tuple(
                extracted_pages
            ),
        )

    finally:
        if document is not None:
            try:
                document.close()
            except Exception:
                pass
