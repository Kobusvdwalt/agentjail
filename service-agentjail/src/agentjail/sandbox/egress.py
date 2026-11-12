"""Allowlisted network egress for sandboxes without direct network access.

A sandbox created with `network: false` has its own network namespace with
only a loopback interface. When `AGENTJAIL_NETWORK_ALLOW` lists any hosts, each
command also gets a Unix socket bind-mounted into the jail, and the
`agentjail-egress` forwarder inside the jail exposes it as an HTTP proxy on
loopback (`HTTP_PROXY` / `HTTPS_PROXY`). This module is the other end of that
socket: an HTTP proxy, outside the jail, that only connects to allowlisted
hosts.

Patterns:

- `api.example.com` — exactly that host, on ports 80 and 443
- `*.example.com` — any subdomain, at any depth, but not `example.com` itself
- `*` — any host
- a `:port` suffix (`smtp.example.com:587`) replaces the default ports

The proxy resolves the host itself and connects to the address it resolved,
so a name cannot be re-pointed between the check and the connection. Hosts
that resolve to link-local addresses (cloud metadata), multicast, unspecified
or cloud platform endpoints are always refused; private, loopback and other
non-public addresses are refused unless `AGENTJAIL_NETWORK_ALLOW_PRIVATE` is
set. HTTPS is tunnelled with CONNECT and never decrypted.
"""

import asyncio
import ipaddress
import logging
import re
import secrets
import socket
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

DEFAULT_PORTS = frozenset({80, 443})

_LABEL = r"[a-z0-9_](?:[a-z0-9_-]*[a-z0-9_])?"
_PATTERN = re.compile(
    rf"(?P<host>\*|(?:\*\.)?{_LABEL}(?:\.{_LABEL})*)(?::(?P<port>[0-9]{{1,5}}))?"
)
_HEAD_LIMIT = 16_384
_TIMEOUT_SECONDS = 10
_ALWAYS_DENIED = (
    # Azure's platform endpoint (wireserver, DNS, health probes) is a public
    # address that every VM and pod can reach.
    ipaddress.ip_network("168.63.129.16/32"),
)


@dataclass(frozen=True)
class HostRule:
    host: str
    port: int | None = None

    def matches(self, host: str, port: int) -> bool:
        if port not in ((self.port,) if self.port else DEFAULT_PORTS):
            return False
        if self.host == "*":
            return True
        if self.host.startswith("*."):
            return host.endswith(self.host[1:])
        return host == self.host


def parse_rule(pattern: str) -> HostRule:
    match = _PATTERN.fullmatch(pattern.strip().lower())
    port = int(match["port"]) if match and match["port"] else None
    if not match or port == 0 or (port and port > 65_535):
        raise ValueError(
            f"Invalid network allow pattern {pattern!r}: use a host name, "
            "'*.domain' or '*', optionally followed by ':port'"
        )
    return HostRule(match["host"], port)


def normalize_host(host: str) -> str:
    return host.strip().lower().rstrip(".")


@dataclass(frozen=True)
class EgressPolicy:
    rules: tuple[HostRule, ...]
    allow_private: bool = False

    @classmethod
    def from_patterns(
        cls, patterns: Iterable[str], allow_private: bool = False
    ) -> "EgressPolicy":
        return cls(tuple(parse_rule(p) for p in patterns), allow_private)

    def permits(self, host: str, port: int) -> bool:
        host = normalize_host(host)
        return any(rule.matches(host, port) for rule in self.rules)

    def permits_address(self, address: str) -> bool:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            return False
        if any(ip in network for network in _ALWAYS_DENIED):
            return False
        return ip.is_global or self.allow_private


