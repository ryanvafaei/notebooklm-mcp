"""Egress guard tests.

Audit hooks can't be removed once installed, so every check that installs the guard
runs in a fresh Python subprocess (the parent pytest process stays unguarded).
"""

import json
import os
import subprocess
import sys
import textwrap

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from notebooklm_study_mcp.netguard import is_allowed_host

PROXY_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "NO_PROXY",
    "no_proxy",
)


def run_guarded(code: str, *, drop_proxies: bool = False) -> dict:
    env = dict(os.environ)
    if drop_proxies:
        for var in PROXY_VARS:
            env.pop(var, None)
    script = "import json\nfrom notebooklm_study_mcp import netguard\nnetguard.install()\n"
    script += "results = {}\n" + textwrap.dedent(code) + "\nprint(json.dumps(results))\n"
    proc = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=60, env=env
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize(
    "host",
    [
        "notebooklm.google.com",
        "accounts.google.com",
        "google.com",
        "www.googleapis.com",
        "notebooklm-pa.googleapis.com",
        "lh3.googleusercontent.com",
        "fonts.gstatic.com",
        "accounts.google.co.uk",
        "www.google.com.sg",
        "google.de",
        "localhost",
        "127.0.0.1",
        "::1",
        None,
        b"accounts.google.com",
        b"notebook.google.com",
        "notebook.google.com",
    ],
)
def test_allowed_hosts(host):
    assert is_allowed_host(host)


@pytest.mark.parametrize(
    "host",
    [
        "example.com",
        "pypi.org",
        "api.anthropic.com",
        "github.com",
        "evilgoogle.com",
        "google.com.evil.net",
        "notgoogleapis.com",
        "googleapis.com.attacker.io",
        "google.evil",
        "8.8.8.8",
        "192.168.1.1",
        "10.0.0.1",
        "proxy.corp.local",
        b"example.com",
        b"\xff\xfe.google.com",
    ],
)
def test_blocked_hosts(host):
    assert not is_allowed_host(host)


def test_guard_blocks_non_google_traffic_and_spawning():
    results = run_guarded(
        """
        import asyncio, socket, subprocess
        from notebooklm_study_mcp.netguard import EgressBlocked

        def outcome(fn):
            try:
                fn()
                return "allowed"
            except EgressBlocked:
                return "blocked"
            except OSError as exc:  # allowed by the guard, failed for network reasons
                return "allowed-neterr"

        results["dns_example"] = outcome(lambda: socket.getaddrinfo("example.com", 443))
        results["raw_ip_create_conn"] = outcome(
            lambda: socket.create_connection(("93.184.215.14", 80), timeout=3))
        def raw_connect():
            s = socket.socket()
            s.settimeout(3)
            try:
                s.connect(("1.1.1.1", 53))
            finally:
                s.close()
        results["raw_ip_connect"] = outcome(raw_connect)
        results["udp_sendto"] = outcome(
            lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b"x", ("8.8.8.8", 53)))
        results["spawn"] = outcome(lambda: subprocess.run(["echo", "hi"]))

        import httpx
        try:
            httpx.get("https://example.com", timeout=5, trust_env=False)
            results["httpx_example"] = "allowed"
        except Exception as exc:
            chain, e = [], exc
            while e is not None:
                chain.append(type(e).__name__)
                e = e.__cause__ or e.__context__
            results["httpx_example"] = "blocked" if "EgressBlocked" in chain else repr(exc)

        # Loopback keeps working (asyncio internals, local tests).
        srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
        results["loopback"] = outcome(
            lambda: socket.create_connection(srv.getsockname(), timeout=3).close())

        async def work():
            await asyncio.sleep(0)
            return await asyncio.to_thread(lambda: 42)
        results["asyncio"] = asyncio.run(work())

        results["dns_google"] = outcome(
            lambda: socket.getaddrinfo("notebooklm.google.com", 443))
        """
    )
    assert results["dns_example"] == "blocked"
    assert results["raw_ip_create_conn"] == "blocked"
    assert results["raw_ip_connect"] == "blocked"
    assert results["udp_sendto"] == "blocked"
    assert results["spawn"] == "blocked"
    assert results["httpx_example"] == "blocked"
    assert results["loopback"] == "allowed"
    assert results["asyncio"] == 42
    assert results["dns_google"] in ("allowed", "allowed-neterr")


def test_guard_blocks_proxies():
    results = run_guarded(
        """
        import httpx
        try:
            httpx.get("https://notebooklm.google.com", timeout=5,
                      proxy="http://corp-proxy.example.net:3128")
            results["via_proxy"] = "allowed"
        except Exception as exc:
            results["via_proxy"] = "blocked" if "only talks to Google" in repr(exc) or \
                "EgressBlocked" in repr(exc.__cause__) + repr(exc.__context__) else repr(exc)
        """
    )
    assert results["via_proxy"] == "blocked"


def test_real_https_to_google_passes_guard():
    """Real httpx + system TLS through the guard (meaningful on CI with direct internet)."""
    results = run_guarded(
        """
        import httpx
        from notebooklm_study_mcp.netguard import EgressBlocked
        try:
            r = httpx.get("https://notebooklm.google.com/", timeout=10)
            results["status"] = r.status_code
        except Exception as exc:
            e, blocked = exc, False
            while e is not None:
                blocked = blocked or isinstance(e, EgressBlocked)
                e = e.__cause__ or e.__context__
            results["status"] = "blocked" if blocked else "neterr"
        """,
        drop_proxies=True,
    )
    if results["status"] == "neterr":
        pytest.skip("no direct internet access in this environment")
    assert results["status"] != "blocked"
    assert isinstance(results["status"], int)


async def test_stdio_server_runs_with_guard(tmp_path):
    """The real entry point (as Claude Desktop runs it) installs the guard and works."""
    env = {k: v for k, v in os.environ.items() if k not in PROXY_VARS}
    env.update(NOTEBOOKLM_HOME=str(tmp_path / "nlm"), NOTEBOOKLM_STUDY_HOME=str(tmp_path / "s"))
    transport = StdioTransport(command=sys.executable, args=["-m", "notebooklm_study_mcp"], env=env)
    async with Client(transport) as c:
        status = (await c.call_tool("auth_status", {})).data
        assert status["network"] == "Google-only egress guard active"
        assert status["logged_in"] is False
        assert "notebooklm login" in status["problem"]
        names = {t.name for t in await c.list_tools()}
        assert "build_study_pack" in names
