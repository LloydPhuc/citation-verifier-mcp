"""Web acquisition, incomplete-page gates and exact text provenance."""

import json

import pytest

from citation_v2 import reference_resolver, source_loader, web_source
from citation_v2.source_loader import SourceDownloadError, SourceLoaderError, SourceSecurityError
from citation_v2.web_source import Resource

pytestmark = pytest.mark.unit


@pytest.fixture
def article():
    return (
        '<html><head><meta name="citation_doi" content="10.1234/example">'
        '<meta name="citation_title" content="Testing citation identity"></head>'
        "<body><nav>Navigation noise</nav><article><h1>Testing citation identity</h1>"
        '<section class="abstract"><p>Abstract noise</p></section><h2>Introduction</h2>'
        "<p>" + "Researchers study citation identity with controlled experiments. " * 20 + "</p>"
        "<h2>Results</h2><p>The sample contains 42 verified references.</p><p>"
        + "The study measures metadata consistency and reproducible citation verification. "
        * 20
        + "</p><h2>References</h2><p>Bibliography noise</p></article>"
        "<aside>Related article noise</aside><script>Executable noise</script></body></html>"
    ).encode()


def test_html_exact_offsets_and_boilerplate_removal(article):
    extraction, metadata = web_source.parse_article(
        Resource("https://example.org/paper", article, "text/html", 200)
    )
    assert metadata["citation_doi"] == "10.1234/example"
    assert (
        extraction.text[extraction.pages[0].start_char : extraction.pages[0].end_char]
        == extraction.pages[0].text
    )
    assert "42 verified references" in extraction.text
    for noise in (
        "Navigation noise",
        "Abstract noise",
        "Bibliography noise",
        "Related article noise",
        "Executable noise",
    ):
        assert noise not in extraction.text


@pytest.mark.parametrize(
    "html",
    [
        "<article><h2>Abstract</h2><p>Only abstract</p></article>",
        "<div>Please sign in or purchase access.</div>",
        "<main><h2>Introduction</h2><p>Only one section</p></main>",
        '<script>document.write("Full text")</script>',
    ],
)
def test_incomplete_sources_rejected(html):
    with pytest.raises(SourceLoaderError, match="INCOMPLETE_HTML"):
        web_source.parse_article(Resource("https://example.org", html.encode(), "text/html", 200))


def test_html_source_persistence_and_cache(monkeypatch, article, clean_db):
    calls = []

    def fetch(url, **kwargs):
        calls.append(url)
        return Resource(url, article, "text/html", 200)

    monkeypatch.setattr(web_source, "fetch_resource", fetch)
    url = "https://example.org/persistence-test"
    first = source_loader.load_source(url, force_refresh=True)
    second = source_loader.load_source(url)
    assert first.source_type == "html_url"
    assert first.canonical_url == url
    assert second.cache_hit is True
    assert second.text == first.text
    assert len(calls) == 1


def test_doi_html_identity_mismatch(monkeypatch, article):
    monkeypatch.setattr(
        web_source, "fetch_resource", lambda url: Resource(url, article, "text/html", 200)
    )
    with pytest.raises(SourceLoaderError, match="does not match"):
        source_loader._load_web_source(
            "10.1234/wrong",
            "https://example.org",
            canonical_id="doi:wrong",
            force_refresh=True,
            expected_metadata={"doi": "10.1234/wrong", "title": "Wrong"},
        )


