"""Linux conditional and global DNS backend matching official MagicDNS configuration."""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
from typing import Callable, List, Optional

from ..profiles import DnsProfile
from ..resolver import ConditionalDnsProxy
from .base import (
    HOSTS_START_MARKER,
    BackendStatus,
    DnsBackend,
    update_hosts_content,
)


RESOLVED_DROPIN_DIR = "/etc/systemd/resolved.conf.d"
RESOLVED_DROPIN_FILE = "/etc/systemd/resolved.conf.d/magicdns.conf"
LEGACY_DROPIN_FILE = "/etc/systemd/resolved.conf.d/fastdns.conf"
HOSTS_FILE = "/etc/hosts"
HYBRID_PROXY_HOST = "127.0.0.1"
HYBRID_PROXY_PORT = 5354


def _detect_active_links() -> List[str]:
    """Detect active network links that might have competing ~. domain settings."""
    links: List[str] = []
    try:
        proc = subprocess.run(
            ["ip", "-o", "link", "show", "up"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        for line in proc.stdout.splitlines():
            parts = line.split(":")
            if len(parts) >= 2:
                dev = parts[1].strip()
                if not dev.startswith(("lo", "docker", "br-", "veth")):
                    links.append(dev)
    except Exception:
        pass
    return links


def _run_privileged_shell(script: str) -> subprocess.CompletedProcess[str]:
    """Execute a shell snippet with root privileges."""
    if os.geteuid() == 0:
        return subprocess.run(
            ["/bin/sh", "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    sudo_check = subprocess.run(
        ["sudo", "-n", "true"],
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
    )
    if sudo_check.returncode == 0:
        return subprocess.run(
            ["sudo", "-n", "/bin/sh", "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    if shutil.which("pkexec") and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return subprocess.run(
            ["pkexec", "/bin/sh", "-c", script],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    return subprocess.run(
        ["sudo", "/bin/sh", "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


class LinuxDnsBackend(DnsBackend):
    """Manages conditional and global DNS forwarding on Ubuntu/Linux."""

    def __init__(
        self,
        on_query_log: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self.on_query_log = on_query_log
        self._proxy: Optional[ConditionalDnsProxy] = None

    def get_status(self, current_profile: Optional[DnsProfile] = None) -> BackendStatus:
        """Check whether MagicDNS drop-in is active."""
        active_file = None
        for path in (RESOLVED_DROPIN_FILE, LEGACY_DROPIN_FILE):
            if os.path.exists(path):
                active_file = path
                break

        hosts_active = False
        try:
            if os.path.exists(HOSTS_FILE):
                hosts_text = Path(HOSTS_FILE).read_text(encoding="utf-8", errors="ignore")
                hosts_active = HOSTS_START_MARKER in hosts_text
        except Exception:
            pass

        if not active_file and not hosts_active:
            return BackendStatus(
                enabled=False,
                mode="inactive",
                scope="global",
                interface_or_policy="systemd-resolved",
                details="System default DNS active for all traffic",
                proxy_running=bool(self._proxy and self._proxy.is_running),
            )

        dropin_text = ""
        try:
            if active_file:
                dropin_text = Path(active_file).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            pass

        is_hybrid = f"{HYBRID_PROXY_HOST}:{HYBRID_PROXY_PORT}" in dropin_text
        mode = "hybrid" if is_hybrid else "native"
        is_conditional = "Domains=~" in dropin_text and "Domains=~." not in dropin_text
        scope = "conditional" if is_conditional else "global"
        profile_name = current_profile.name if current_profile else "MagicDNS"

        if scope == "global":
            servers_str = " & ".join(current_profile.dns_servers) if current_profile else "DoT"
            details = f"{profile_name} active (DoT: {servers_str}, DNSOverTLS=yes)"
        else:
            details = f"Google, Gemini & Antigravity via {profile_name} (conditional mode)"

        return BackendStatus(
            enabled=True,
            mode=mode,
            scope=scope,
            active_profile_name=profile_name,
            interface_or_policy="/etc/systemd/resolved.conf.d/magicdns.conf",
            details=details,
            proxy_running=bool(self._proxy and self._proxy.is_running),
        )

    def enable(
        self,
        profile: DnsProfile,
        mode: str = "native",
        scope: str = "global",
    ) -> BackendStatus:
        """Enable MagicDNS on systemd-resolved."""
        if not shutil.which("resolvectl"):
            raise RuntimeError(
                "systemd-resolved (resolvectl) was not found. "
                "Please ensure systemd-resolved is installed and active."
            )

        if mode == "hybrid":
            self._start_proxy(profile)
            dns_servers = [f"{HYBRID_PROXY_HOST}:{HYBRID_PROXY_PORT}"]
            fallback_servers = "1.1.1.1 8.8.8.8"
            dot_mode = "no"
            domain_line = ""
        else:
            self._stop_proxy()
            dns_servers = profile.linux_resolved_servers
            fallback_servers = "1.1.1.1 8.8.8.8"
            dot_mode = "yes"
            if scope == "conditional":
                route_domains = [f"~{d.lstrip('.').lstrip('~')}" for d in profile.domains if d.strip()]
                domain_line = f"Domains={' '.join(route_domains)}\n"
            else:
                domain_line = ""

        # Matches official DNS instruction when scope is global:
        # [Resolve]
        # DNS=217.144.190.216#api.magicinfo.art 109.120.187.249#api.magicinfo.art
        # FallbackDNS=1.1.1.1 8.8.8.8
        # DNSOverTLS=yes
        dropin_content = (
            "[Resolve]\n"
            f"DNS={' '.join(dns_servers)}\n"
            f"FallbackDNS={fallback_servers}\n"
            f"{domain_line}"
            f"DNSOverTLS={dot_mode}\n"
        )

        existing_hosts = ""
        if os.path.exists(HOSTS_FILE):
            existing_hosts = Path(HOSTS_FILE).read_text(encoding="utf-8", errors="ignore")
        new_hosts = update_hosts_content(existing_hosts, profile)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".conf", delete=False, encoding="utf-8"
        ) as tmp_dropin:
            tmp_dropin.write(dropin_content)
            tmp_dropin_path = tmp_dropin.name

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".hosts", delete=False, encoding="utf-8"
        ) as tmp_hosts:
            tmp_hosts.write(new_hosts)
            tmp_hosts_path = tmp_hosts.name

        clean_links_cmds: List[str] = []
        if scope == "global":
            for link in _detect_active_links():
                clean_links_cmds.append(f"resolvectl domain {shlex.quote(link)} '' 2>/dev/null || true")

        try:
            script_parts = [
                "while ip rule delete pref 150 2>/dev/null; do :; done",
                f"mkdir -p {shlex.quote(RESOLVED_DROPIN_DIR)}",
                f"rm -f {shlex.quote(LEGACY_DROPIN_FILE)}",
                f"cp {shlex.quote(tmp_dropin_path)} {shlex.quote(RESOLVED_DROPIN_FILE)}",
                f"chmod 644 {shlex.quote(RESOLVED_DROPIN_FILE)}",
                f"cp {shlex.quote(tmp_hosts_path)} {shlex.quote(HOSTS_FILE)}",
                f"chmod 644 {shlex.quote(HOSTS_FILE)}",
                *clean_links_cmds,
                "systemctl restart systemd-resolved",
                "resolvectl flush-caches 2>/dev/null || true",
            ]
            script = " && ".join(script_parts)
            res = _run_privileged_shell(script)
            if res.returncode != 0:
                if mode == "hybrid":
                    self._stop_proxy()
                err = (res.stderr or res.stdout or "Failed to configure systemd-resolved").strip()
                raise RuntimeError(f"Failed to enable MagicDNS on Linux: {err}")
        finally:
            for p in (tmp_dropin_path, tmp_hosts_path):
                try:
                    os.remove(p)
                except OSError:
                    pass

        return self.get_status(profile)

    def disable(self) -> BackendStatus:
        """Remove MagicDNS drop-in and /etc/hosts block and restore default DNS."""
        self._stop_proxy()

        existing_hosts = ""
        if os.path.exists(HOSTS_FILE):
            existing_hosts = Path(HOSTS_FILE).read_text(encoding="utf-8", errors="ignore")
        cleaned_hosts = update_hosts_content(existing_hosts, None)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".hosts", delete=False, encoding="utf-8"
        ) as tmp_hosts:
            tmp_hosts.write(cleaned_hosts)
            tmp_hosts_path = tmp_hosts.name

        try:
            script = " && ".join(
                [
                    "while ip rule delete pref 150 2>/dev/null; do :; done",
                    f"rm -f {shlex.quote(RESOLVED_DROPIN_FILE)} {shlex.quote(LEGACY_DROPIN_FILE)}",
                    f"cp {shlex.quote(tmp_hosts_path)} {shlex.quote(HOSTS_FILE)}",
                    f"chmod 644 {shlex.quote(HOSTS_FILE)}",
                    "systemctl restart systemd-resolved",
                    "resolvectl flush-caches 2>/dev/null || true",
                ]
            )
            res = _run_privileged_shell(script)
            if res.returncode != 0:
                err = (res.stderr or res.stdout or "Privilege elevation cancelled").strip()
                raise RuntimeError(f"Failed to disable MagicDNS on Linux: {err}")
        finally:
            try:
                os.remove(tmp_hosts_path)
            except OSError:
                pass

        return self.get_status()

    def _start_proxy(self, profile: DnsProfile) -> None:
        self._stop_proxy()
        self._proxy = ConditionalDnsProxy(
            profile=profile,
            bind_host=HYBRID_PROXY_HOST,
            bind_port=HYBRID_PROXY_PORT,
            on_query_log=self.on_query_log,
        )
        self._proxy.start()

    def _stop_proxy(self) -> None:
        if self._proxy is not None:
            self._proxy.stop()
            self._proxy = None
