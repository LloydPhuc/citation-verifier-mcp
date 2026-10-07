from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import (
    urljoin,
    urlparse,
    urlunparse,
)

import requests

from .cache import (
    delete_cache_file,
    load_normalized_text,
    raw_cache_path,
    save_normalized_text,
    save_raw_file,
    save_source_file,
    sha256_text,
    source_cache_path,
)
from .config import (
    HTTP_CONNECT_TIMEOUT_SECONDS,
    HTTP_MAX_REDIRECTS,
    HTTP_READ_TIMEOUT_SECONDS,
    HTTP_USER_AGENT,
    MAX_SOURCE_DOWNLOAD_BYTES,
)
from .database import (
    get_paper,
    upsert_paper,
)
from .text_extractor import (
    ExtractedPage,
    PDFExtractionError,
    PDFExtractionResult,
    extract_pdf_text,
)

# ============================================================
# Constants
# ============================================================

SOURCE_SIDECAR_SCHEMA_VERSION = 1

_ARXIV_NEW_RE = re.compile(
    r"^\d{4}\.\d{4,5}(?:v\d+)?$",
    re.IGNORECASE,
)

_ARXIV_OLD_RE = re.compile(
    r"^[A-Za-z0-9.\-]+/\d{7}(?:v\d+)?$",
    re.IGNORECASE,
)

_WINDOWS_DRIVE_RE = re.compile(
    r"^[A-Za-z]:[\\/]"
)


# ============================================================
# Exceptions
# ============================================================

class SourceLoaderError(RuntimeError):
    """Base source-loader error."""


class UnsupportedSourceError(SourceLoaderError):
    """Input source type is not supported."""


class SourceDownloadError(SourceLoaderError):
    """Remote source could not be downloaded safely."""


class SourceSecurityError(SourceLoaderError):
    """Remote URL violates network safety rules."""


class SourceCacheError(SourceLoaderError):
    """Persistent source cache is malformed or inconsistent."""


# ============================================================
# Public result
# ============================================================

@dataclass(frozen=True)
class SourceDocument:
    source_input: str
    canonical_id: str
    source_type: str
    source_state: str

    paper_id: int

    text: str
    content_hash: str
    normalized_text_path: str

    pages: tuple[ExtractedPage, ...]

    cache_hit: bool

    canonical_url: str | None = None
    arxiv_id: str | None = None
    raw_path: str | None = None

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def text_char_count(self) -> int:
        return len(self.text)

    def to_dict(
        self,
        *,
        include_text: bool = False,
    ) -> dict[str, Any]:

        result: dict[str, Any] = {
            "source_input": self.source_input,
            "canonical_id": self.canonical_id,
            "source_type": self.source_type,
            "source_state": self.source_state,
            "paper_id": self.paper_id,
            "content_hash": self.content_hash,
            "normalized_text_path":
                self.normalized_text_path,
            "page_count": self.page_count,
            "text_char_count":
                self.text_char_count,
            "cache_hit": self.cache_hit,
            "canonical_url":
                self.canonical_url,
            "arxiv_id": self.arxiv_id,
            "raw_path": self.raw_path,
            "pages": [
                {
                    "page_number":
                        page.page_number,
                    "start_char":
                        page.start_char,
                    "end_char":
                        page.end_char,
                    "has_text":
                        page.has_text,
                }
                for page in self.pages
            ],
        }

        if include_text:
            result["text"] = self.text

        return result


# ============================================================
# Input helpers
# ============================================================

def _is_arxiv_id(
    value: str,
) -> bool:

    return bool(
        _ARXIV_NEW_RE.fullmatch(value)
        or _ARXIV_OLD_RE.fullmatch(value)
    )


