"""Command-line interface and entry point for FastDNS."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Optional

from .backends import create_backend
from .profiles import ProfileStore
from .resolver import verify_profile_connectivity


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fastdns",
        description="FastDNS — DNS switcher for MagicDNS and custom profiles (Ubuntu & Windows)",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch desktop GUI (default when no flags passed)",
    )
    parser.add_argument(
        "--enable",
        action="store_true",
        help="Enable DNS routing for the active profile",
    )
    parser.add_argument(
        "--disable",
        action="store_true",
        help="Disable DNS routing and restore system default DNS",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current DNS routing status",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Test profile connectivity and latency",
    )
    parser.add_argument(
        "--profile",
        type=str,
        default=None,
        help="Profile ID to use (default: magicdns)",
    )
    parser.add_argument(
        "--profiles-dir",
        type=str,
        default=None,
        help="Custom directory containing DNS profile JSON files",
    )
    parser.add_argument(
        "--list-profiles",
        action="store_true",
        help="List all discovered DNS profiles in dns_profiles folder",
    )
    parser.add_argument(
        "--scope",
        choices=["conditional", "global"],
        default=None,
        help="Routing scope: 'conditional' (Google & AI) or 'global' (all DNS traffic)",
    )
    parser.add_argument(
        "--mode",
        choices=["native", "hybrid"],
        default=None,
        help="DNS engine: 'native' (systemd-resolved DoT / Windows NRPT) or 'hybrid' (local DoH proxy)",
    )
    parser.add_argument(
        "--list-domains",
        action="store_true",
        help="Print list of routed domains for the active profile",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    has_cli_action = any(
        [
            args.enable,
            args.disable,
            args.status,
            args.test,
            args.list_domains,
            args.list_profiles,
        ]
    )

    if args.gui or not has_cli_action:
        from .gui import run_gui

        run_gui()
        return 0

    profiles_dir = Path(args.profiles_dir) if args.profiles_dir else None
    store = ProfileStore(profiles_dir=profiles_dir)

    if args.list_profiles:
        print(f"Profiles ({len(store.profiles)}) [directory: {store.profiles_dir}]:")
        for pid, p in store.profiles.items():
            active_marker = " * " if pid == store.active_profile_id else "   "
            source_file = store.profile_sources.get(pid)
            source_str = f" ({source_file.name})" if source_file else ""
            print(f"{active_marker}{pid}: {p.name} [{p.primary_dns}] DoH={p.doh_url or 'None'} DoT={p.dot_hostname or 'None'}{source_str}")
        return 0

    if args.profile:
        store.set_active_profile(args.profile)
    if args.mode:
        store.routing_mode = args.mode
    if args.scope:
        store.scope = args.scope
    store.save()

    profile = store.active_profile
    backend = create_backend()

    if args.list_domains:
        print(f"Profile: {profile.name} ({len(profile.domains)} routed domains)")
        for dom in profile.domains:
            print(f"  - {dom}")
        return 0

    if args.enable:
        status = backend.enable(profile, mode=store.routing_mode, scope=store.scope)
        print(f"[ENABLED] {status.details}")
        return 0

    if args.disable:
        status = backend.disable()
        print(f"[DISABLED] {status.details}")
        return 0

    if args.status:
        status = backend.get_status(profile)
        state_str = "ENABLED" if status.enabled else "DISABLED"
        print(f"State:   {state_str}")
        print(f"Scope:   {status.scope}")
        print(f"Mode:    {status.mode}")
        print(f"Profile: {profile.name} ({profile.primary_dns})")
        print(f"Details: {status.details}")
        return 0

    if args.test:
        report = verify_profile_connectivity(profile)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report.get("ok") else 1

    return 0
