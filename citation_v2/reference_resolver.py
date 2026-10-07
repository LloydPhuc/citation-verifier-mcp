"""Reference identity is separate from content-level claim verification."""

from __future__ import annotations

import os
import re
import unicodedata
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import quote, unquote, urlencode, urlparse

from .source_loader import SourceDownloadError, SourceLoaderError
from .web_source import fetch_resource

DOI_RE = re.compile(r"10\.\d{4,9}/[^\s<>\"]+", re.I)


def normalize_doi(value: str) -> str | None:
    """Accept a DOI, doi: prefix, resolver URL or DOI embedded in a citation."""
    value = unquote(value.strip())
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"}:
        if parsed.username is not None or parsed.password is not None:
            return None
        if parsed.hostname not in {"doi.org", "dx.doi.org", "www.doi.org"}:
            return None
        value = parsed.path.lstrip("/")
    match = DOI_RE.search(value)
    if not match:
        return None
    doi = match.group(0).rstrip(".,;")
    while doi.endswith(")") and doi.count(")") > doi.count("("):
        doi = doi[:-1]
    return doi.lower()


def _norm(value: Any) -> str:
    value = unicodedata.normalize("NFKD", str(value)).casefold()
    return " ".join(re.findall(r"[^\W_]+", value, re.UNICODE))


def _crossref(item: dict) -> dict:
    years = set()
    for field in ("published", "published-print", "published-online", "issued"):
        for date in item.get(field, {}).get("date-parts", []):
            if date:
                years.add(str(date[0]))
    return {
        "doi": str(item.get("DOI", "")).lower(),
        "title": " ".join(item.get("title", [])),
        "authors": [
            " ".join(filter(None, (a.get("given"), a.get("family")))) or a.get("name", "")
            for a in item.get("author", [])
        ],
        "years": sorted(years),
        "publisher": item.get("publisher", ""),
        "container_title": " ".join(item.get("container-title", [])),
        "url": item.get("resource", {}).get("primary", {}).get("URL") or item.get("URL"),
        "full_text_urls": [a["URL"] for a in item.get("link", []) if a.get("URL")],
        "registry": "Crossref",
        "updates": item.get("update-to", []),
    }


def _datacite(item: dict) -> dict:
    a = item.get("attributes", {})
    return {
        "doi": str(a.get("doi", item.get("id", ""))).lower(),
        "title": " ".join(t.get("title", "") for t in a.get("titles", [])),
        "authors": [
            c.get("name") or " ".join(filter(None, (c.get("givenName"), c.get("familyName"))))
            for c in a.get("creators", [])
        ],
        "years": [str(a["publicationYear"])] if a.get("publicationYear") else [],
        "publisher": a.get("publisher", ""),
        "container_title": "",
        "url": a.get("url"),
        "full_text_urls": [],
        "registry": "DataCite",
        "updates": [],
    }


def _get_json(url: str) -> dict[str, Any] | None:
    result = fetch_resource(url, respect_robots=False, max_bytes=2_000_000)
    if result.status in {404, 410}:
        return None
    payload = result.json()
    if not isinstance(payload, dict):
        raise SourceDownloadError("Metadata service returned an invalid object.")
    return payload


