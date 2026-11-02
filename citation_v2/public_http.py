"""Public-only connections: validate the same resolved addresses we connect to."""

from __future__ import annotations

import ipaddress
import socket

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import NewConnectionError


class _PublicHTTPConnection(HTTPConnection):
    def _new_conn(self):
        try:
            addresses = socket.getaddrinfo(
                self.host, self.port, type=socket.SOCK_STREAM
            )
        except OSError as exc:
            raise NewConnectionError(self, "Public source DNS lookup failed") from exc
        if not addresses or any(
            not ipaddress.ip_address(address[4][0].split("%", 1)[0]).is_global
            for address in addresses
        ):
            raise requests.RequestException("Source DNS returned a non-public address")
        last_error = None
        for family, kind, protocol, _, address in addresses:
            connection = socket.socket(family, kind, protocol)
            try:
                connection.settimeout(self.timeout)
                for option in self.socket_options or ():
                    connection.setsockopt(*option)
                if self.source_address:
                    connection.bind(self.source_address)
                connection.connect(address)
                return connection
            except OSError as exc:
                last_error = exc
                connection.close()
        raise NewConnectionError(self, "Public source connection failed") from last_error


class _PublicHTTPSConnection(_PublicHTTPConnection, HTTPSConnection):
    # HTTPSConnection retains certificate verification and SNI for the original host.
    pass


class _PublicHTTPPool(HTTPConnectionPool):
    ConnectionCls = _PublicHTTPConnection


class _PublicHTTPSPool(HTTPSConnectionPool):
    ConnectionCls = _PublicHTTPSConnection


class _PublicAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {
            "http": _PublicHTTPPool,
            "https": _PublicHTTPSPool,
        }


def public_session() -> requests.Session:
    session = requests.Session()
    # Disable ambient proxy routing and .netrc credentials for untrusted sources.
    session.trust_env = False
    session.mount("http://", _PublicAdapter())
    session.mount("https://", _PublicAdapter())
    return session
