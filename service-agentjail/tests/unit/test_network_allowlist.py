"""Allowlisted egress: which hosts a sandbox may reach, and that nothing else is."""

import asyncio
import shutil
import socket
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentjail.config import AgentjailSettings
from agentjail.sandbox import egress, nsjail
from agentjail.sandbox.egress import EgressPolicy, HostRule, parse_rule
from agentjail.sandbox.manager import SandboxManager
from agentjail.sandbox.models import ExecResult, SandboxConfig, SandboxState
from agentjail.sandbox.nsjail import NsjailRunner

FORWARDER_SOURCE = Path(__file__).parents[2] / "native" / "agentjail_egress.c"


class TestPatterns:
    def test_exact_host_on_default_ports(self):
        policy = EgressPolicy.from_patterns(["api.github.com"])
        assert policy.permits("api.github.com", 443)
        assert policy.permits("api.github.com", 80)
        assert not policy.permits("api.github.com", 22)
        assert not policy.permits("github.com", 443)
        assert not policy.permits("evil.api.github.com", 443)

    def test_wildcard_matches_subdomains_at_any_depth(self):
        policy = EgressPolicy.from_patterns(["*.googleapis.com"])
        assert policy.permits("storage.googleapis.com", 443)
        assert policy.permits("a.b.googleapis.com", 443)
        assert not policy.permits("googleapis.com", 443)
        assert not policy.permits("evilgoogleapis.com", 443)
        assert not policy.permits("googleapis.com.evil.net", 443)

    def test_star_matches_any_host(self):
        policy = EgressPolicy.from_patterns(["*"])
        assert policy.permits("example.com", 443)
        assert not policy.permits("example.com", 8080)

    def test_explicit_port_replaces_the_defaults(self):
        policy = EgressPolicy.from_patterns(["smtp.example.com:587", "*:8443"])
        assert policy.permits("smtp.example.com", 587)
        assert not policy.permits("smtp.example.com", 443)
        assert policy.permits("anything.example.org", 8443)

    def test_hosts_are_compared_case_insensitively_without_trailing_dot(self):
        policy = EgressPolicy.from_patterns(["API.Example.com"])
        assert policy.permits("api.EXAMPLE.com.", 443)

    def test_underscores_are_valid_for_compose_service_names(self):
        assert parse_rule("service_api:3001") == HostRule("service_api", 3001)

    def test_no_patterns_permit_nothing(self):
        assert not EgressPolicy.from_patterns([]).permits("example.com", 443)

    @pytest.mark.parametrize(
        "pattern",
        [
            "",
            "api.*.com",
            "*example.com",
            "**.example.com",
            "https://example.com",
            "example.com/path",
            "example.com:0",
            "example.com:70000",
            "-bad.example.com",
        ],
    )
    def test_invalid_patterns_are_rejected(self, pattern):
        with pytest.raises(ValueError, match="Invalid network allow pattern"):
            parse_rule(pattern)

    def test_settings_reject_an_invalid_pattern_at_startup(self):
        with pytest.raises(ValidationError):
            AgentjailSettings(network_allow=["api.*.com"])


class TestAddresses:
    @pytest.mark.parametrize(
        "address",
        ["169.254.169.254", "fe80::1", "224.0.0.1", "0.0.0.0", "168.63.129.16"],
    )
    def test_metadata_and_platform_addresses_are_always_blocked(self, address):
        assert not EgressPolicy((), allow_private=True).permits_address(address)

    @pytest.mark.parametrize(
        "address",
        ["10.0.0.1", "172.16.0.1", "192.168.1.1", "127.0.0.1", "::1", "100.64.0.1"],
    )
    def test_private_addresses_need_the_private_opt_in(self, address):
        assert not EgressPolicy(()).permits_address(address)
        assert EgressPolicy((), allow_private=True).permits_address(address)

    def test_ipv4_mapped_ipv6_is_checked_as_ipv4(self):
        assert not EgressPolicy(()).permits_address("::ffff:10.0.0.1")
        assert not EgressPolicy((), allow_private=True).permits_address(
            "::ffff:169.254.169.254"
        )

    def test_public_addresses_are_reachable(self):
        assert EgressPolicy(()).permits_address("8.8.8.8")
        assert EgressPolicy(()).permits_address("2001:4860:4860::8888")


