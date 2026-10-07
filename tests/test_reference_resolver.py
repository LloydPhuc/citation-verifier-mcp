"""Deterministic identity matching and provider failure regressions."""

import pytest

from citation_v2 import reference_resolver as resolver
from citation_v2.source_loader import SourceDownloadError

pytestmark = pytest.mark.unit


@pytest.fixture
def item():
    return {
        "DOI": "10.1234/example",
        "title": ["Testing citation identity"],
        "author": [{"given": "Jane", "family": "Smith"}],
        "published-print": {"date-parts": [[2024]]},
        "published-online": {"date-parts": [[2023]]},
        "publisher": "Example Press",
        "container-title": ["Example Journal"],
        "URL": "https://doi.org/10.1234/example",
        "link": [{"URL": "https://example.org/full.pdf"}],
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("10.1234/EXAMPLE", "10.1234/example"),
        ("doi:10.1234/example", "10.1234/example"),
        ("https://doi.org/10.1234%2Fexample?tracking=1", "10.1234/example"),
        ("Smith (2024). Testing. doi:10.1234/example.", "10.1234/example"),
        ("10.1234/test(foo)", "10.1234/test(foo)"),
        ("(10.1234/example).", "10.1234/example"),
        ("https://example.org/10.1234/example", None),
        ("not a doi", None),
    ],
)
def test_doi_normalization(value, expected):
    assert resolver.normalize_doi(value) == expected


def test_doi_record_verified(monkeypatch, item):
    monkeypatch.setattr(resolver, "_get_json", lambda url: {"message": item})
    result = resolver.resolve_reference("10.1234/example")
    assert result["verdict"] == "PASS"
    assert result["reference_exists"] is True
    assert result["metadata"]["registry"] == "Crossref"


def test_all_structured_fields_and_online_year(monkeypatch, item):
    monkeypatch.setattr(resolver, "_get_json", lambda url: {"message": item})
    result = resolver.resolve_reference(
        {
            "doi": "10.1234/example",
            "title": "Testing citation identity",
            "authors": ["Smith, J."],
            "year": 2023,
            "publisher": "Example Press",
            "container_title": "Example Journal",
        }
    )
    assert result["verdict"] == "PASS"
    assert set(result["field_checks"].values()) == {"MATCH"}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", "Fabricated paper title"),
        ("year", 2026),
        ("authors", ["Jane Doe"]),
        ("publisher", "Wrong publisher"),
        ("container_title", "Wrong Journal"),
    ],
)
def test_real_doi_does_not_validate_wrong_citation(monkeypatch, item, field, value):
    monkeypatch.setattr(resolver, "_get_json", lambda url: {"message": item})
    result = resolver.resolve_reference({"doi": "10.1234/example", field: value})
    assert result["reference_exists"] is True
    assert result["status"] == "METADATA_MISMATCH"
    assert result["verdict"] == "WARN"
    assert result["field_checks"][field] == "MISMATCH"


def test_missing_metadata_unknown(monkeypatch, item):
    item.pop("publisher")
    monkeypatch.setattr(resolver, "_get_json", lambda url: {"message": item})
    result = resolver.resolve_reference({"doi": "10.1234/example", "publisher": "Press"})
    assert result["status"] == "PARTIALLY_VERIFIED"


def test_datacite_fallback(monkeypatch):
    def get(url):
        if "crossref" in url:
            return None
        return {
            "data": {
                "id": "10.1234/example",
                "attributes": {
                    "doi": "10.1234/example",
                    "titles": [{"title": "Dataset title"}],
                    "creators": [{"name": "Jane Smith"}],
                    "publicationYear": 2024,
                    "publisher": "Repository",
                    "url": "https://example.org/data",
                },
            }
        }

    monkeypatch.setattr(resolver, "_get_json", get)
    result = resolver.resolve_reference("10.1234/example")
    assert result["metadata"]["registry"] == "DataCite"


def test_not_found_is_not_fabrication(monkeypatch):
    monkeypatch.setattr(resolver, "_get_json", lambda url: None)
    result = resolver.resolve_reference("10.1234/example")
    assert result["status"] == "NOT_FOUND"
    assert result["reference_exists"] is None
    assert result["verdict"] == "ABSTAIN"


