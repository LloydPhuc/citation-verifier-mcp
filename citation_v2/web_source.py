"""Bounded public HTTP acquisition and conservative scholarly HTML extraction."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

from .config import (
    HTTP_CONNECT_TIMEOUT_SECONDS,
    HTTP_MAX_REDIRECTS,
    HTTP_READ_TIMEOUT_SECONDS,
    HTTP_USER_AGENT,
    MAX_SOURCE_DOWNLOAD_BYTES,
)
from .normalizer import normalize_text
from .source_loader import (
    SourceDownloadError,
    SourceLoaderError,
    SourceSecurityError,
    _canonicalize_http_url,
    _validate_public_http_url,
)
from .text_extractor import ExtractedPage, PDFExtractionResult


@dataclass(frozen=True)
class Resource:
    url: str
    data: bytes
    content_type: str
    status: int

    def json(self):
        try:
            return json.loads(self.data)
        except (ValueError, UnicodeDecodeError) as exc:
            raise SourceDownloadError("Metadata service returned invalid JSON.") from exc


def _check_robots(url: str) -> None:
    parsed = urlparse(url)
    if parsed.hostname in {"doi.org", "dx.doi.org"}:
        return  # Resolver, not an article host.
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    resource = fetch_resource(robots_url, respect_robots=False, max_bytes=512_000)
    if resource.status in {404, 410}:
        return
    if resource.status != 200:
        raise SourceDownloadError("Cannot establish robots.txt permission.")
    rules = RobotFileParser()
    rules.parse(resource.data.decode("utf-8", errors="replace").splitlines())
    if not rules.can_fetch(HTTP_USER_AGENT, url):
        raise SourceSecurityError("Source acquisition disallowed by robots.txt.")


def fetch_resource(
    url: str, *, respect_robots: bool = True, max_bytes: int = MAX_SOURCE_DOWNLOAD_BYTES
) -> Resource:
    """No cookies, credentials, ambient proxy credentials or automatic redirects."""
    current = _canonicalize_http_url(url)
    session = requests.Session()
    session.trust_env = False
    session.headers.update({"User-Agent": HTTP_USER_AGENT, "Accept": "*/*"})
    deadline = time.monotonic() + 180
    try:
        for hop in range(HTTP_MAX_REDIRECTS + 1):
            _validate_public_http_url(current)
            if respect_robots:
                _check_robots(current)
            with session.get(
                current,
                stream=True,
                allow_redirects=False,
                timeout=(HTTP_CONNECT_TIMEOUT_SECONDS, HTTP_READ_TIMEOUT_SECONDS),
            ) as response:
                if 300 <= response.status_code < 400:
                    location = response.headers.get("Location")
                    if not location or hop == HTTP_MAX_REDIRECTS:
                        raise SourceDownloadError("Invalid or excessive source redirects.")
                    current = _canonicalize_http_url(urljoin(current, location))
                    continue
                if response.status_code not in {200, 404, 410}:
                    raise SourceDownloadError(
                        f"Source request returned HTTP {response.status_code}."
                    )
                try:
                    declared = int(response.headers.get("Content-Length", "0"))
                except ValueError:
                    declared = 0
                if declared > max_bytes:
                    raise SourceDownloadError("Source exceeds maximum download size.")
                parts = []
                total = 0
                for part in response.iter_content(chunk_size=65536):
                    if time.monotonic() > deadline:
                        raise SourceDownloadError("Source acquisition time budget exceeded.")
                    total += len(part)
                    if total > max_bytes:
                        raise SourceDownloadError("Source exceeds maximum download size.")
                    parts.append(part)
                return Resource(
                    current,
                    b"".join(parts),
                    response.headers.get("Content-Type", ""),
                    response.status_code,
                )
        raise SourceDownloadError("Source redirect resolution failed.")
    except requests.RequestException as exc:
        raise SourceDownloadError("Public source request failed.") from exc
    finally:
        session.close()


@dataclass
class Node:
    tag: str
    attrs: dict[str, str]
    children: list = field(default_factory=list)

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()

    def ignored(self) -> bool:
        ignored = {"script", "style", "nav", "footer", "aside", "form", "noscript"}
        marker = " ".join(self.attrs.get(k, "") for k in ("id", "class", "role"))
        return (
            self.tag in ignored
            or "hidden" in self.attrs
            or self.attrs.get("aria-hidden") == "true"
            or re.search(
                r"(?:abstract|references|bibliography|related|cookie|advert)", marker, re.I
            )
            is not None
        )

    def text(self) -> str:
        if self.ignored():
            return ""
        return " ".join(c.text() if isinstance(c, Node) else c for c in self.children)

    def walk_visible(self):
        if self.ignored():
            return
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk_visible()


def _body_text(body: Node) -> tuple[str, list[str]]:
    parts = []
    headings: list[str] = []
    skip_section = False

    def visit(node):
        nonlocal skip_section
        if isinstance(node, str):
            if not skip_section:
                parts.append(node)
            return
        if node.ignored():
            return
        if node.tag in {"h2", "h3", "h4"}:
            heading = node.text().strip().lower()
            skip_section = bool(
                re.search(
                    r"^(?:\d+[.\s]*)?(?:abstract|references|bibliography|related articles)", heading
                )
            )
            if heading and not skip_section:
                headings.append(heading)
        if node.tag in {"p", "div", "section", "h1", "h2", "h3", "h4"}:
            parts.append("\n")
        for child in node.children:
            visit(child)
        if node.tag in {"p", "div", "section", "h1", "h2", "h3", "h4"}:
            parts.append("\n")

    visit(body)
    return normalize_text(" ".join(parts)), headings


class ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root", {})
        self.stack = [self.root]
        self.node_count = 0

    def handle_starttag(self, tag, attrs):
        self.node_count += 1
        if self.node_count > 50_000:
            raise SourceLoaderError("HTML element count limit exceeded.")
        node = Node(tag, {k: v or "" for k, v in attrs})
        self.stack[-1].children.append(node)
        if tag not in {
            "meta",
            "link",
            "img",
            "br",
            "hr",
            "input",
            "source",
            "wbr",
            "area",
            "base",
            "embed",
            "param",
            "col",
            "track",
        }:
            if len(self.stack) > 256:
                raise SourceLoaderError("HTML nesting limit exceeded.")
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def parse_article(resource: Resource) -> tuple[PDFExtractionResult, dict[str, str]]:
    """Only accept a substantial article body with multiple scientific sections.

    HTML has one synthetic page; offsets refer to the cached normalized article,
    never to the publisher's DOM or to physical PDF pages.
    """
    charset = re.search(r"charset=([\w-]+)", resource.content_type, re.I)
    encoding = charset.group(1) if charset else "utf-8"
    try:
        html = resource.data.decode(encoding, errors="replace")
    except LookupError:
        html = resource.data.decode("utf-8", errors="replace")
    parser = ArticleParser()
    parser.feed(html)
    nodes = list(parser.root.walk())
    metadata = {
        n.attrs.get("name", n.attrs.get("property", "")).lower(): n.attrs.get("content", "")
        for n in nodes
        if n.tag == "meta"
    }
    bodies = [
        n
        for n in parser.root.walk_visible()
        if n.tag in {"article", "main"}
        or re.search(
            r"(?:article-body|article__body|article-content|fulltext|full-text|body-section)",
            " ".join(n.attrs.get(k, "") for k in ("class", "id")),
            re.I,
        )
    ]
    bodies.sort(key=lambda n: 2 if n.tag == "main" else 1 if n.tag == "article" else 0)
    for body in bodies[:20]:
        text, headings = _body_text(body)
        sections = {
            key
            for key in (
                "introduction",
                "methods",
                "methodology",
                "results",
                "discussion",
                "conclusion",
                "background",
            )
            if any(key in heading for heading in headings)
        }
        if len(text) >= 1200 and len(sections) >= 2:
            page = ExtractedPage(1, text, 0, len(text))
            return PDFExtractionResult(
                source_path=resource.url,
                page_count=1,
                pages=(page,),
                text=text,
                extraction_method="scholarly_html",
            ), metadata
    raise SourceLoaderError("ABSTRACT_ONLY_OR_INCOMPLETE_HTML: no substantial article body found.")


def html_metadata(resource: Resource) -> dict[str, str]:
    parser = ArticleParser()
    parser.feed(resource.data.decode("utf-8", errors="replace"))
    return {
        n.attrs.get("name", "").lower(): n.attrs.get("content", "")
        for n in parser.root.walk()
        if n.tag == "meta"
    }