@pytest.fixture
def socket_dir():
    # Unix socket paths are limited to ~104 bytes; pytest's tmp_path is too long on macOS.
    path = Path(tempfile.mkdtemp(prefix="aj-", dir="/tmp"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
async def upstream():
    """A loopback server that records the request head and echoes the rest."""
    received: list[bytes] = []

    async def handle(reader, writer):
        head = await reader.readuntil(b"\r\n\r\n")
        received.append(head)
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
        await writer.drain()
        while data := await reader.read(1024):
            writer.write(data)
            await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    yield port, received
    server.close()
    await server.wait_closed()


async def _request(
    path: Path, head: bytes
) -> tuple[bytes, asyncio.StreamReader, asyncio.StreamWriter]:
    reader, writer = await asyncio.open_unix_connection(path)
    writer.write(head)
    await writer.drain()
    status = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
    return status, reader, writer


class TestProxy:
    async def test_connect_tunnels_to_an_allowlisted_host(self, socket_dir, upstream):
        port, received = upstream
        policy = EgressPolicy.from_patterns([f"localhost:{port}"], allow_private=True)
        async with egress.serve(policy, socket_dir) as path:
            status, reader, writer = await _request(
                path, f"CONNECT localhost:{port} HTTP/1.1\r\n\r\n".encode()
            )
            assert status.startswith(b"HTTP/1.1 200")
            writer.write(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\nping")
            await writer.drain()
            expected = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nokping"
            reply = await asyncio.wait_for(reader.readexactly(len(expected)), 5)
            assert reply == expected
            writer.close()
        assert received == [b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n"]

    async def test_plain_http_is_forwarded_in_origin_form(self, socket_dir, upstream):
        port, received = upstream
        policy = EgressPolicy.from_patterns([f"localhost:{port}"], allow_private=True)
        async with egress.serve(policy, socket_dir) as path:
            status, _, writer = await _request(
                path,
                f"GET http://localhost:{port}/a?b=1 HTTP/1.1\r\n"
                f"Host: localhost:{port}\r\nProxy-Authorization: Basic x\r\n"
                "Proxy-Connection: keep-alive\r\n\r\n".encode(),
            )
            assert status.startswith(b"HTTP/1.1 200")
            writer.close()
        assert received == [
            f"GET /a?b=1 HTTP/1.1\r\nHost: localhost:{port}\r\n\r\n".encode()
        ]

    async def test_a_host_outside_the_allowlist_is_refused(self, socket_dir, upstream):
        port, received = upstream
        policy = EgressPolicy.from_patterns(["api.example.com"], allow_private=True)
        async with egress.serve(policy, socket_dir) as path:
            status, reader, writer = await _request(
                path, f"CONNECT localhost:{port} HTTP/1.1\r\n\r\n".encode()
            )
            body = await reader.read()
            writer.close()
        assert status.startswith(b"HTTP/1.1 403")
        assert (
            f"localhost:{port} is not in the sandbox network allowlist".encode() in body
        )
        assert received == []

    async def test_a_port_outside_the_allowlist_is_refused(self, socket_dir):
        policy = EgressPolicy.from_patterns(["localhost"], allow_private=True)
        async with egress.serve(policy, socket_dir) as path:
            status, _, writer = await _request(
                path, b"CONNECT localhost:22 HTTP/1.1\r\n\r\n"
            )
            writer.close()
        assert status.startswith(b"HTTP/1.1 403")

    async def test_an_allowlisted_name_resolving_to_a_private_address_is_refused(
        self, socket_dir, upstream
    ):
        port, received = upstream
        policy = EgressPolicy.from_patterns([f"localhost:{port}"])
        async with egress.serve(policy, socket_dir) as path:
            status, reader, writer = await _request(
                path, f"CONNECT localhost:{port} HTTP/1.1\r\n\r\n".encode()
            )
            body = await reader.read()
            writer.close()
        assert status.startswith(b"HTTP/1.1 403")
        assert b"resolves to an address sandboxes cannot reach" in body
        assert received == []

    async def test_metadata_is_refused_even_when_allowlisted(self, socket_dir):
        policy = EgressPolicy.from_patterns(["169.254.169.254"], allow_private=True)
        async with egress.serve(policy, socket_dir) as path:
            status, _, writer = await _request(
                path, b"GET http://169.254.169.254/metadata HTTP/1.1\r\n\r\n"
            )
            writer.close()
        assert status.startswith(b"HTTP/1.1 403")

    @pytest.mark.parametrize(
        "head",
        [
            b"GET https://example.com/ HTTP/1.1\r\n\r\n",
            b"GET / HTTP/1.1\r\nHost: example.com\r\n\r\n",
            b"nonsense\r\n\r\n",
            b"CONNECT example.com:http HTTP/1.1\r\n\r\n",
        ],
    )
    async def test_malformed_requests_are_rejected(self, socket_dir, head):
        policy = EgressPolicy.from_patterns(["*"])
        async with egress.serve(policy, socket_dir) as path:
            status, _, writer = await _request(path, head)
            writer.close()
        assert status.startswith(b"HTTP/1.1 400")

    async def test_closing_removes_the_socket_and_ends_open_tunnels(
        self, socket_dir, upstream
    ):
        port, _ = upstream
        policy = EgressPolicy.from_patterns([f"localhost:{port}"], allow_private=True)
        async with egress.serve(policy, socket_dir) as path:
            status, reader, writer = await _request(
                path, f"CONNECT localhost:{port} HTTP/1.1\r\n\r\n".encode()
            )
            assert status.startswith(b"HTTP/1.1 200")
        assert not path.exists()
        assert await asyncio.wait_for(reader.read(), 5) == b""
        writer.close()


@pytest.fixture(scope="module")
def forwarder(tmp_path_factory):
    binary = tmp_path_factory.mktemp("bin") / "agentjail-egress"
    subprocess.run(
        ["cc", "-O2", "-Wall", "-Werror", "-o", str(binary), str(FORWARDER_SOURCE)],
        check=True,
    )
    return binary


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class TestForwarder:
    """The in-jail half, run here without a jail: loopback port → Unix socket."""

    def test_it_returns_the_command_status(self, forwarder, socket_dir):
        result = subprocess.run(
            [
                forwarder,
                str(_free_port()),
                str(socket_dir / "x.sock"),
                "--",
                "sh",
                "-c",
                "exit 7",
            ],
            timeout=10,
        )
        assert result.returncode == 7

    def test_it_refuses_bad_arguments(self, forwarder):
        result = subprocess.run(
            [forwarder, "0", "/x", "--", "true"], capture_output=True
        )
        assert result.returncode == 125

    async def test_a_command_reaches_an_allowlisted_host_through_the_proxy(
        self, forwarder, socket_dir, upstream
    ):
        upstream_port, received = upstream
        listen_port = _free_port()
        policy = EgressPolicy.from_patterns(
            [f"localhost:{upstream_port}"], allow_private=True
        )
        client = (
            "import os, urllib.request;"
            "print(urllib.request.urlopen(os.environ['TARGET'], timeout=5).read().decode())"
        )
        async with egress.serve(policy, socket_dir) as path:
            proc = await asyncio.create_subprocess_exec(
                forwarder,
                str(listen_port),
                str(path),
                "--",
                sys.executable,
                "-c",
                client,
                env={
                    "HTTP_PROXY": f"http://127.0.0.1:{listen_port}",
                    "TARGET": f"http://localhost:{upstream_port}/hello",
                },
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), 15)
        assert proc.returncode == 0, stderr.decode()
        assert stdout.decode().strip() == "ok"
        assert received[0].startswith(b"GET /hello HTTP/1.1\r\n")


def _sandbox(tmp_path, network=False) -> SandboxState:
    now = datetime.now(timezone.utc)
    return SandboxState(
        id="sandbox",
        status="running",
        config=SandboxConfig(network=network, resources=[]),
        root_dir=str(tmp_path / "root"),
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def allowlisted(settings, socket_dir, tmp_path):
    binary = tmp_path / "agentjail-egress"
    binary.write_text("")
    settings.network_allow = ["api.example.com"]
    settings.egress_bin = str(binary)
    settings.egress_socket_dir = socket_dir
    return settings


class TestNsjailWiring:
    def test_without_an_allowlist_commands_are_unchanged(self, settings, tmp_path):
        args = NsjailRunner(settings)._build_args(
            _sandbox(tmp_path), ["/bin/sh", "-c", "true"], 5, None, None
        )
        assert not any("egress" in arg or "PROXY" in arg for arg in args)
        assert args[-4:] == ["--", "/bin/sh", "-c", "true"]

    def test_egress_mounts_the_forwarder_and_socket_and_wraps_the_command(
        self, allowlisted, tmp_path
    ):
        socket_path = Path("/tmp/aj/abc.sock")
        args = NsjailRunner(allowlisted)._build_args(
            _sandbox(tmp_path), ["/bin/sh", "-c", "true"], 5, None, None, socket_path
        )
        assert f"{allowlisted.egress_bin}:{nsjail.EGRESS_BIN}" in args
        assert f"{socket_path}:{nsjail.EGRESS_SOCKET}" in args
        assert "HTTPS_PROXY=http://127.0.0.1:3128" in args
        assert "https_proxy=http://127.0.0.1:3128" in args
        assert "--disable_clone_newnet" not in args
        separator = args.index("--")
        assert args[separator + 1 :] == [
            nsjail.EGRESS_BIN,
            "3128",
            nsjail.EGRESS_SOCKET,
            "--",
            "/bin/sh",
            "-c",
            "true",
        ]

    async def test_the_socket_exists_only_while_the_command_runs(
        self, allowlisted, tmp_path, monkeypatch
    ):
        seen: list[list[str]] = []

        async def fake_run(args, **_):
            seen.append(args)
            socket_path = next(
                arg.split(":")[0] for arg in args if arg.endswith(nsjail.EGRESS_SOCKET)
            )
            assert Path(socket_path).is_socket()
            return ExecResult(exit_code=0, stdout="", stderr="")

        monkeypatch.setattr(nsjail, "run_process", fake_run)
        await NsjailRunner(allowlisted).run_command(_sandbox(tmp_path), ["true"])
        assert seen and list(allowlisted.egress_socket_dir.iterdir()) == []

    async def test_full_network_sandboxes_bypass_the_proxy(
        self, allowlisted, tmp_path, monkeypatch
    ):
        seen: list[list[str]] = []

        async def fake_run(args, **_):
            seen.append(args)
            return ExecResult(exit_code=0, stdout="", stderr="")

        monkeypatch.setattr(nsjail, "run_process", fake_run)
        await NsjailRunner(allowlisted).run_command(
            _sandbox(tmp_path, network=True), ["true"]
        )
        assert "--disable_clone_newnet" in seen[0]
        assert not any("PROXY" in arg for arg in seen[0])

    def test_a_missing_forwarder_fails_at_startup(self, allowlisted):
        allowlisted.egress_bin = "/nonexistent/agentjail-egress"
        with pytest.raises(ValueError, match="egress forwarder"):
            NsjailRunner(allowlisted)

    @pytest.mark.parametrize("runner", ["chroot", "bare"])
    def test_other_runners_refuse_an_allowlist(self, allowlisted, runner):
        allowlisted.runner = runner
        with pytest.raises(ValueError, match="requires the nsjail runner"):
            SandboxManager(allowlisted)
