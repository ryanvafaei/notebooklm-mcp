"""Egress guard: this server process may talk to Google only.

Installed once at startup by ``server.main()``. It enforces three rules for the whole
process (every thread, every library):

1. **DNS allowlist.** ``socket.getaddrinfo`` only resolves Google hostnames
   (``google.com``, ``googleapis.com``, ``googleusercontent.com``, ``gstatic.com``,
   regional ``google.<cc>``) and loopback. Anything else raises :class:`EgressBlocked`.
2. **Connect allowlist.** A socket may only connect to loopback, a local UNIX socket,
   or an IP address that was just resolved from an allowed Google hostname. Raw-IP
   connections and connections to proxies or any other server are refused.
3. **No child processes.** Spawning programs is refused, so nothing can sidestep the
   guard by running another process.

It uses Python audit hooks (PEP 578), which cannot be removed once installed. All HTTP in
this process goes through Python sockets (notebooklm-py uses httpx; the optional
curl_cffi transport is not installed), so the guard sees every connection.

Consequences, by design:
- If your network forces traffic through an HTTP proxy, the server refuses to use it
  (a proxy is another server) and tells you why.
- ``notebooklm login`` is a separate command that opens a normal browser to sign in to
  Google; the guard covers the MCP server that Claude Desktop runs.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
import sys
import threading
from typing import Any

logger = logging.getLogger(__name__)

ALLOWED_SUFFIXES = (
    "google.com",
    "googleapis.com",
    "googleusercontent.com",
    "gstatic.com",
)
# Regional Google domains used for cookies/auth: google.de, google.co.uk, google.com.sg ...
_REGIONAL_GOOGLE = re.compile(r"^(?:[a-z0-9-]+\.)*google\.(?:co\.|com\.)?[a-z]{2}$")
_LOOPBACK_NAMES = {"localhost"}

_SPAWN_EVENTS = {
    "subprocess.Popen",
    "os.system",
    "os.exec",
    "os.posix_spawn",
    "os.spawn",
    "os.startfile",
    "os.fork",
    "os.forkpty",
    "pty.spawn",
}


class EgressBlocked(PermissionError):
    """Raised when code in this process tries to reach a non-Google destination."""


def is_allowed_host(host: str | bytes | None) -> bool:
    if host is None:
        return True  # getaddrinfo(None, port) = local wildcard address for binding
    if isinstance(host, bytes | bytearray):
        try:
            host = bytes(host).decode("ascii")  # httpx/anyio pass hostnames as bytes
        except UnicodeDecodeError:
            try:
                host = bytes(host).decode("idna")
            except UnicodeError:
                return False
    host = host.strip().lower().rstrip(".")
    if host in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        pass
    if any(host == s or host.endswith("." + s) for s in ALLOWED_SUFFIXES):
        return True
    return bool(_REGIONAL_GOOGLE.match(host))


class _Guard:
    def __init__(self) -> None:
        self.resolved: set[str] = set()
        self.lock = threading.Lock()
        self.real_getaddrinfo = socket.getaddrinfo

    def getaddrinfo(self, host: Any, *args: Any, **kwargs: Any) -> Any:
        if not is_allowed_host(host):
            raise EgressBlocked(_blocked_message(str(host)))
        infos = self.real_getaddrinfo(host, *args, **kwargs)
        with self.lock:
            for info in infos:
                sockaddr = info[4]
                if isinstance(sockaddr, tuple) and sockaddr:
                    self.resolved.add(str(sockaddr[0]).split("%", 1)[0])
        return infos

    def ip_allowed(self, address: Any) -> bool:
        if not isinstance(address, tuple) or not address:
            return True  # AF_UNIX path or other local address family
        ip = str(address[0]).split("%", 1)[0]
        try:
            if ipaddress.ip_address(ip).is_loopback:
                return True
        except ValueError:
            return False  # an unresolved hostname passed straight to connect()
        with self.lock:
            return ip in self.resolved

    def audit(self, event: str, args: tuple[Any, ...]) -> None:
        if event in ("socket.connect", "socket.sendto"):
            address = args[1] if event == "socket.connect" else args[-1]
            if not self.ip_allowed(address):
                raise EgressBlocked(_blocked_message(str(address[0])))
        elif event == "socket.getaddrinfo":
            # Belt and braces for callers holding a pre-patch reference to getaddrinfo.
            if args and not is_allowed_host(args[0]):
                raise EgressBlocked(_blocked_message(str(args[0])))
        elif event in _SPAWN_EVENTS:
            raise EgressBlocked(
                "This NotebookLM server is not allowed to start other programs "
                "(local-only egress guard)."
            )


def _blocked_message(target: str) -> str:
    logger.warning("Blocked network access to non-Google destination: %s", target[:100])
    return (
        f"Blocked connection to '{target[:100]}': this NotebookLM server only talks to Google. "
        "If your network forces traffic through an HTTP proxy, the server refuses to use it."
    )


_installed: _Guard | None = None


def install() -> None:
    """Install the guard for the rest of this process's life (idempotent)."""
    global _installed
    if _installed is not None:
        return
    guard = _Guard()
    socket.getaddrinfo = guard.getaddrinfo  # type: ignore[assignment]
    sys.addaudithook(guard.audit)
    _installed = guard
    logger.info("Egress guard active: Google-only network access, no child processes")


def is_installed() -> bool:
    return _installed is not None
