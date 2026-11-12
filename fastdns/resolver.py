"""DNS wire-format helpers, DoH/DoT/UDP resolvers, and local conditional DNS proxy."""

from __future__ import annotations

import http.client
import os
import re
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
import urllib.parse
from typing import Callable, Dict, List, Optional, Tuple

from .profiles import DnsProfile, get_hosts_pinned_domains, matches_routed_domain


def build_dns_query(domain: str, qtype: int = 1, txid: int = 0x4644) -> bytes:
    """Build a standard DNS query packet (default A record, qtype=1)."""
    labels = [lbl for lbl in domain.strip().rstrip(".").split(".") if lbl]
    qname = b"".join(bytes([len(lbl)]) + lbl.encode("idna") for lbl in labels) + b"\x00"
    header = struct.pack("!HHHHHH", txid & 0xFFFF, 0x0100, 1, 0, 0, 0)
    question = qname + struct.pack("!HH", qtype, 1)
    return header + question


def extract_qname_and_qtype(packet: bytes) -> Tuple[str, int]:
    """Extract (qname, qtype) from a raw DNS request packet."""
    if len(packet) < 12:
        return "", 0
    idx = 12
    labels: List[str] = []
    max_jumps = 10
    jumps = 0
    end_of_qname = -1
    while idx < len(packet):
        length = packet[idx]
        if length == 0:
            if end_of_qname == -1:
                end_of_qname = idx + 1
            break
        if (length & 0xC0) == 0xC0:
            if idx + 1 >= len(packet) or jumps >= max_jumps:
                break
            if end_of_qname == -1:
                end_of_qname = idx + 2
            idx = ((length & 0x3F) << 8) | packet[idx + 1]
            jumps += 1
            continue
        idx += 1
        if idx + length > len(packet):
            break
        labels.append(packet[idx : idx + length].decode("ascii", errors="ignore"))
        idx += length

    qtype = 1
    if end_of_qname != -1 and end_of_qname + 2 <= len(packet):
        qtype = struct.unpack("!H", packet[end_of_qname : end_of_qname + 2])[0]
    return ".".join(labels).lower(), qtype


def extract_qname(packet: bytes) -> str:
    """Extract the queried domain name from a raw DNS request packet."""
    qname, _ = extract_qname_and_qtype(packet)
    return qname


def _skip_dns_name(packet: bytes, idx: int) -> int:
    while idx < len(packet):
        length = packet[idx]
        if length == 0:
            return idx + 1
        if (length & 0xC0) == 0xC0:
            return idx + 2
        idx += 1 + length
    return idx


def build_empty_noerror_response(query: bytes) -> bytes:
    """Build a synthetic NOERROR (0 answers) response for AAAA/HTTPS suppression."""
    if len(query) < 12:
        return b""
    txid = struct.unpack("!H", query[:2])[0]
    q_end = _skip_dns_name(query, 12) + 4
    question = query[12:q_end]
    header = struct.pack("!HHHHHH", txid, 0x8180, 1, 0, 0, 0)
    return header + question


def build_synthetic_a_response(query: bytes, ipv4: str, ttl: int = 120) -> bytes:
    """Build a synthetic DNS A record response pointing to ipv4."""
    if len(query) < 12:
        return b""
    txid = struct.unpack("!H", query[:2])[0]
    q_end = _skip_dns_name(query, 12) + 4
    question = query[12:q_end]
    header = struct.pack("!HHHHHH", txid, 0x8180, 1, 1, 0, 0)
    ip_bytes = socket.inet_aton(ipv4)
    answer = struct.pack("!HHHIH", 0xC00C, 1, 1, ttl, 4) + ip_bytes
    return header + question + answer


