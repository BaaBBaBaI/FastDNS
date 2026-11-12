"""DNS profiles and configuration for FastDNS."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import sys
from typing import Dict, List, Optional


DEFAULT_ROUTING_CATEGORIES: Dict[str, List[str]] = {
    "Antigravity (IDE, CLI & Cloud Code)": [
        "antigravity.google",
        "antigravity.google.com",
        "antigravity-unleash.goog",
        "daily-cloudcode-pa.googleapis.com",
        "cloudcode-pa.googleapis.com",
        "cloudaicompanion.googleapis.com",
        "daily-cloudcode-pa.sandbox.googleapis.com",
        "autopush-cloudcode-pa.sandbox.googleapis.com",
        "preprod-daily-cloudcode-pa.sandbox.googleapis.com",
        "aicode.googleapis.com",
        "autopush-aicode.sandbox.googleapis.com",
        "preprod-aicode.sandbox.googleapis.com",
        "businessaicode.googleapis.com",
        "aiplatform.googleapis.com",
        "auth.cloud.google",
        "sts.googleapis.com",
        "iamcredentials.googleapis.com",
        "oauth2.googleapis.com",
        "www.googleapis.com",
        "play.googleapis.com",
        "idx.dev",
        "firebase.studio",
    ],
    "Gemini (Web, AI Studio & DeepMind)": [
        "gemini.google.com",
        "aistudio.google.com",
        "makersuite.google.com",
        "generativelanguage.googleapis.com",
        "alkalimakersuite-pa.clients6.google.com",
        "alkalimakersuiteapplets.pa.googleapis.com",
        "proactivebackend-pa.googleapis.com",
        "aisandbox-pa.googleapis.com",
        "ogads-pa.clients6.google.com",
        "waa-pa.clients6.google.com",
        "signaler-pa.clients6.google.com",
        "peoplestack-pa.clients6.google.com",
        "clients6.google.com",
        "optimizationguide-pa.googleapis.com",
        "content-autofill.googleapis.com",
        "notebooklm.google.com",
        "deepmind.google",
        "labs.google",
        "ai.google.dev",
        "bard.google.com",
        "jules.google.com",
        "opal.google.com",
        "stitch.withgoogle.com",
    ],
    "Google Core & Ecosystem": [
        "www.google.com",
        "accounts.google.com",
        "apis.google.com",
        "play.google.com",
        "google.com",
        "googleapis.com",
        "gstatic.com",
        "googleusercontent.com",
        "google",
        "goog",
        "google.dev",
        "withgoogle.com",
        "1e100.net",
        "gvt1.com",
        "gvt2.com",
        "ggpht.com",
        "appspot.com",
    ],
}

WILDCARD_ZONE_ONLY_SUFFIXES = {
    "google.com",
    "googleapis.com",
    "gstatic.com",
    "googleusercontent.com",
    "google",
    "goog",
    "google.dev",
    "withgoogle.com",
    "1e100.net",
    "gvt1.com",
    "gvt2.com",
    "ggpht.com",
    "appspot.com",
    "firebase.studio",
}


def get_default_domains() -> List[str]:
    """Return deduplicated list of all default routed domains."""
    seen = set()
    result: List[str] = []
    for domains in DEFAULT_ROUTING_CATEGORIES.values():
        for d in domains:
            norm = d.strip().lower().lstrip(".")
            if norm and norm not in seen:
                seen.add(norm)
                result.append(norm)
    return result


def get_hosts_pinned_domains(domains: List[str]) -> List[str]:
    """Return exact hostnames to pin in /etc/hosts to the MagicDNS SNI proxy IP."""
    pinned: List[str] = []
    seen = set()
    for d in domains:
        clean = d.strip().lower().lstrip(".").lstrip("~").rstrip(".")
        if not clean or "." not in clean:
            continue
        if clean in WILDCARD_ZONE_ONLY_SUFFIXES:
            continue
        if clean not in seen:
            seen.add(clean)
            pinned.append(clean)
    return pinned


@dataclass
class DnsProfile:
    """Represents a DNS provider profile."""

    id: str
    name: str
    primary_dns: str
    secondary_dns: str = ""
    dot_hostname: str = ""
    dot_endpoint: str = ""
    doh_url: str = ""
    apple_profile_url: str = ""
    setup_url: str = ""
    description: str = ""
    domains: List[str] = field(default_factory=get_default_domains)
    builtin: bool = False

    @property
    def dns_servers(self) -> List[str]:
        servers = [self.primary_dns.strip()]
        if self.secondary_dns.strip():
            servers.append(self.secondary_dns.strip())
        return [s for s in servers if s]

    @property
    def linux_resolved_servers(self) -> List[str]:
        """Format servers for systemd-resolved (with #hostname for DoT)."""
        servers: List[str] = []
        for ip in self.dns_servers:
            if "#" in ip:
                servers.append(ip)
            elif self.dot_hostname:
                servers.append(f"{ip}#{self.dot_hostname}")
            else:
                servers.append(ip)
        return servers


def create_magicdns_profile() -> DnsProfile:
    """Create the official MagicDNS profile:
    Primary: 217.144.190.216, Secondary: 109.120.187.249, Hostname: api.magicinfo.art, DoH: https://api.magicinfo.art/rpc
    """
    return DnsProfile(
        id="magicdns",
        name="MagicDNS",
        primary_dns="217.144.190.216",
        secondary_dns="109.120.187.249",
        dot_hostname="api.magicinfo.art",
        dot_endpoint="217.144.190.216#api.magicinfo.art",
        doh_url="https://api.magicinfo.art/rpc",
        apple_profile_url="https://magicdns.ru/profile.mobileconfig",
        setup_url="https://magicdns.ru/#setup",
        description="Official MagicDNS: 217.144.190.216 & 109.120.187.249 (api.magicinfo.art)",
        domains=get_default_domains(),
        builtin=True,
    )


def get_default_config_dir() -> Path:
    """Return the default user configuration directory for FastDNS."""
    if os.environ.get("FASTDNS_CONFIG_DIR"):
        return Path(os.environ["FASTDNS_CONFIG_DIR"]).resolve()

    legacy_dir = Path.home() / ".config" / "fastdns"
    if sys.platform == "win32" and os.environ.get("APPDATA") and not legacy_dir.exists():
        return Path(os.environ["APPDATA"]) / "FastDNS"
    return legacy_dir


def _get_app_root() -> Path:
    """Return the application root directory (works from source and frozen builds)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_default_profiles_dir() -> Path:
    """Return the default writable directory for dns_profiles."""
    if os.environ.get("FASTDNS_PROFILES_DIR"):
        return Path(os.environ["FASTDNS_PROFILES_DIR"]).resolve()

    app_root = _get_app_root()
    app_profiles_dir = app_root / "dns_profiles"
    if app_profiles_dir.exists():
        if os.access(app_profiles_dir, os.W_OK):
            return app_profiles_dir
    elif os.access(app_root, os.W_OK):
        return app_profiles_dir

    return get_default_config_dir() / "dns_profiles"


def get_search_profiles_dirs(custom_dir: Optional[Path] = None) -> List[Path]:
    """Return candidate directories to search for JSON profile files in priority order."""
    candidates: List[Path] = []
    if custom_dir:
        candidates.append(Path(custom_dir).resolve())

    if os.environ.get("FASTDNS_PROFILES_DIR"):
        candidates.append(Path(os.environ["FASTDNS_PROFILES_DIR"]).resolve())

    # Application root / dns_profiles (source checkout or executable directory)
    candidates.append((_get_app_root() / "dns_profiles").resolve())

    # PyInstaller _MEIPASS bundled resources if present
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append((Path(meipass) / "dns_profiles").resolve())

    # Current working directory / dns_profiles
    candidates.append((Path.cwd() / "dns_profiles").resolve())

    # User config directory / dns_profiles
    candidates.append((get_default_config_dir() / "dns_profiles").resolve())

    # Deduplicate while preserving search priority order
    seen = set()
    result: List[Path] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            result.append(c)
    return result


def dict_to_profile(data: dict, default_id: str = "") -> Optional[DnsProfile]:
    """Parse a dictionary into a DnsProfile instance."""
    if not isinstance(data, dict):
        return None

    raw_id = data.get("id") or default_id or ""
    pid = str(raw_id).strip().lower().replace(" ", "_")
    if not pid:
        return None

    name = str(data.get("name") or pid.capitalize()).strip()
    primary = str(
        data.get("primary_dns")
        or data.get("primary")
        or data.get("dns1")
        or data.get("dns")
        or ""
    ).strip()
    secondary = str(
        data.get("secondary_dns")
        or data.get("secondary")
        or data.get("dns2")
        or ""
    ).strip()
    dot_host = str(
        data.get("dot_hostname")
        or data.get("hostname")
        or data.get("tls_hostname")
        or ""
    ).strip()
    dot_ep = str(data.get("dot_endpoint") or "").strip()
    if not dot_ep and primary and dot_host:
        dot_ep = f"{primary}#{dot_host}"

    doh = str(data.get("doh_url") or data.get("doh") or "").strip()
    apple_profile = str(data.get("apple_profile_url") or "").strip()
    setup_url = str(data.get("setup_url") or "").strip()
    description = str(
        data.get("description")
        or (f"{name}: {primary}" if primary else "")
    ).strip()

    raw_domains = data.get("domains")
    if isinstance(raw_domains, list) and raw_domains:
        domains: List[str] = []
        seen_d = set()
        for d in raw_domains:
            norm = str(d).strip().lower().lstrip(".")
            if norm and norm not in seen_d:
                seen_d.add(norm)
                domains.append(norm)
    else:
        domains = get_default_domains()

    builtin = bool(data.get("builtin", pid == "magicdns"))

    return DnsProfile(
        id=pid,
        name=name,
        primary_dns=primary,
        secondary_dns=secondary,
        dot_hostname=dot_host,
        dot_endpoint=dot_ep,
        doh_url=doh,
        apple_profile_url=apple_profile,
        setup_url=setup_url,
        description=description,
        domains=domains,
        builtin=builtin,
    )


def load_profiles_from_file(file_path: Path) -> List[DnsProfile]:
    """Load one or more DnsProfiles from a JSON file."""
    try:
        content = file_path.read_text(encoding="utf-8")
        parsed = json.loads(content)
    except Exception:
        return []

    profiles: List[DnsProfile] = []
    if isinstance(parsed, list):
        for idx, item in enumerate(parsed):
            p = dict_to_profile(item, default_id=f"{file_path.stem}_{idx}")
            if p:
                profiles.append(p)
    elif isinstance(parsed, dict):
        if "profiles" in parsed and isinstance(parsed["profiles"], list):
            for idx, item in enumerate(parsed["profiles"]):
                p = dict_to_profile(item, default_id=f"{file_path.stem}_{idx}")
                if p:
                    profiles.append(p)
        else:
            p = dict_to_profile(parsed, default_id=file_path.stem)
            if p:
                profiles.append(p)

    return profiles


class ProfileStore:
    """Loads and saves DNS profiles and application settings."""

    def __init__(
        self,
        config_path: Optional[Path] = None,
        profiles_dir: Optional[Path] = None,
    ) -> None:
        if config_path is None:
            config_path = get_default_config_dir() / "config.json"
        self.config_path = Path(config_path)
        self.profiles_dir = Path(profiles_dir) if profiles_dir else get_default_profiles_dir()
        self.profiles: Dict[str, DnsProfile] = {}
        self.profile_sources: Dict[str, Path] = {}
        self.active_profile_id: str = "magicdns"
        # scope: "global" (system-wide DNS) or "conditional" (Google & AI)
        self.scope: str = "global"
        # mode: "native" (systemd-resolved DoT) or "hybrid" (local proxy)
        self.routing_mode: str = "native"
        self.load()

    def load(self) -> None:
        """Load profiles from dns_profiles/*.json and user settings from config.json."""
        self.profiles = {}
        self.profile_sources = {}

        # 1. Search for JSON profile files across candidate directories
        search_dirs = get_search_profiles_dirs(self.profiles_dir)
        for p_dir in search_dirs:
            if not p_dir.is_dir():
                continue
            for json_file in sorted(p_dir.glob("*.json")):
                loaded_list = load_profiles_from_file(json_file)
                for prof in loaded_list:
                    if prof.id not in self.profiles:
                        self.profiles[prof.id] = prof
                        self.profile_sources[prof.id] = json_file

        # 2. If magicdns is not loaded from json files, add official default
        if "magicdns" not in self.profiles:
            magic = create_magicdns_profile()
            self.profiles[magic.id] = magic

        # Ensure profiles_dir has magicdns.json persisted
        try:
            self.profiles_dir.mkdir(parents=True, exist_ok=True)
            magic_file = self.profiles_dir / "magicdns.json"
            if not magic_file.exists():
                magic_file.write_text(
                    json.dumps(asdict(self.profiles["magicdns"]), indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                self.profile_sources["magicdns"] = magic_file
        except Exception:
            pass

        # 3. Read app settings from config.json
        if self.config_path.exists():
            try:
                raw = json.loads(self.config_path.read_text(encoding="utf-8"))
                self.active_profile_id = raw.get("active_profile_id", "magicdns")
                self.routing_mode = raw.get("routing_mode", "native")
                self.scope = raw.get("scope", "global")
                for item in raw.get("profiles", []):
                    pid = item.get("id")
                    if not pid:
                        continue
                    if pid in self.profiles:
                        # User customized domains
                        custom_domains = item.get("domains")
                        if isinstance(custom_domains, list) and custom_domains:
                            self.profiles[pid].domains = custom_domains
                    else:
                        prof = dict_to_profile(item, default_id=pid)
                        if prof:
                            self.profiles[pid] = prof
            except Exception:
                pass

        if self.active_profile_id not in self.profiles:
            self.active_profile_id = "magicdns" if "magicdns" in self.profiles else next(iter(self.profiles.keys()))

    def reload_profiles(self) -> None:
        """Re-scan dns_profiles folder and reload all profiles."""
        self.load()

    def save(self) -> None:
        """Persist settings to disk."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "active_profile_id": self.active_profile_id,
            "routing_mode": self.routing_mode,
            "scope": self.scope,
            "profiles": [asdict(p) for p in self.profiles.values()],
        }
        self.config_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @property
    def active_profile(self) -> DnsProfile:
        return self.profiles.get(self.active_profile_id) or self.profiles["magicdns"]

    def set_active_profile(self, profile_id: str) -> DnsProfile:
        if profile_id not in self.profiles:
            raise KeyError(f"Unknown profile: {profile_id}")
        self.active_profile_id = profile_id
        self.save()
        return self.active_profile

    def add_or_update_profile(self, profile: DnsProfile, save_json_file: bool = True) -> None:
        """Add or update a profile and persist to dns_profiles/<id>.json."""
        self.profiles[profile.id] = profile
        if save_json_file:
            try:
                target_file = self.profile_sources.get(profile.id)
                if not target_file:
                    self.profiles_dir.mkdir(parents=True, exist_ok=True)
                    target_file = self.profiles_dir / f"{profile.id}.json"
                    self.profile_sources[profile.id] = target_file
                target_file.write_text(
                    json.dumps(asdict(profile), indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
            except Exception:
                pass
        self.save()

    def delete_profile(self, profile_id: str) -> None:
        """Delete a profile and its backing JSON file if present."""
        if profile_id == "magicdns":
            raise ValueError("Cannot delete the built-in MagicDNS profile.")
        target_file = self.profile_sources.pop(profile_id, None)
        if target_file and target_file.exists():
            try:
                target_file.unlink()
            except Exception:
                pass
        self.profiles.pop(profile_id, None)
        if self.active_profile_id == profile_id:
            self.active_profile_id = "magicdns"
        self.save()

    def reset_profile_domains(self, profile_id: str) -> List[str]:
        profile = self.profiles[profile_id]
        profile.domains = get_default_domains()
        self.add_or_update_profile(profile)
        return profile.domains


def matches_routed_domain(qname: str, routed_domains: List[str]) -> bool:
    """Return True if qname matches or is a subdomain of any domain in routed_domains."""
    clean = qname.strip().lower().rstrip(".")
    if not clean:
        return False
    for domain in routed_domains:
        d = domain.strip().lower().lstrip(".").rstrip(".")
        if not d:
            continue
        if clean == d or clean.endswith("." + d):
            return True
    return False