def _validate_input(reference: str | dict) -> dict:
    if isinstance(reference, str):
        if not reference.strip() or len(reference) > 8000:
            raise ValueError("reference must contain 1–8000 characters.")
        parsed = urlparse(reference.strip())
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("reference URLs must not contain embedded credentials.")
        return {"citation": reference.strip()}
    if not isinstance(reference, dict):
        raise ValueError("reference must be a DOI/citation string or metadata object.")
    allowed = {"doi", "title", "authors", "year", "publisher", "container_title", "citation"}
    if set(reference) - allowed:
        raise ValueError("Unknown reference fields: " + ", ".join(sorted(set(reference) - allowed)))
    fields = dict(reference)
    for key, value in fields.items():
        if key == "authors":
            if (
                not isinstance(value, list)
                or not value
                or any(not isinstance(a, str) or not a.strip() for a in value)
            ):
                raise ValueError("authors must be a nonempty list of names.")
        elif key == "year":
            if isinstance(value, bool) or not re.fullmatch(r"\d{4}", str(value)):
                raise ValueError("year must be a four-digit year.")
        elif not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must be a nonempty string.")
        if key in {"doi", "citation"} and isinstance(value, str):
            parsed = urlparse(value)
            if parsed.username is not None or parsed.password is not None:
                raise ValueError("reference URLs must not contain embedded credentials.")
    if len(str(fields)) > 8000 or not any(fields.get(k) for k in ("doi", "title", "citation")):
        raise ValueError("Supply doi, title or citation, within 8000 characters.")
    if fields.get("doi") and not normalize_doi(fields["doi"]):
        raise ValueError("Invalid DOI syntax.")
    return fields


def _author_match(given: str, registered: str) -> bool:
    if "," in registered:
        family, personal = registered.split(",", 1)
        registered = personal + " " + family
    a, b = _norm(given).split(), _norm(registered).split()
    # Support initials and family-name-first citations without treating a single
    # given name as an author match.
    if not a or not b or b[-1] not in a:
        return False
    other = [t for t in a if t != b[-1]]
    return all(any(t == x or (len(t) == 1 and x.startswith(t)) for x in b[:-1]) for t in other)


def _checks(fields: dict, record: dict) -> dict:
    checks = {}
    for key in ("title", "year", "publisher", "container_title", "authors"):
        if key not in fields:
            continue
        actual = record["years"] if key == "year" else record.get(key)
        if not actual:
            checks[key] = "UNKNOWN"
        elif key == "year":
            checks[key] = "MATCH" if str(fields[key]) in actual else "MISMATCH"
        elif key == "authors":
            checks[key] = (
                "MATCH"
                if all(
                    any(_author_match(name, author) for author in actual) for name in fields[key]
                )
                else "MISMATCH"
            )
        else:
            checks[key] = "MATCH" if _norm(fields[key]) == _norm(actual) else "MISMATCH"
    return checks


def _raw_match(citation: str, record: dict) -> bool:
    clean, title = _norm(citation), _norm(record["title"])
    if not title or title not in clean:
        return False
    years = re.findall(r"\b(?:19|20)\d{2}\b", citation)
    if years and not set(years).intersection(record["years"]):
        return False
    # A title alone may identify a work; a full citation must also corroborate
    # at least one author. No fuzzy first-hit acceptance.
    if clean == title:
        return True
    return bool(record["authors"]) and any(
        _norm(a.split(",", 1)[0] if "," in a else a).split()[-1] in clean.split()
        for a in record["authors"]
        if _norm(a)
    )