def test_outage_not_not_found(monkeypatch):
    def get(url):
        raise SourceDownloadError("HTTP 429")

    monkeypatch.setattr(resolver, "_get_json", get)
    result = resolver.resolve_reference("10.1234/example")
    assert result["status"] == "SERVICE_UNAVAILABLE"
    assert result["reference_exists"] is None


def test_full_citation_resolution(monkeypatch, item):
    monkeypatch.setattr(resolver, "_get_json", lambda url: {"message": {"items": [item]}})
    result = resolver.resolve_reference(
        "Smith, J. (2024). Testing citation identity. Example Press."
    )
    assert result["status"] == "VERIFIED"


def test_first_fuzzy_search_hit_not_accepted(monkeypatch, item):
    monkeypatch.setattr(resolver, "_get_json", lambda url: {"message": {"items": [item]}})
    result = resolver.resolve_reference("Smith (2024). Totally unrelated work.")
    assert result["status"] == "NO_CONFIDENT_MATCH"
    assert result["metadata"] is None


def test_same_title_ambiguous(monkeypatch, item):
    second = {**item, "DOI": "10.1234/second"}
    monkeypatch.setattr(resolver, "_get_json", lambda url: {"message": {"items": [item, second]}})
    result = resolver.resolve_reference({"title": "Testing citation identity"})
    assert result["status"] == "AMBIGUOUS"


def test_wrong_registry_identity_rejected(monkeypatch, item):
    item["DOI"] = "10.1234/wrong"
    monkeypatch.setattr(resolver, "_get_json", lambda url: {"message": item})
    assert resolver.resolve_reference("10.1234/example")["verdict"] == "ABSTAIN"


@pytest.mark.parametrize(
    "reference",
    [
        "",
        4,
        {},
        {"title": "abc", "extra": 3},
        {"doi": "bad"},
        {"title": "abc", "authors": "Smith"},
        {"title": "abc", "year": True},
    ],
)
def test_invalid_inputs(reference):
    with pytest.raises(ValueError, match="reference|Unknown|DOI|authors|year|Supply"):
        resolver.resolve_reference(reference)


def test_claim_mismatch_does_not_acquire_content(monkeypatch, item):
    import server

    monkeypatch.setattr(resolver, "_get_json", lambda url: {"message": item})

    def unexpected(*args, **kwargs):
        pytest.fail("Claim verification must not run for mismatched citation")

    monkeypatch.setattr(server, "verify_claim", unexpected)
    result = server.verify_reference({"doi": "10.1234/example", "year": 2026}, "Claim")
    assert result["claim_verification"]["verdict"] == "ABSTAIN"


def test_reference_and_claim_verdicts_separate(monkeypatch, item):
    import server

    monkeypatch.setattr(resolver, "_get_json", lambda url: {"message": item})
    monkeypatch.setattr(server, "verify_claim", lambda *args: {"verdict": "FAIL"})
    result = server.verify_reference("10.1234/example", "Contradicted claim")
    assert result["verdict"] == "PASS"
    assert result["claim_verification"]["verdict"] == "FAIL"


def test_datacite_family_name_first_authors():
    assert resolver._author_match("Ashish Vaswani", "Vaswani, Ashish")
    assert resolver._author_match("Vaswani, A.", "Vaswani, Ashish")
    assert not resolver._author_match("Noam Shazeer", "Vaswani, Ashish")


def test_conflicting_doi_inside_citation(monkeypatch, item):
    monkeypatch.setattr(resolver, "_get_json", lambda url: {"message": item})
    result = resolver.resolve_reference(
        {
            "doi": "10.1234/example",
            "citation": "Smith (2024). Testing citation identity. 10.1234/wrong",
        }
    )
    assert result["field_checks"]["doi"] == "MISMATCH"
    assert result["status"] == "METADATA_MISMATCH"


def test_credential_url_rejected_before_network():
    with pytest.raises(ValueError, match="credentials"):
        resolver.resolve_reference("https://user:secret@doi.org/10.1234/example")


def test_pdf_identity_not_from_reference_list():
    record = {"doi": "10.1234/example", "title": "Testing citation identity"}
    assert resolver.pdf_identity_matches(record, "Testing citation identity\nIntroduction")
    assert not resolver.pdf_identity_matches(record, "Other paper body. " * 1000 + record["title"])