def extract_a_records(packet: bytes) -> List[str]:
    """Parse IPv4 A records from a DNS response packet."""
    if len(packet) < 12:
        return []
    _, _, qdcount, ancount, _, _ = struct.unpack("!HHHHHH", packet[:12])
    idx = 12
    for _ in range(qdcount):
        idx = _skip_dns_name(packet, idx)
        idx += 4
    ips: List[str] = []
    for _ in range(ancount):
        if idx >= len(packet):
            break
        idx = _skip_dns_name(packet, idx)
        if idx + 10 > len(packet):
            break
        rtype, rclass, _, rdlength = struct.unpack("!HHIH", packet[idx : idx + 10])
        idx += 10
        if idx + rdlength > len(packet):
            break
        if rtype == 1 and rclass == 1 and rdlength == 4:
            ips.append(".".join(str(b) for b in packet[idx : idx + 4]))
        idx += rdlength
    return ips


def resolve_dot(
    query: bytes,
    server_ip: str,
    hostname: str,
    port: int = 853,
    timeout: float = 3.5,
) -> bytes:
    """Resolve a raw DNS packet via DNS-over-TLS (RFC 7858, port 853)."""
    ctx = ssl.create_default_context()
    with socket.create_connection((server_ip, port), timeout=timeout) as raw_sock:
        sni = hostname or server_ip
        with ctx.wrap_socket(raw_sock, server_hostname=sni) as tls_sock:
            tls_sock.settimeout(timeout)
            payload = struct.pack("!H", len(query)) + query
            tls_sock.sendall(payload)
            hdr = b""
            while len(hdr) < 2:
                chunk = tls_sock.recv(2 - len(hdr))
                if not chunk:
                    raise EOFError("DoT connection closed while reading length")
                hdr += chunk
            resp_len = struct.unpack("!H", hdr)[0]
            resp = b""
            while len(resp) < resp_len:
                chunk = tls_sock.recv(resp_len - len(resp))
                if not chunk:
                    raise EOFError("DoT connection closed while reading body")
                resp += chunk
            return resp


def resolve_doh(
    query: bytes,
    doh_url: str,
    bootstrap_ips: Optional[List[str]] = None,
    timeout: float = 3.5,
) -> bytes:
    """Resolve a raw DNS packet via DNS-over-HTTPS (RFC 8484 POST) with bootstrap IP pinning."""
    parsed = urllib.parse.urlparse(doh_url)
    host = parsed.hostname or "api.magicinfo.art"
    port = parsed.port or 443
    path = parsed.path or "/sync"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    targets = list(bootstrap_ips or [])
    if not targets:
        targets = [host]

    ctx = ssl.create_default_context()
    last_err: Optional[Exception] = None
    for target_ip in targets:
        try:
            raw_sock = socket.create_connection((target_ip, port), timeout=timeout)
            tls_sock = ctx.wrap_socket(raw_sock, server_hostname=host)
            tls_sock.settimeout(timeout)
            conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=ctx)
            conn.sock = tls_sock
            try:
                conn.request(
                    "POST",
                    path,
                    body=query,
                    headers={
                        "Host": host,
                        "Content-Type": "application/dns-message",
                        "Accept": "application/dns-message",
                        "Connection": "close",
                        "User-Agent": "FastDNS/1.0",
                    },
                )
                resp = conn.getresponse()
                body = resp.read()
                if resp.status == 200 and len(body) >= 12:
                    return body
                raise RuntimeError(f"DoH HTTP {resp.status}")
            finally:
                conn.close()
        except Exception as exc:
            last_err = exc
    raise RuntimeError(f"DoH resolution failed via {doh_url}: {last_err}")