def test_doi_acquisition_fallback_and_cache(monkeypatch, article, clean_db):
    record = {"doi": "10.1234/example", "title": "Testing citation identity"}
    monkeypatch.setattr(
        reference_resolver,
        "resolve_reference",
        lambda source: {
            "status": "VERIFIED",
            "metadata": record,
        },
    )
    monkeypatch.setattr(
        reference_resolver,
        "full_text_candidates",
        lambda record: ["https://example.org/blocked", "https://example.org/body"],
    )
    calls = []

    def fetch(url):
        calls.append(url)
        if url.endswith("blocked"):
            raise SourceDownloadError("HTTP 403")
        return Resource(url, article, "text/html", 200)

    monkeypatch.setattr(web_source, "fetch_resource", fetch)
    first = source_loader.load_source("10.1234/example", force_refresh=True)

    def unexpected_lookup(source):
        pytest.fail("Cached bare DOI content must not require another metadata request")

    monkeypatch.setattr(reference_resolver, "resolve_reference", unexpected_lookup)
    second = source_loader.load_source("https://doi.org/10.1234/example")
    assert first.source_type == "doi_html"
    assert first.canonical_id == "doi:10.1234/example"
    assert second.cache_hit is True
    assert len(calls) == 2


class Response:
    def __init__(self, data=b"text", status=200, headers=None):
        self.data, self.status_code, self.headers = data, status, headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def iter_content(self, chunk_size):
        yield self.data


def mock_session(monkeypatch, responses):
    calls = []

    class Session:
        headers = {}

        def get(self, url, **kwargs):
            calls.append(url)
            assert kwargs["allow_redirects"] is False
            return responses.pop(0)

        def close(self):
            pass

    monkeypatch.setattr(web_source.requests, "Session", Session)
    return calls


def test_redirect_to_private_host_blocked(monkeypatch):
    calls = mock_session(
        monkeypatch, [Response(status=302, headers={"Location": "http://127.0.0.1/internal"})]
    )
    monkeypatch.setattr(web_source, "_check_robots", lambda url: None)
    with pytest.raises(SourceSecurityError):
        web_source.fetch_resource("https://8.8.8.8/article")
    assert len(calls) == 1


@pytest.mark.parametrize("headers", [{"Content-Length": "100"}, {}])
def test_download_size_limit(monkeypatch, headers):
    mock_session(monkeypatch, [Response(b"a" * 100, headers=headers)])
    with pytest.raises(SourceDownloadError, match="maximum"):
        web_source.fetch_resource("https://8.8.8.8/article", respect_robots=False, max_bytes=10)


def test_robots_disallow(monkeypatch):
    calls = mock_session(monkeypatch, [Response(b"User-agent: *\nDisallow: /article")])
    with pytest.raises(SourceSecurityError, match="robots"):
        web_source.fetch_resource("https://8.8.8.8/article")
    assert calls == ["https://8.8.8.8/robots.txt"]


def test_robots_missing_allows_article(monkeypatch):
    calls = mock_session(monkeypatch, [Response(status=404), Response(b"article")])
    assert web_source.fetch_resource("https://8.8.8.8/article").data == b"article"
    assert len(calls) == 2


def test_rate_limit_is_acquisition_failure(monkeypatch):
    mock_session(monkeypatch, [Response(status=429)])
    with pytest.raises(SourceDownloadError, match="429"):
        web_source.fetch_resource("https://8.8.8.8/article", respect_robots=False)


def test_invalid_json_not_not_found():
    with pytest.raises(SourceDownloadError):
        Resource("https://example.org", b"not json", "text/html", 200).json()
    assert Resource(
        "https://example.org", json.dumps({"a": 1}).encode(), "application/json", 200
    ).json() == {"a": 1}


@pytest.mark.parametrize("attribute", ["hidden", 'aria-hidden="true"'])
def test_hidden_sections_do_not_establish_full_text(attribute):
    html = (
        "<article><h2>Introduction</h2><p>"
        + "Visible introductory text. " * 100
        + "</p><section "
        + attribute
        + "><h2>Results</h2><p>Hidden results.</p></section></article>"
    )
    with pytest.raises(SourceLoaderError, match="INCOMPLETE_HTML"):
        web_source.parse_article(Resource("https://example.org", html.encode(), "text/html", 200))


def test_article_inside_hidden_container_rejected(article):
    html = b"<div hidden>" + article + b"</div>"
    with pytest.raises(SourceLoaderError, match="INCOMPLETE_HTML"):
        web_source.parse_article(Resource("https://example.org", html, "text/html", 200))