def _normalize_arxiv_id(
    value: str,
) -> str:

    value = value.strip()

    value = re.sub(
        r"^arxiv:\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )

    value = value.removesuffix(
        ".pdf"
    )

    if not _is_arxiv_id(value):
        raise UnsupportedSourceError(
            f"Invalid or unsupported arXiv ID: "
            f"{value!r}"
        )

    return value


def _extract_arxiv_from_url(
    url: str,
) -> str | None:

    parsed = urlparse(url)

    hostname = (
        parsed.hostname or ""
    ).lower()

    if hostname not in {
        "arxiv.org",
        "www.arxiv.org",
    }:
        return None

    path = parsed.path.strip("/")

    if path.startswith("abs/"):
        candidate = path[4:]

    elif path.startswith("pdf/"):
        candidate = path[4:]

    else:
        return None

    candidate = candidate.removesuffix(
        ".pdf"
    )

    if _is_arxiv_id(candidate):
        return candidate

    return None


def _canonicalize_http_url(
    url: str,
) -> str:

    parsed = urlparse(
        url.strip()
    )

    if parsed.scheme.lower() not in {
        "http",
        "https",
    }:
        raise UnsupportedSourceError(
            "Only http:// and https:// "
            "source URLs are supported."
        )

    if not parsed.hostname:
        raise UnsupportedSourceError(
            f"URL has no hostname: {url}"
        )

    if (
        parsed.username is not None
        or parsed.password is not None
    ):
        raise SourceSecurityError(
            "URLs containing embedded "
            "credentials are not allowed."
        )

    # Fragment never affects downloaded resource.
    parsed = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        fragment="",
    )

    return urlunparse(parsed)


# ============================================================
# Remote network safety
# ============================================================

def _validate_public_http_url(
    url: str,
) -> None:
    """
    Reject obvious SSRF targets.

    This does not claim to solve every possible DNS rebinding
    attack, but prevents direct access to loopback/private/
    link-local/reserved addresses.
    """

    parsed = urlparse(url)

    if parsed.scheme not in {
        "http",
        "https",
    }:
        raise SourceSecurityError(
            "Remote source must use "
            "http or https."
        )

    hostname = parsed.hostname

    if not hostname:
        raise SourceSecurityError(
            "Remote URL has no hostname."
        )

    lowered = hostname.lower()

    if lowered in {
        "localhost",
        "localhost.localdomain",
    }:
        raise SourceSecurityError(
            "Localhost source URLs are blocked."
        )

    port = parsed.port

    if port is None:
        port = (
            443
            if parsed.scheme == "https"
            else 80
        )

    try:
        literal_ip = ipaddress.ip_address(
            hostname
        )
    except ValueError:
        literal_ip = None

    if literal_ip is not None:

        if not literal_ip.is_global:
            raise SourceSecurityError(
                "Non-public IP source URLs "
                "are blocked."
            )

        return

    try:
        results = socket.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
        )

    except socket.gaierror as exc:
        raise SourceDownloadError(
            f"Unable to resolve source host: "
            f"{hostname}"
        ) from exc

    if not results:
        raise SourceDownloadError(
            f"No IP address found for "
            f"source host: {hostname}"
        )

    for result in results:

        address = result[4][0]

        # Remove IPv6 zone identifier if present.
        address = address.split(
            "%",
            1,
        )[0]

        try:
            ip = ipaddress.ip_address(
                address
            )
        except ValueError:
            continue

        if not ip.is_global:
            raise SourceSecurityError(
                "Source hostname resolves to "
                "a non-public IP address."
            )


# ============================================================
# Downloading
# ============================================================