class _Refused(Exception):
    def __init__(self, status: int, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.reason = reason
        self.detail = detail


class EgressProxy:
    """One proxy per command, listening on that command's Unix socket."""

    def __init__(self, policy: EgressPolicy) -> None:
        self.policy = policy
        self._tasks: set[asyncio.Task] = set()

    async def handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        task = asyncio.current_task()
        self._tasks.add(task)
        try:
            await self._handle(reader, writer)
        except _Refused as refused:
            await _reply(writer, refused)
        except ConnectionError, OSError:
            pass
        finally:
            self._tasks.discard(task)
            writer.close()

    async def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            head = await asyncio.wait_for(
                reader.readuntil(b"\r\n\r\n"), _TIMEOUT_SECONDS
            )
        except asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError:
            raise _Refused(400, "Bad Request", "malformed proxy request")

        request_line, _, headers = head.partition(b"\r\n")
        try:
            method, target, version = request_line.decode("ascii").split(" ")
        except UnicodeDecodeError, ValueError:
            raise _Refused(400, "Bad Request", "malformed request line")

        tunnel = method.upper() == "CONNECT"
        url = urlsplit(f"//{target}" if tunnel else target)
        try:
            host, port = url.hostname, url.port or (None if tunnel else 80)
        except ValueError:
            raise _Refused(400, "Bad Request", "invalid port")
        if not host or not port or (not tunnel and url.scheme != "http"):
            raise _Refused(
                400,
                "Bad Request",
                "send http:// URLs through the proxy and tunnel https with CONNECT",
            )

        host = normalize_host(host)
        if not self.policy.permits(host, port):
            logger.info("egress refused: %s:%d is not allowlisted", host, port)
            raise _Refused(
                403,
                "Forbidden",
                f"{host}:{port} is not in the sandbox network allowlist",
            )

        upstream_reader, upstream_writer = await self._connect(host, port)
        logger.info("egress allowed: %s:%d", host, port)
        try:
            if tunnel:
                writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await writer.drain()
            else:
                path = url.path or "/"
                if url.query:
                    path = f"{path}?{url.query}"
                upstream_writer.write(
                    f"{method} {path} {version}\r\n".encode("ascii")
                    + _without_proxy_headers(headers)
                )
                await upstream_writer.drain()
            await asyncio.gather(
                _pipe(reader, upstream_writer), _pipe(upstream_reader, writer)
            )
        finally:
            upstream_writer.close()

    async def _connect(
        self, host: str, port: int
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        loop = asyncio.get_running_loop()
        try:
            infos = await asyncio.wait_for(
                loop.getaddrinfo(host, port, type=socket.SOCK_STREAM),
                _TIMEOUT_SECONDS,
            )
        except OSError, TimeoutError:
            raise _Refused(502, "Bad Gateway", f"could not resolve {host}")

        addresses = list(dict.fromkeys(str(info[4][0]) for info in infos))
        if not all(self.policy.permits_address(address) for address in addresses):
            logger.info("egress refused: %s resolves to a blocked address", host)
            raise _Refused(
                403,
                "Forbidden",
                f"{host} resolves to an address sandboxes cannot reach",
            )

        for address in addresses:
            try:
                return await asyncio.wait_for(
                    asyncio.open_connection(address, port), _TIMEOUT_SECONDS
                )
            except OSError, TimeoutError:
                continue
        raise _Refused(502, "Bad Gateway", f"could not connect to {host}:{port}")


def _without_proxy_headers(headers: bytes) -> bytes:
    return b"".join(
        line
        for line in headers.splitlines(keepends=True)
        if not line.lower().startswith(b"proxy-")
    )


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65_536):
            writer.write(data)
            await writer.drain()
        if writer.can_write_eof():
            writer.write_eof()
    except ConnectionError, OSError:
        writer.close()


async def _reply(writer: asyncio.StreamWriter, refused: _Refused) -> None:
    body = f"agentjail: {refused.detail}\n".encode()
    writer.write(
        f"HTTP/1.1 {refused.status} {refused.reason}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n\r\n".encode()
        + body
    )
    try:
        await writer.drain()
    except ConnectionError, OSError:
        pass


@asynccontextmanager
async def serve(policy: EgressPolicy, socket_dir: Path) -> AsyncIterator[Path]:
    """Listen on a fresh Unix socket for the duration of one command."""
    socket_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = socket_dir / f"{secrets.token_hex(8)}.sock"
    proxy = EgressProxy(policy)
    server = await asyncio.start_unix_server(proxy.handle, path, limit=_HEAD_LIMIT)
    # The jail's user reaches the socket only through its bind mount.
    path.chmod(0o666)
    try:
        yield path
    finally:
        server.close()
        # Cancelling the handlers closes their connections; uvloop's Server has
        # no close_clients().
        await proxy.close()
        await server.wait_closed()
        path.unlink(missing_ok=True)
