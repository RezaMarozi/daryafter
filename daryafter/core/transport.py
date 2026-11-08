"""The only module that talks to the network library (httpx).

The engine uses the tiny ``Transport`` / ``Response`` interface below, so it can
be tested against a fake network and the HTTP library can be swapped later."""
from __future__ import annotations

import ssl
from dataclasses import dataclass
from typing import AsyncIterator, Mapping, Protocol

from .errors import FatalError, NetworkError


class Response(Protocol):
    status: int
    headers: "Headers"
    url: str

    def iter_chunks(self) -> AsyncIterator[bytes]: ...
    async def aclose(self) -> None: ...


class Headers(Protocol):
    def get(self, key: str, default: str | None = None) -> str | None: ...


class Transport(Protocol):
    async def open(self, url: str, headers: Mapping[str, str]) -> Response: ...
    async def aclose(self) -> None: ...


@dataclass(slots=True)
class NetworkConfig:
    proxy_mode: str = "system"       # system | none | manual
    proxy_url: str = ""              # http://host:port or socks5://host:port
    http2: bool = False
    verify_tls: bool = True
    connect_timeout: float = 20.0
    read_timeout: float = 30.0


def _tls_context():
    """Prefer the platform certificate store when truststore is available."""
    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:
        return True      # httpx default (certifi bundle)


class HttpxTransport:
    def __init__(self, cfg: NetworkConfig, *, username: str = "", password: str = "",
                 max_connections: int = 8):
        import httpx

        self._httpx = httpx
        kwargs: dict = {}
        trust_env = True
        if cfg.proxy_mode == "none":
            trust_env = False
        elif cfg.proxy_mode == "manual" and cfg.proxy_url:
            trust_env = False
            kwargs["proxy"] = cfg.proxy_url
        http2 = cfg.http2
        if http2:
            try:
                import h2  # noqa: F401
            except ImportError:
                http2 = False
        self._client = httpx.AsyncClient(
            http2=http2,
            verify=_tls_context() if cfg.verify_tls else False,
            follow_redirects=True,
            max_redirects=10,
            trust_env=trust_env,
            auth=httpx.BasicAuth(username, password) if username else None,
            timeout=httpx.Timeout(connect=cfg.connect_timeout, read=cfg.read_timeout,
                                  write=cfg.read_timeout, pool=None),
            limits=httpx.Limits(max_connections=max_connections + 2,
                                max_keepalive_connections=max_connections),
            **kwargs,
        )

    async def open(self, url: str, headers: Mapping[str, str]) -> "_HttpxResponse":
        httpx = self._httpx
        try:
            request = self._client.build_request("GET", url, headers=dict(headers))
            response = await self._client.send(request, stream=True)
        except httpx.InvalidURL as exc:
            raise FatalError(f"Invalid link: {exc}") from exc
        except httpx.UnsupportedProtocol as exc:
            raise FatalError("Unsupported link type. Use http:// or https://") from exc
        except httpx.TooManyRedirects as exc:
            raise FatalError("Too many redirects") from exc
        except httpx.TimeoutException as exc:
            raise NetworkError("Connection timed out") from exc
        except httpx.ProxyError as exc:
            raise NetworkError(f"Proxy error: {exc}") from exc
        except (httpx.TransportError, httpx.RequestError, OSError) as exc:
            raise NetworkError(_describe(exc)) from exc
        return _HttpxResponse(response, httpx)

    async def aclose(self) -> None:
        try:
            await self._client.aclose()
        except Exception:
            pass


def _describe(exc: BaseException) -> str:
    text = str(exc).strip()
    return f"Connection problem: {text}" if text else f"Connection problem ({type(exc).__name__})"


class _HttpxResponse:
    def __init__(self, response, httpx_module):
        self._response = response
        self._httpx = httpx_module
        self.status: int = response.status_code
        self.headers = response.headers
        self.url: str = str(response.url)

    async def iter_chunks(self) -> AsyncIterator[bytes]:
        httpx = self._httpx
        try:
            async for chunk in self._response.aiter_raw():
                if chunk:
                    yield chunk
        except httpx.TimeoutException as exc:
            raise NetworkError("Connection timed out") from exc
        except (httpx.TransportError, httpx.RequestError, OSError) as exc:
            raise NetworkError(_describe(exc)) from exc

    async def aclose(self) -> None:
        try:
            await self._response.aclose()
        except Exception:
            pass


def make_httpx_transport(cfg: NetworkConfig, username: str = "", password: str = "",
                         max_connections: int = 8) -> HttpxTransport:
    return HttpxTransport(cfg, username=username, password=password, max_connections=max_connections)