def _download_pdf(
    url: str,
) -> bytes:

    current_url = _canonicalize_http_url(
        url
    )

    session = requests.Session()

    session.headers.update(
        {
            "User-Agent":
                HTTP_USER_AGENT,
            "Accept":
                "application/pdf,"
                "application/octet-stream;q=0.9,"
                "*/*;q=0.1",
        }
    )

    response = None

    try:

        for redirect_count in range(
            HTTP_MAX_REDIRECTS + 1
        ):

            _validate_public_http_url(
                current_url
            )

            try:
                response = session.get(
                    current_url,
                    stream=True,
                    allow_redirects=False,
                    timeout=(
                        HTTP_CONNECT_TIMEOUT_SECONDS,
                        HTTP_READ_TIMEOUT_SECONDS,
                    ),
                )

            except requests.RequestException as exc:
                raise SourceDownloadError(
                    f"Failed to download PDF: "
                    f"{current_url}"
                ) from exc

            if 300 <= response.status_code < 400:

                location = response.headers.get(
                    "Location"
                )

                response.close()
                response = None

                if not location:
                    raise SourceDownloadError(
                        "PDF download returned "
                        "a redirect without Location."
                    )

                if (
                    redirect_count
                    >= HTTP_MAX_REDIRECTS
                ):
                    raise SourceDownloadError(
                        "Too many redirects while "
                        "downloading PDF."
                    )

                current_url = (
                    _canonicalize_http_url(
                        urljoin(
                            current_url,
                            location,
                        )
                    )
                )

                continue

            try:
                response.raise_for_status()

            except requests.HTTPError as exc:
                status = response.status_code

                raise SourceDownloadError(
                    f"PDF download failed with "
                    f"HTTP {status}: "
                    f"{current_url}"
                ) from exc

            content_length = (
                response.headers.get(
                    "Content-Length"
                )
            )

            if content_length:

                try:
                    declared_size = int(
                        content_length
                    )

                except ValueError:
                    declared_size = None

                if (
                    declared_size is not None
                    and declared_size
                    > MAX_SOURCE_DOWNLOAD_BYTES
                ):
                    raise SourceDownloadError(
                        "Remote PDF exceeds maximum "
                        "allowed download size."
                    )

            chunks: list[bytes] = []
            total = 0

            try:

                for chunk in response.iter_content(
                    chunk_size=1024 * 1024
                ):

                    if not chunk:
                        continue

                    total += len(chunk)

                    if (
                        total
                        > MAX_SOURCE_DOWNLOAD_BYTES
                    ):
                        raise SourceDownloadError(
                            "Remote PDF exceeded "
                            "maximum allowed size "
                            "during download."
                        )

                    chunks.append(chunk)

            except requests.RequestException as exc:
                raise SourceDownloadError(
                    "PDF download was interrupted."
                ) from exc

            data = b"".join(chunks)

            if not data:
                raise SourceDownloadError(
                    "Remote server returned "
                    "an empty document."
                )

            # PDF header should occur within first 1024 bytes.
            if b"%PDF-" not in data[:1024]:
                raise SourceDownloadError(
                    "Downloaded resource does not "
                    "appear to be a PDF."
                )

            return data

        raise SourceDownloadError(
            "PDF redirect resolution failed."
        )

    finally:

        if response is not None:
            response.close()

        session.close()


# ============================================================
# Page provenance sidecar
# ============================================================

def _sidecar_path(
    content_hash: str,
) -> Path:

    return source_cache_path(
        f"{content_hash}.pages.json"
    )


def _save_page_sidecar(
    extraction: PDFExtractionResult,
    content_hash: str,
) -> Path:

    payload = {
        "schema_version":
            SOURCE_SIDECAR_SCHEMA_VERSION,
        "content_hash":
            content_hash,
        "page_count":
            extraction.page_count,
        "pages": [
            {
                "page_number":
                    page.page_number,
                "start_char":
                    page.start_char,
                "end_char":
                    page.end_char,
            }
            for page in extraction.pages
        ],
    }

    raw = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    return save_source_file(
        f"{content_hash}.pages.json",
        raw,
    )


def _load_page_sidecar(
    content_hash: str,
    text: str,
) -> tuple[ExtractedPage, ...] | None:

    path = _sidecar_path(
        content_hash
    )

    if not path.exists():
        return None

    try:
        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        return None

    if (
        payload.get("schema_version")
        != SOURCE_SIDECAR_SCHEMA_VERSION
    ):
        return None

    if (
        payload.get("content_hash")
        != content_hash
    ):
        return None

    raw_pages = payload.get(
        "pages"
    )

    if not isinstance(
        raw_pages,
        list,
    ):
        return None

    if (
        payload.get("page_count")
        != len(raw_pages)
    ):
        return None

    pages: list[ExtractedPage] = []

    previous_page_number = 0
    previous_end = 0

    for raw_page in raw_pages:

        if not isinstance(
            raw_page,
            dict,
        ):
            return None

        try:
            page_number = int(
                raw_page["page_number"]
            )
            start_char = int(
                raw_page["start_char"]
            )
            end_char = int(
                raw_page["end_char"]
            )

        except (
            KeyError,
            TypeError,
            ValueError,
        ):
            return None

        if (
            page_number
            != previous_page_number + 1
        ):
            return None

        if (
            start_char < 0
            or end_char < start_char
            or end_char > len(text)
        ):
            return None

        if start_char < previous_end:
            return None

        page_text = text[
            start_char:end_char
        ]

        pages.append(
            ExtractedPage(
                page_number=page_number,
                text=page_text,
                start_char=start_char,
                end_char=end_char,
            )
        )

        previous_page_number = (
            page_number
        )
        previous_end = end_char

    if not pages:
        return None

    return tuple(pages)


# ============================================================
# Persistent cache
# ============================================================