def resolve_udp(
    query: bytes,
    server_ip: str,
    port: int = 53,
    timeout: float = 2.5,
) -> bytes:
    """Resolve a raw DNS packet over standard UDP port 53."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(query, (server_ip, port))
        data, _ = sock.recvfrom(4096)
        return data


def resolve_with_profile(
    query: bytes,
    profile: DnsProfile,
    prefer_doh: bool = True,
    timeout: float = 3.5,
) -> Tuple[bytes, str]:
    """Resolve a DNS packet using the given profile (DoH -> DoT -> UDP fallback)."""
    errors: List[str] = []

    if prefer_doh and profile.doh_url:
        try:
            resp = resolve_doh(
                query,
                profile.doh_url,
                bootstrap_ips=profile.dns_servers,
                timeout=timeout,
            )
            return resp, "DoH"
        except Exception as exc:
            errors.append(f"DoH: {exc}")

    if profile.dot_hostname or profile.dot_endpoint:
        sni = profile.dot_hostname
        if not sni and "#" in profile.dot_endpoint:
            sni = profile.dot_endpoint.split("#", 1)[1]
        for ip in profile.dns_servers:
            clean_ip = ip.split("#", 1)[0]
            try:
                resp = resolve_dot(query, clean_ip, sni, timeout=timeout)
                return resp, f"DoT ({clean_ip})"
            except Exception as exc:
                errors.append(f"DoT {clean_ip}: {exc}")

    if not prefer_doh and profile.doh_url:
        try:
            resp = resolve_doh(
                query,
                profile.doh_url,
                bootstrap_ips=profile.dns_servers,
                timeout=timeout,
            )
            return resp, "DoH"
        except Exception as exc:
            errors.append(f"DoH: {exc}")

    for ip in profile.dns_servers:
        clean_ip = ip.split("#", 1)[0]
        try:
            resp = resolve_udp(query, clean_ip, timeout=timeout)
            return resp, f"UDP ({clean_ip})"
        except Exception as exc:
            errors.append(f"UDP {clean_ip}: {exc}")

    raise RuntimeError("; ".join(errors) or "No DNS endpoints configured")


def detect_system_upstream_dns() -> List[str]:
    """Detect the system's default non-loopback upstream DNS servers."""
    upstreams: List[str] = []

    if sys.platform.startswith("linux"):
        try:
            proc = subprocess.run(
                ["resolvectl", "dns"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            for line in proc.stdout.splitlines():
                if "Global:" in line or "fastdns" in line:
                    continue
                for token in line.split():
                    ip = token.split("#", 1)[0]
                    if re.match(r"^\d+\.\d+\.\d+\.\d+$", ip) and not ip.startswith("127."):
                        if ip not in upstreams:
                            upstreams.append(ip)
        except Exception:
            pass

        for conf in ("/run/systemd/resolve/resolv.conf", "/etc/resolv.conf"):
            if os.path.exists(conf):
                try:
                    with open(conf, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line.startswith("nameserver"):
                                parts = line.split()
                                if len(parts) >= 2:
                                    ip = parts[1]
                                    if not ip.startswith("127.") and ip not in upstreams:
                                        upstreams.append(ip)
                except Exception:
                    pass

    elif sys.platform == "win32":
        try:
            proc = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-DnsClientServerAddress -AddressFamily IPv4).ServerAddresses",
                ],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            for line in proc.stdout.splitlines():
                ip = line.strip()
                if re.match(r"^\d+\.\d+\.\d+\.\d+$", ip) and not ip.startswith("127."):
                    if ip not in upstreams:
                        upstreams.append(ip)
        except Exception:
            pass

    if not upstreams:
        upstreams = ["1.1.1.1", "8.8.8.8"]
    return upstreams


class ConditionalDnsProxy:
    """Lightweight local UDP DNS proxy with conditional forwarding to MagicDNS (DoH/DoT)."""

    def __init__(
        self,
        profile: DnsProfile,
        bind_host: str = "127.0.0.1",
        bind_port: int = 5354,
        on_query_log: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self.profile = profile
        self.bind_host = bind_host
        self.bind_port = bind_port
        self.on_query_log = on_query_log
        self._pinned_set = set(get_hosts_pinned_domains(profile.domains))
        self._primary_ip = profile.primary_dns.split("#", 1)[0].split(":", 1)[0].strip()
        self.upstream_dns = [
            ip
            for ip in detect_system_upstream_dns()
            if ip not in {s.split("#")[0] for s in profile.dns_servers}
        ] or ["1.1.1.1", "8.8.8.8"]
        self._sock: Optional[socket.socket] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.bind_host, self.bind_port))
        sock.settimeout(0.5)
        self._sock = sock
        self._running = True
        self._thread = threading.Thread(
            target=self._serve_loop,
            name="FastDnsProxy",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._thread = None

    def _serve_loop(self) -> None:
        while self._running and self._sock is not None:
            try:
                data, client_addr = self._sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(
                target=self._handle_packet,
                args=(data, client_addr),
                daemon=True,
            ).start()

    def _handle_packet(self, data: bytes, client_addr: Tuple[str, int]) -> None:
        qname, qtype = extract_qname_and_qtype(data)
        try:
            if matches_routed_domain(qname, self.profile.domains):
                # Suppress IPv6 (AAAA=28) and SVCB/HTTPS (65) so clients use IPv4 SNI proxy without leak
                if qtype in (28, 65):
                    resp = build_empty_noerror_response(data)
                    if resp and self._sock is not None:
                        self._sock.sendto(resp, client_addr)
                    return

                # Instant 0ms synthesis for pinned Gemini/Antigravity endpoints
                if qtype == 1 and qname in self._pinned_set and self._primary_ip:
                    resp = build_synthetic_a_response(data, self._primary_ip)
                    if self.on_query_log:
                        self.on_query_log(qname, f"{self.profile.name} (Pinned {self._primary_ip})")
                else:
                    resp, proto = resolve_with_profile(data, self.profile, prefer_doh=True)
                    if self.on_query_log:
                        self.on_query_log(qname, f"{self.profile.name} ({proto})")
            else:
                resp = b""
                for upstream in self.upstream_dns:
                    try:
                        resp = resolve_udp(data, upstream, timeout=2.0)
                        break
                    except Exception:
                        continue
                if self.on_query_log:
                    self.on_query_log(qname, "System Default DNS")
            if resp and self._sock is not None:
                self._sock.sendto(resp, client_addr)
        except Exception:
            pass


def verify_profile_connectivity(profile: DnsProfile) -> Dict[str, object]:
    """Run a live diagnostic check against the profile's DoT/DoH endpoints and system DNS."""
    results: Dict[str, object] = {
        "profile": profile.name,
        "probes": [],
        "ok": False,
        "latency_ms": None,
    }
    test_domains = [
        ("gemini.google.com", True),
        ("antigravity.google", True),
        ("daily-cloudcode-pa.googleapis.com", True),
    ]
    latencies: List[float] = []
    probes: List[Dict[str, str]] = []

    for domain, _ in test_domains:
        q = build_dns_query(domain)
        t0 = time.perf_counter()
        try:
            resp, transport = resolve_with_profile(q, profile, prefer_doh=True, timeout=3.5)
            dt = (time.perf_counter() - t0) * 1000.0
            latencies.append(dt)
            ips = extract_a_records(resp)
            probes.append(
                {
                    "domain": domain,
                    "status": "OK",
                    "transport": transport,
                    "ip": ", ".join(ips) if ips else "resolved",
                    "latency_ms": f"{dt:.0f} ms",
                }
            )
        except Exception as exc:
            probes.append(
                {
                    "domain": domain,
                    "status": "ERROR",
                    "transport": "-",
                    "ip": str(exc),
                    "latency_ms": "-",
                }
            )

    try:
        sys_ip = socket.gethostbyname("gemini.google.com")
    except Exception as exc:
        sys_ip = f"Error: {exc}"

    results["probes"] = probes
    results["system_gemini_ip"] = sys_ip
    results["ok"] = any(p["status"] == "OK" for p in probes)
    if latencies:
        results["latency_ms"] = round(sum(latencies) / len(latencies))
    return results
