"""Synthetic DNS/transport fixtures; no connection to an external network."""

import socket
from functools import partial

import pytest
import requests

from citation_v2 import public_http, source_loader, web_source


@pytest.mark.parametrize("loader", ["pdf", "html"])
def test_rebinding_is_rejected_at_connection(monkeypatch, loader):
    lookups = []

    def lookup(host, port, *args, **kwargs):
        lookups.append(host)
        address = "8.8.8.8" if len(lookups) == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    monkeypatch.setattr(socket, "getaddrinfo", lookup)
    monkeypatch.setattr(
        socket, "socket", lambda *a, **k: pytest.fail("Rebound socket was opened")
    )
    download = (
        source_loader._download_pdf
        if loader == "pdf"
        else partial(web_source.fetch_resource, respect_robots=False)
    )
    with pytest.raises(source_loader.SourceDownloadError):
        download("http://fixture.invalid/paper.pdf")
    assert len(lookups) == 2


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_connects_to_validated_address_without_reresolving(monkeypatch, scheme):
    lookups, connected = [], []

    def lookup(host, port, *args, **kwargs):
        lookups.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port))]

    class Socket:
        def settimeout(self, value):
            pass

        def setsockopt(self, *args):
            pass

        def connect(self, address):
            connected.append(address)

    monkeypatch.setattr(socket, "getaddrinfo", lookup)
    monkeypatch.setattr(socket, "socket", lambda *a: Socket())
    with public_http.public_session() as session:
        pool = session.get_adapter(scheme + "://").poolmanager.connection_from_url(
            scheme + "://fixture.invalid"
        )
        connection = pool.ConnectionCls("fixture.invalid", port=443, timeout=1)
        connection._new_conn()
        assert connection.host == "fixture.invalid"
    assert lookups == ["fixture.invalid"]
    assert connected == [("8.8.8.8", 443)]


@pytest.mark.parametrize("loader", ["pdf", "html"])
def test_sources_do_not_send_netrc_or_use_ambient_proxy(monkeypatch, tmp_path, loader):
    netrc = tmp_path / "netrc"
    netrc.write_text("machine 8.8.8.8 login fixture password synthetic\n")
    monkeypatch.setenv("NETRC", str(netrc))
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    seen = []

    def send(session, request, **kwargs):
        seen.append(request)
        assert "Authorization" not in request.headers
        assert not kwargs.get("proxies")
        response = requests.Response()
        response.status_code = 200
        response._content = b"%PDF-1.7\nsynthetic fixture"
        response._content_consumed = True
        response.headers["Content-Type"] = "application/pdf"
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    if loader == "pdf":
        source_loader._download_pdf("http://8.8.8.8/paper.pdf")
    else:
        web_source.fetch_resource("http://8.8.8.8/article", respect_robots=False)
    assert len(seen) == 1