def _load_cached_document(
    *,
    source_input: str,
    canonical_id: str,
) -> SourceDocument | None:

    paper = get_paper(
        canonical_id
    )

    if paper is None:
        return None

    content_hash = paper.get(
        "content_hash"
    )

    if not content_hash:
        return None

    try:
        text = load_normalized_text(
            content_hash
        )

    except RuntimeError:
        return None

    if text is None:
        return None

    pages = _load_page_sidecar(
        content_hash,
        text,
    )

    if pages is None:
        return None

    return SourceDocument(
        source_input=source_input,
        canonical_id=canonical_id,
        source_type=(
            paper.get("source_type")
            or "unknown"
        ),
        source_state="FULL_TEXT",
        paper_id=int(paper["id"]),
        text=text,
        content_hash=content_hash,
        normalized_text_path=str(
            paper.get(
                "normalized_text_path"
            )
            or ""
        ),
        pages=pages,
        cache_hit=True,
        canonical_url=paper.get(
            "canonical_url"
        ),
        arxiv_id=paper.get(
            "arxiv_id"
        ),
        raw_path=None,
    )


def _persist_extraction(
    *,
    source_input: str,
    canonical_id: str,
    source_type: str,
    extraction: PDFExtractionResult,
    canonical_url: str | None = None,
    arxiv_id: str | None = None,
    raw_path: Path | None = None,
    cache_hit: bool = False,
) -> SourceDocument:

    content_hash, text_path = (
        save_normalized_text(
            extraction.text
        )
    )

    _save_page_sidecar(
        extraction,
        content_hash,
    )

    paper_id = upsert_paper(
        canonical_id,
        arxiv_id=arxiv_id,
        canonical_url=canonical_url,
        source_type=source_type,
        content_hash=content_hash,
        normalized_text_path=str(
            text_path
        ),
    )

    return SourceDocument(
        source_input=source_input,
        canonical_id=canonical_id,
        source_type=source_type,
        source_state="FULL_TEXT",
        paper_id=paper_id,
        text=extraction.text,
        content_hash=content_hash,
        normalized_text_path=str(
            text_path
        ),
        pages=extraction.pages,
        cache_hit=cache_hit,
        canonical_url=canonical_url,
        arxiv_id=arxiv_id,
        raw_path=(
            str(raw_path)
            if raw_path is not None
            else None
        ),
    )


# ============================================================
# Local PDF
# ============================================================

def _load_local_pdf(
    source: str,
    *,
    password: str | None,
) -> SourceDocument:

    expanded = os.path.expandvars(
        os.path.expanduser(source)
    )

    path = Path(
        expanded
    ).resolve()

    if not path.exists():
        raise FileNotFoundError(
            path
        )

    if not path.is_file():
        raise UnsupportedSourceError(
            f"Local source is not a file: "
            f"{path}"
        )

    # Windows path case is normalized for identity.
    canonical_path = os.path.normcase(
        str(path)
    )

    canonical_id = (
        f"local:{canonical_path}"
    )

    # Deliberately re-extract local files each call.
    # A user may have modified a PDF at the same path.
    extraction = extract_pdf_text(
        path,
        password=password,
    )

    return _persist_extraction(
        source_input=source,
        canonical_id=canonical_id,
        source_type="local_pdf",
        extraction=extraction,
        raw_path=path,
        cache_hit=False,
    )


# ============================================================
# Remote PDF shared helper
# ============================================================

def _load_remote_pdf(
    *,
    source_input: str,
    canonical_id: str,
    source_type: str,
    url: str,
    arxiv_id: str | None,
    force_refresh: bool,
) -> SourceDocument:

    if not force_refresh:

        cached = _load_cached_document(
            source_input=source_input,
            canonical_id=canonical_id,
        )

        if cached is not None:
            return cached

    raw_filename = (
        f"{sha256_text(canonical_id)}.pdf"
    )

    raw_path = raw_cache_path(
        raw_filename
    )

    extraction = None

    # Raw cache is useful if persistent extracted cache
    # is absent but the downloaded PDF still exists.
    if (
        raw_path.exists()
        and not force_refresh
    ):

        try:
            extraction = extract_pdf_text(
                raw_path
            )

        except PDFExtractionError:
            # Corrupt/stale raw cache should not poison
            # future verification.
            try:
                delete_cache_file(
                    raw_path
                )
            except Exception:
                pass

            extraction = None

    if extraction is None:

        data = _download_pdf(
            url
        )

        save_raw_file(
            raw_filename,
            data,
        )

        try:
            extraction = extract_pdf_text(
                raw_path
            )

        except PDFExtractionError:
            # Do not retain an unusable download.
            try:
                delete_cache_file(
                    raw_path
                )
            except Exception:
                pass

            raise

    return _persist_extraction(
        source_input=source_input,
        canonical_id=canonical_id,
        source_type=source_type,
        extraction=extraction,
        canonical_url=url,
        arxiv_id=arxiv_id,
        raw_path=raw_path,
        cache_hit=False,
    )


