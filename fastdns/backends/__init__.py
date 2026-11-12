"""Platform backend factory for FastDNS."""

from __future__ import annotations

import sys
from typing import Callable, Optional

from .base import BackendStatus, DnsBackend
from .linux import LinuxDnsBackend
from .windows import WindowsDnsBackend


def create_backend(
    on_query_log: Optional[Callable[[str, str], None]] = None,
) -> DnsBackend:
    """Create the appropriate OS conditional DNS backend for the current platform."""
    if sys.platform == "win32":
        return WindowsDnsBackend(on_query_log=on_query_log)
    return LinuxDnsBackend(on_query_log=on_query_log)


__all__ = [
    "BackendStatus",
    "DnsBackend",
    "LinuxDnsBackend",
    "WindowsDnsBackend",
    "create_backend",
]
