"""Windows conditional and global DNS backend using NRPT, DoH template, and hosts pinning."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Callable, List, Optional

from ..profiles import DnsProfile
from ..resolver import ConditionalDnsProxy
from .base import (
    BackendStatus,
    DnsBackend,
    update_hosts_content,
)


NRPT_COMMENT = "FastDNS"
NRPT_DISPLAY_NAME = "FastDNS Routing Rule"
WINDOWS_PROXY_HOST = "127.0.0.1"
WINDOWS_PROXY_PORT = 53
WINDOWS_HOSTS_PATH = r"C:\Windows\System32\drivers\etc\hosts"


def _is_windows_admin() -> bool:
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _run_powershell(script: str, require_admin: bool = False) -> subprocess.CompletedProcess[str]:
    """Execute a PowerShell script, elevating via UAC RunAs when required."""
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if not require_admin or _is_windows_admin():
        return subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            creationflags=creation_flags,
        )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".ps1", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(script)
        ps1_path = tmp.name

    try:
        elevate_cmd = (
            f"$p = Start-Process powershell -ArgumentList "
            f"'-NoProfile -ExecutionPolicy Bypass -File \"{ps1_path}\"' "
            f"-Verb RunAs -Wait -PassThru; exit $p.ExitCode"
        )
        return subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                elevate_cmd,
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            creationflags=creation_flags,
        )
    finally:
        try:
            os.remove(ps1_path)
        except OSError:
            pass


class WindowsDnsBackend(DnsBackend):
    """Manages conditional and global DNS forwarding on Windows 10/11."""

    def __init__(
        self,
        on_query_log: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self.on_query_log = on_query_log
        self._proxy: Optional[ConditionalDnsProxy] = None

    def get_status(self, current_profile: Optional[DnsProfile] = None) -> BackendStatus:
        """Query Windows NRPT rules created by FastDNS."""
        check_script = (
            f"$rules = Get-DnsClientNrptRule | Where-Object {{ $_.Comment -like '{NRPT_COMMENT}*' }}; "
            "if ($rules) { "
            "  $first = $rules | Select-Object -First 1; "
            "  Write-Output ('ACTIVE|' + $first.Comment + '|' + ($first.NameServers -join ',')) "
            "} else { Write-Output 'INACTIVE' }"
        )
        try:
            proc = _run_powershell(check_script, require_admin=False)
            out = (proc.stdout or "").strip()
            if out.startswith("ACTIVE|"):
                parts = out.split("|")
                comment = parts[1] if len(parts) > 1 else NRPT_COMMENT
                servers = parts[2] if len(parts) > 2 else ""
                is_hybrid = WINDOWS_PROXY_HOST in servers or "hybrid" in comment.lower()
                is_global = "global" in comment.lower()
                mode = "hybrid" if is_hybrid else "native"
                scope = "global" if is_global else "conditional"
                profile_name = current_profile.name if current_profile else "MagicDNS"
                return BackendStatus(
                    enabled=True,
                    mode=mode,
                    scope=scope,
                    active_profile_name=profile_name,
                    interface_or_policy="Windows NRPT + DoH + Hosts",
                    details=(
                        f"NRPT {'global' if is_global else 'conditional'} active -> "
                        f"{'Local DoH Proxy -> ' + profile_name if is_hybrid else profile_name}"
                    ),
                    proxy_running=bool(self._proxy and self._proxy.is_running),
                )
        except Exception as exc:
            return BackendStatus(
                enabled=False,
                mode="inactive",
                scope="conditional",
                details=f"NRPT query error: {exc}",
            )

        return BackendStatus(
            enabled=False,
            mode="inactive",
            scope="conditional",
            interface_or_policy="Windows NRPT",
            details="System default DNS active for all traffic",
            proxy_running=bool(self._proxy and self._proxy.is_running),
        )

    def enable(
        self,
        profile: DnsProfile,
        mode: str = "native",
        scope: str = "conditional",
    ) -> BackendStatus:
        """Configure Windows NRPT rules, DoH template, and hosts file."""
        if scope == "global":
            namespaces = ["."]
            rule_comment = f"{NRPT_COMMENT}:{mode}:global:{profile.id}"
        else:
            namespaces = []
            for dom in profile.domains:
                clean = dom.strip().lstrip(".").rstrip(".")
                if not clean:
                    continue
                for entry in (f".{clean}", clean):
                    if entry not in namespaces:
                        namespaces.append(entry)
            if not namespaces:
                raise ValueError("Profile has no routing domains configured.")
            rule_comment = f"{NRPT_COMMENT}:{mode}:conditional:{profile.id}"

        if mode == "hybrid":
            self._start_proxy(profile)
            servers = [WINDOWS_PROXY_HOST]
        else:
            self._stop_proxy()
            servers = [s.split("#", 1)[0] for s in profile.dns_servers]

        servers_ps = ", ".join(f"'{s}'" for s in servers)
        chunks = [namespaces[i : i + 40] for i in range(0, len(namespaces), 40)]

        existing_hosts = ""
        if os.path.exists(WINDOWS_HOSTS_PATH):
            try:
                existing_hosts = Path(WINDOWS_HOSTS_PATH).read_text(encoding="utf-8", errors="ignore")
            except Exception:
                pass
        new_hosts = update_hosts_content(existing_hosts, profile)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".hosts", delete=False, encoding="utf-8"
        ) as tmp_hosts:
            tmp_hosts.write(new_hosts)
            tmp_hosts_path = tmp_hosts.name

        ps_lines = [
            "$ErrorActionPreference = 'Stop'",
            f"Get-DnsClientNrptRule | Where-Object {{ $_.Comment -like '{NRPT_COMMENT}*' }} | Remove-DnsClientNrptRule -Force",
        ]

        if profile.doh_url and mode == "native":
            for srv_ip in servers:
                ps_lines.append(
                    "if (Get-Command Add-DnsClientDohServerAddress -ErrorAction SilentlyContinue) { "
                    f"  try {{ Add-DnsClientDohServerAddress -ServerAddress '{srv_ip}' "
                    f"-DohTemplate '{profile.doh_url}' -AllowFallbackToUdp $true -AutoUpgrade $true "
                    "-ErrorAction SilentlyContinue } catch {} "
                    "}"
                )

        for idx, chunk in enumerate(chunks, start=1):
            ns_ps = ", ".join(f"'{n}'" for n in chunk)
            ps_lines.append(
                f"Add-DnsClientNrptRule -Namespace @({ns_ps}) "
                f"-NameServers @({servers_ps}) "
                f"-DisplayName '{NRPT_DISPLAY_NAME} #{idx}' "
                f"-Comment '{rule_comment}' | Out-Null"
            )

        ps_lines.append(f"Copy-Item -Path '{tmp_hosts_path}' -Destination '{WINDOWS_HOSTS_PATH}' -Force")
        ps_lines.append("Clear-DnsClientCache")
        script = "\n".join(ps_lines)

        try:
            res = _run_powershell(script, require_admin=True)
            if res.returncode != 0:
                if mode == "hybrid":
                    self._stop_proxy()
                err = (res.stderr or res.stdout or "Administrator elevation failed").strip()
                raise RuntimeError(f"Failed to configure Windows NRPT: {err}")
        finally:
            try:
                os.remove(tmp_hosts_path)
            except OSError:
                pass

        return self.get_status(profile)

    def disable(self) -> BackendStatus:
        """Remove all FastDNS NRPT rules, clean Windows hosts block, and flush DNS cache."""
        self._stop_proxy()

        existing_hosts = ""
        if os.path.exists(WINDOWS_HOSTS_PATH):
            try:
                existing_hosts = Path(WINDOWS_HOSTS_PATH).read_text(encoding="utf-8", errors="ignore")
            except Exception:
                pass
        cleaned_hosts = update_hosts_content(existing_hosts, None)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".hosts", delete=False, encoding="utf-8"
        ) as tmp_hosts:
            tmp_hosts.write(cleaned_hosts)
            tmp_hosts_path = tmp_hosts.name

        script = "\n".join(
            [
                "$ErrorActionPreference = 'Stop'",
                f"Get-DnsClientNrptRule | Where-Object {{ $_.Comment -like '{NRPT_COMMENT}*' }} | Remove-DnsClientNrptRule -Force",
                f"if (Test-Path '{WINDOWS_HOSTS_PATH}') {{ Copy-Item -Path '{tmp_hosts_path}' -Destination '{WINDOWS_HOSTS_PATH}' -Force }}",
                "Clear-DnsClientCache",
            ]
        )
        try:
            res = _run_powershell(script, require_admin=True)
            if res.returncode != 0:
                err = (res.stderr or res.stdout or "Administrator elevation failed").strip()
                raise RuntimeError(f"Failed to remove Windows NRPT rules: {err}")
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
            bind_host=WINDOWS_PROXY_HOST,
            bind_port=WINDOWS_PROXY_PORT,
            on_query_log=self.on_query_log,
        )
        self._proxy.start()

    def _stop_proxy(self) -> None:
        if self._proxy is not None:
            self._proxy.stop()
            self._proxy = None
