"""Base interface for platform-specific conditional DNS backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import re
from typing import Optional

from ..profiles import DnsProfile, get_hosts_pinned_domains


HOSTS_START_MARKER = "# >>> FASTDNS-MANAGED-START >>>"
HOSTS_END_MARKER = "# <<< FASTDNS-MANAGED-END <<<"


def build_hosts_block(profile: DnsProfile) -> str:
    """Build the managed /etc/hosts block pinning Gemini & Antigravity endpoints to the profile IP."""
    proxy_ip = profile.primary_dns.split("#", 1)[0].split(":", 1)[0].strip()
    pinned = get_hosts_pinned_domains(profile.domains)
    lines = [
        HOSTS_START_MARKER,
        f"# Profile: {profile.name} ({proxy_ip})",
    ]
    for host in pinned:
        lines.append(f"{proxy_ip}\t{host}")
    lines.append(HOSTS_END_MARKER)
    return "\n".join(lines) + "\n"


def update_hosts_content(existing_content: str, profile: Optional[DnsProfile]) -> str:
    """Insert, replace, or remove the FastDNS managed block in hosts file text."""
    pattern = re.compile(
        r"\n?" + re.escape(HOSTS_START_MARKER) + r".*?" + re.escape(HOSTS_END_MARKER) + r"\n?",
        re.DOTALL,
    )
    cleaned = pattern.sub("\n", existing_content).rstrip() + "\n"
    if profile is None:
        return cleaned
    return cleaned + "\n" + build_hosts_block(profile)


@dataclass
class BackendStatus:
    """Represents the live state of DNS routing on the OS."""

    enabled: bool
    mode: str       # "native", "hybrid", or "inactive"
    scope: str = "conditional"  # "conditional" or "global"
    active_profile_name: str = ""
    interface_or_policy: str = ""
    details: str = ""
    proxy_running: bool = False


class DnsBackend(ABC):
    """Abstract base class for Linux and Windows DNS backends."""

    @abstractmethod
    def get_status(self, current_profile: Optional[DnsProfile] = None) -> BackendStatus:
        """Inspect OS state and return whether FastDNS is active."""

    @abstractmethod
    def enable(
        self,
        profile: DnsProfile,
        mode: str = "native",
        scope: str = "conditional",
    ) -> BackendStatus:
        """Enable DNS routing for the given profile, mode ('native'/'hybrid') and scope ('conditional'/'global')."""

    @abstractmethod
    def disable(self) -> BackendStatus:
        """Disable DNS routing and restore default OS DNS resolution."""