# ============================================================
# arXiv
# ============================================================

def _load_arxiv(
    source_input: str,
    arxiv_id: str,
    *,
    force_refresh: bool,
) -> SourceDocument:

    arxiv_id = _normalize_arxiv_id(
        arxiv_id
    )

    canonical_id = (
        f"arxiv:{arxiv_id}"
    )

    pdf_url = (
        f"https://arxiv.org/pdf/"
        f"{arxiv_id}"
    )

    return _load_remote_pdf(
        source_input=source_input,
        canonical_id=canonical_id,
        source_type="arxiv",
        url=pdf_url,
        arxiv_id=arxiv_id,
        force_refresh=force_refresh,
    )


# ============================================================
# Direct PDF URL
# ============================================================

def _load_pdf_url(
    source_input: str,
    url: str,
    *,
    force_refresh: bool,
) -> SourceDocument:

    url = _canonicalize_http_url(
        url
    )

    canonical_id = (
        f"url:{url}"
    )

    return _load_remote_pdf(
        source_input=source_input,
        canonical_id=canonical_id,
        source_type="pdf_url",
        url=url,
        arxiv_id=None,
        force_refresh=force_refresh,
    )


# ============================================================
# Public dispatch
# ============================================================

def _load_web_source(
    source_input: str, url: str, *, canonical_id: str,
    force_refresh: bool, expected_metadata: dict | None = None,
) -> SourceDocument:
    from .reference_resolver import normalize_doi, pdf_identity_matches, title_matches
    from .web_source import fetch_resource, html_metadata, parse_article

    if not force_refresh:
        cached = _load_cached_document(source_input=source_input, canonical_id=canonical_id)
        if cached is not None:
            return cached
    resource = fetch_resource(url)
    if resource.status != 200:
        raise SourceDownloadError(f"Source request returned HTTP {resource.status}.")
    if b"%PDF-" in resource.data[:1024]:
        raw_path = save_raw_file(f"{sha256_text(canonical_id)}.pdf", resource.data)
        extraction = extract_pdf_text(raw_path)
        source_type = "doi_pdf" if expected_metadata else "pdf_url"
    else:
        if "html" not in resource.content_type.lower():
            raise SourceLoaderError("Remote resource is neither PDF nor supported HTML.")
        metadata = html_metadata(resource)
        if expected_metadata:
            found_doi = normalize_doi(metadata.get("citation_doi", "") or metadata.get("dc.identifier", ""))
            if found_doi and found_doi != expected_metadata["doi"]:
                raise SourceLoaderError("Resolved HTML DOI does not match requested reference.")
            if not found_doi and not title_matches(
                expected_metadata["title"], metadata.get("citation_title", "") or metadata.get("dc.title", "")
            ):
                raise SourceLoaderError("Resolved HTML identity could not be verified.")
        try:
            extraction, metadata = parse_article(resource)
            source_type = "doi_html" if expected_metadata else "html_url"
            raw_path = save_raw_file(f"{sha256_text(canonical_id)}.html", resource.data)
        except SourceLoaderError:
            pdf_url = metadata.get("citation_pdf_url")
            if not pdf_url:
                raise
            # One publisher-declared PDF fallback; no recursive crawling.
            pdf_resource = fetch_resource(urljoin(resource.url, pdf_url))
            if pdf_resource.status != 200 or b"%PDF-" not in pdf_resource.data[:1024]:
                raise SourceLoaderError("Publisher PDF link did not yield a PDF.") from None
            raw_path = save_raw_file(f"{sha256_text(canonical_id)}.pdf", pdf_resource.data)
            extraction = extract_pdf_text(raw_path)
            resource = pdf_resource
            source_type = "doi_pdf" if expected_metadata else "pdf_url"
    if expected_metadata and source_type == "doi_pdf" and not pdf_identity_matches(
        expected_metadata, extraction.text
    ):
        raise SourceLoaderError("Resolved PDF identity could not be verified.")
    return _persist_extraction(
        source_input=source_input, canonical_id=canonical_id, source_type=source_type,
        extraction=extraction, canonical_url=resource.url, raw_path=raw_path,
    )