def resolve_reference(reference: str | dict) -> dict:
    fields = _validate_input(reference)
    doi = normalize_doi(fields.get("doi") or fields.get("citation", ""))
    errors, candidates = [], []
    if doi:
        for registry, endpoint_base, convert in (
            ("Crossref", "https://api.crossref.org/works/", _crossref),
            ("DataCite", "https://api.datacite.org/dois/", _datacite),
        ):
            try:
                payload = _get_json(endpoint_base + quote(doi, safe=""))
                if payload is not None:
                    record = convert(
                        payload["message"] if registry == "Crossref" else payload["data"]
                    )
                    if record["doi"] != doi or not record["title"]:
                        raise SourceDownloadError("Registry returned inconsistent DOI metadata.")
                    candidates = [record]
                    break
            except (SourceLoaderError, KeyError, TypeError, ValueError) as exc:
                errors.append(f"{registry}: {type(exc).__name__}")
    else:
        query = fields.get("citation") or " ".join(
            str(fields.get(k, "")) for k in ("title", "authors", "year")
        )
        try:
            payload = _get_json(
                "https://api.crossref.org/works?"
                + urlencode({"query.bibliographic": query, "rows": 5})
            )
            candidates = [_crossref(i) for i in payload["message"]["items"]] if payload else []
        except (SourceLoaderError, KeyError, TypeError, ValueError) as exc:
            errors.append(f"Crossref: {type(exc).__name__}")

    candidates = list({r["doi"]: r for r in candidates if r["doi"] and r["title"]}.values())
    base = {
        "ok": True,
        "checked_at": datetime.now(UTC).isoformat(),
        "reference_exists": None,
        "verdict": "ABSTAIN",
        "status": "UNVERIFIED",
        "metadata": None,
        "field_checks": {},
        "candidates": candidates,
        "provider_errors": errors,
    }
    if not candidates:
        base["status"] = "SERVICE_UNAVAILABLE" if errors else "NOT_FOUND"
        base["reason"] = "No registry match established; this does not prove fabrication."
        return base
    if doi:
        selected = candidates[0]
    else:
        matches = [
            r
            for r in candidates
            if (
                _norm(fields["title"]) == _norm(r["title"])
                if fields.get("title")
                else _raw_match(fields["citation"], r)
            )
        ]
        if len(matches) > 1:
            compatible = [r for r in matches if "MISMATCH" not in _checks(fields, r).values()]
            if len(compatible) == 1:
                matches = compatible
        if len(matches) != 1:
            base["status"] = "AMBIGUOUS" if len(matches) > 1 else "NO_CONFIDENT_MATCH"
            base["reason"] = "Supply DOI or exact title, authors and year to disambiguate."
            return base
        selected = matches[0]
    checks = _checks(fields, selected)
    raw = fields.get("citation", "")
    if raw and doi:
        if normalize_doi(raw) and normalize_doi(raw) != doi:
            checks["doi"] = "MISMATCH"
        bare = re.sub(r"^(?:doi:\s*|https?://(?:dx\.)?doi\.org/)", "", raw, flags=re.I)
        if normalize_doi(raw) and bare.strip().lower().rstrip(".,;") != doi:
            checks["citation"] = "MATCH" if _raw_match(raw, selected) else "UNKNOWN"
    base.update(reference_exists=True, metadata=selected, field_checks=checks)
    if "MISMATCH" in checks.values():
        base.update(
            verdict="WARN",
            status="METADATA_MISMATCH",
            reason="Work exists, but supplied citation fields disagree with registry metadata.",
        )
    elif "UNKNOWN" in checks.values():
        base.update(
            verdict="WARN",
            status="PARTIALLY_VERIFIED",
            reason="Work exists; some supplied citation fields could not be verified.",
        )
    else:
        base.update(
            verdict="PASS",
            status="VERIFIED",
            reason=(
                "Citation title and available author/year corroborate a registry record; "
                "use structured fields for complete field checks."
                if raw and not doi
                else "Registry record found and supplied structured fields match."
            ),
        )
    return base


def full_text_candidates(record: dict) -> list[str]:
    urls = list(record.get("full_text_urls", []))
    email = os.getenv("CITATION_UNPAYWALL_EMAIL", "").strip()
    if email:
        try:
            payload = _get_json(
                "https://api.unpaywall.org/v2/"
                + quote(record["doi"], safe="")
                + "?"
                + urlencode({"email": email})
            )
            for location in (payload or {}).get("oa_locations", []):
                urls.extend(location[k] for k in ("url_for_pdf", "url") if location.get(k))
        except SourceLoaderError:
            pass  # Optional provider must not disable publisher acquisition.
    if record.get("url"):
        urls.append(record["url"])
    urls.append("https://doi.org/" + record["doi"])
    return list(dict.fromkeys(u for u in urls if isinstance(u, str)))[:6]


def title_matches(expected: str, actual: str) -> bool:
    return bool(actual) and SequenceMatcher(None, _norm(expected), _norm(actual)).ratio() >= 0.95


def pdf_identity_matches(record: dict, text: str) -> bool:
    # Limit checks to the opening text; a bibliography mentioning the expected
    # work must not be accepted as the requested paper.
    opening = text[:4000]
    return record["doi"].casefold() in opening.casefold() or _norm(record["title"]) in _norm(
        opening
    )