def _load_reference(source_input: str, *, force_refresh: bool) -> SourceDocument:
    from .reference_resolver import full_text_candidates, normalize_doi, resolve_reference

    doi = normalize_doi(source_input)
    doi_only = len(source_input.split()) == 1 and source_input.lower().startswith(
        ("10.", "doi:", "https://doi.org/", "http://doi.org/", "https://dx.doi.org/")
    )
    if doi and doi_only and not force_refresh:
        cached = _load_cached_document(source_input=source_input, canonical_id="doi:" + doi)
        if cached is not None:
            return cached

    resolution = resolve_reference(source_input)
    if resolution["status"] != "VERIFIED":
        raise SourceLoaderError(f"REFERENCE_{resolution['status']}: {resolution['reason']}")
    record = resolution["metadata"]
    canonical_id = "doi:" + record["doi"]
    if not force_refresh:
        cached = _load_cached_document(source_input=source_input, canonical_id=canonical_id)
        if cached is not None:
            return cached
    failures = []
    for url in full_text_candidates(record):
        try:
            return _load_web_source(
                source_input, url, canonical_id=canonical_id, force_refresh=force_refresh,
                expected_metadata=record,
            )
        except (SourceLoaderError, PDFExtractionError) as exc:
            failures.append(str(exc))
    raise SourceLoaderError("FULL_TEXT_UNAVAILABLE: reference exists, but no usable public full text. "
                            + " | ".join(failures))

def load_source(
    source: str | Path,
    *,
    password: str | None = None,
    force_refresh: bool = False,
) -> SourceDocument:
    """
    Load a source into canonical FULL_TEXT representation.

    Supported:
      - local PDF path
      - arXiv ID
      - arXiv abs/pdf URL
      - public HTTP(S) PDF or scholarly HTML URL
      - DOI, DOI URL or complete citation (conservative metadata matching)
    """

    if isinstance(source, Path):
        source_text = str(source)

    elif isinstance(source, str):
        source_text = source

    else:
        raise TypeError(
            "source must be a string "
            "or pathlib.Path."
        )

    source_text = source_text.strip()

    if not source_text:
        raise ValueError(
            "source cannot be empty."
        )

    # --------------------------------------------------------
    # Local path
    # --------------------------------------------------------

    expanded = os.path.expandvars(
        os.path.expanduser(
            source_text
        )
    )

    candidate_path = Path(
        expanded
    )

    try:
        path_exists = candidate_path.exists()
    except OSError:
        path_exists = False  # Long citations / DOI strings are not filesystem paths.
    if (
        path_exists
        or _WINDOWS_DRIVE_RE.match(
            source_text
        )
    ):
        return _load_local_pdf(
            source_text,
            password=password,
        )

    # --------------------------------------------------------
    # arXiv prefix / raw ID
    # --------------------------------------------------------

    stripped_arxiv = re.sub(
        r"^arxiv:\s*",
        "",
        source_text,
        flags=re.IGNORECASE,
    )

    if _is_arxiv_id(
        stripped_arxiv
    ):
        return _load_arxiv(
            source_text,
            stripped_arxiv,
            force_refresh=force_refresh,
        )

    # --------------------------------------------------------
    # URL
    # --------------------------------------------------------

    from .reference_resolver import normalize_doi

    if normalize_doi(source_text):
        return _load_reference(source_text, force_refresh=force_refresh)

    parsed = urlparse(
        source_text
    )

    if parsed.scheme.lower() in {
        "http",
        "https",
    }:

        arxiv_from_url = (
            _extract_arxiv_from_url(
                source_text
            )
        )

        if arxiv_from_url is not None:
            return _load_arxiv(
                source_text,
                arxiv_from_url,
                force_refresh=force_refresh,
            )

        if parsed.path.lower().endswith(".pdf"):
            return _load_pdf_url(source_text, source_text, force_refresh=force_refresh)
        url = _canonicalize_http_url(source_text)
        return _load_web_source(source_text, url, canonical_id=f"url:{url}",
                                force_refresh=force_refresh)

    # --------------------------------------------------------
    # Complete citations and titles; unsupported paths remain local errors.
    # --------------------------------------------------------

    if len(source_text.split()) >= 3 and not source_text.startswith(("/", "\\")):
        return _load_reference(source_text, force_refresh=force_refresh)

    raise UnsupportedSourceError(
        f"Unsupported source: "
        f"{source_text!r}"
    )
