"""Unit tests for FastDNS profiles, domain routing rules, hosts pinning, DNS wire-format, and OS backends."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from fastdns.backends.base import (
    HOSTS_END_MARKER,
    HOSTS_START_MARKER,
    update_hosts_content,
)
from fastdns.backends.linux import LinuxDnsBackend
from fastdns.backends.windows import WindowsDnsBackend
from fastdns.profiles import (
    DnsProfile,
    ProfileStore,
    create_magicdns_profile,
    dict_to_profile,
    get_default_domains,
    get_hosts_pinned_domains,
    load_profiles_from_file,
    matches_routed_domain,
)
from fastdns.resolver import (
    build_dns_query,
    build_empty_noerror_response,
    build_synthetic_a_response,
    extract_a_records,
)


class TestProfilesAndRouting(unittest.TestCase):
    def test_magicdns_official_profile(self) -> None:
        magic = create_magicdns_profile()
        self.assertEqual(magic.id, "magicdns")
        self.assertEqual(magic.name, "MagicDNS")
        self.assertEqual(magic.primary_dns, "217.144.190.216")
        self.assertEqual(magic.secondary_dns, "109.120.187.249")
        self.assertEqual(magic.dot_hostname, "api.magicinfo.art")
        self.assertEqual(magic.dot_endpoint, "217.144.190.216#api.magicinfo.art")
        self.assertEqual(magic.doh_url, "https://api.magicinfo.art/rpc")

    def test_routing_rules_and_hosts_pinning(self) -> None:
        domains = get_default_domains()
        self.assertTrue(matches_routed_domain("gemini.google.com", domains))
        self.assertTrue(matches_routed_domain("daily-cloudcode-pa.googleapis.com", domains))
        self.assertTrue(matches_routed_domain("aicode.googleapis.com", domains))
        self.assertFalse(matches_routed_domain("example.com", domains))

        pinned = get_hosts_pinned_domains(domains)
        self.assertIn("gemini.google.com", pinned)
        self.assertIn("daily-cloudcode-pa.googleapis.com", pinned)
        self.assertNotIn("google.com", pinned)

    def test_hosts_content_update_and_cleanup(self) -> None:
        profile = create_magicdns_profile()
        orig = "127.0.0.1\tlocalhost\n"
        updated = update_hosts_content(orig, profile)
        self.assertIn(HOSTS_START_MARKER, updated)
        self.assertIn("217.144.190.216\tgemini.google.com", updated)
        self.assertIn(HOSTS_END_MARKER, updated)

        cleaned = update_hosts_content(updated, None)
        self.assertNotIn(HOSTS_START_MARKER, cleaned)
        self.assertIn("127.0.0.1\tlocalhost", cleaned)

    def test_profile_store_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = Path(tmpdir) / "config.json"
            prof_dir = Path(tmpdir) / "dns_profiles"
            store = ProfileStore(config_path=cfg_path, profiles_dir=prof_dir)
            self.assertEqual(store.scope, "global")
            self.assertEqual(store.active_profile.primary_dns, "217.144.190.216")
            self.assertTrue((prof_dir / "magicdns.json").exists())

    def test_dns_profiles_folder_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prof_dir = Path(tmpdir) / "dns_profiles"
            prof_dir.mkdir(parents=True)
            custom_json = {
                "id": "my_dns",
                "name": "My Custom DNS",
                "primary_dns": "1.1.1.1",
                "secondary_dns": "1.0.0.1",
                "dot_hostname": "one.one.one.one",
                "doh_url": "https://cloudflare-dns.com/dns-query",
            }
            (prof_dir / "custom.json").write_text(json.dumps(custom_json), encoding="utf-8")

            cfg_path = Path(tmpdir) / "config.json"
            store = ProfileStore(config_path=cfg_path, profiles_dir=prof_dir)

            self.assertIn("my_dns", store.profiles)
            p = store.profiles["my_dns"]
            self.assertEqual(p.name, "My Custom DNS")
            self.assertEqual(p.primary_dns, "1.1.1.1")
            self.assertEqual(p.dot_endpoint, "1.1.1.1#one.one.one.one")
            self.assertIn("magicdns", store.profiles)

    def test_dns_profiles_list_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prof_dir = Path(tmpdir) / "dns_profiles"
            prof_dir.mkdir(parents=True)
            list_json = [
                {"id": "dns_a", "name": "DNS A", "primary_dns": "8.8.8.8"},
                {"id": "dns_b", "name": "DNS B", "primary_dns": "9.9.9.9"},
            ]
            (prof_dir / "bundle.json").write_text(json.dumps(list_json), encoding="utf-8")

            cfg_path = Path(tmpdir) / "config.json"
            store = ProfileStore(config_path=cfg_path, profiles_dir=prof_dir)

            self.assertIn("dns_a", store.profiles)
            self.assertIn("dns_b", store.profiles)
            self.assertEqual(store.profiles["dns_a"].primary_dns, "8.8.8.8")
            self.assertEqual(store.profiles["dns_b"].primary_dns, "9.9.9.9")

    def test_add_and_delete_profile_updates_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prof_dir = Path(tmpdir) / "dns_profiles"
            cfg_path = Path(tmpdir) / "config.json"
            store = ProfileStore(config_path=cfg_path, profiles_dir=prof_dir)

            new_prof = DnsProfile(
                id="test_prof",
                name="Test DNS",
                primary_dns="10.0.0.1",
            )
            store.add_or_update_profile(new_prof)
            json_file = prof_dir / "test_prof.json"
            self.assertTrue(json_file.exists())

            # Delete
            store.delete_profile("test_prof")
            self.assertNotIn("test_prof", store.profiles)
            self.assertFalse(json_file.exists())


class TestDnsWireFormat(unittest.TestCase):
    def test_synthetic_responses(self) -> None:
        q_a = build_dns_query("gemini.google.com", qtype=1)
        resp_a = build_synthetic_a_response(q_a, "217.144.190.216")
        self.assertEqual(extract_a_records(resp_a), ["217.144.190.216"])

        q_aaaa = build_dns_query("gemini.google.com", qtype=28)
        resp_empty = build_empty_noerror_response(q_aaaa)
        self.assertEqual(extract_a_records(resp_empty), [])


class TestBackends(unittest.TestCase):
    @patch("fastdns.backends.linux.os.path.exists", return_value=True)
    @patch(
        "fastdns.backends.linux.Path.read_text",
        return_value="[Resolve]\nDNS=217.144.190.216#api.magicinfo.art 109.120.187.249#api.magicinfo.art\nFallbackDNS=1.1.1.1 8.8.8.8\nDNSOverTLS=yes\n",
    )
    @patch("fastdns.backends.linux.shutil.which", return_value="/usr/bin/resolvectl")
    @patch("fastdns.backends.linux._run_privileged_shell")
    def test_linux_backend_enable_magicdns(
        self,
        mock_priv: MagicMock,
        _mock_which: MagicMock,
        _mock_read: MagicMock,
        _mock_exists: MagicMock,
    ) -> None:
        mock_priv.return_value = MagicMock(returncode=0, stdout="", stderr="")
        backend = LinuxDnsBackend()
        profile = create_magicdns_profile()
        status = backend.enable(profile, mode="native", scope="global")
        self.assertTrue(status.enabled)
        self.assertEqual(status.scope, "global")
        called_script = mock_priv.call_args[0][0]
        self.assertIn("/etc/systemd/resolved.conf.d/magicdns.conf", called_script)
        self.assertIn("systemctl restart systemd-resolved", called_script)

    @patch("fastdns.backends.windows.os.path.exists", return_value=False)
    @patch("fastdns.backends.windows._run_powershell")
    def test_windows_backend_enable_and_disable(
        self,
        mock_ps: MagicMock,
        _mock_exists: MagicMock,
    ) -> None:
        mock_ps.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(
                returncode=0,
                stdout="ACTIVE|FastDNS:native:global:magicdns|217.144.190.216,109.120.187.249\n",
                stderr="",
            ),
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=0, stdout="INACTIVE\n", stderr=""),
        ]
        backend = WindowsDnsBackend()
        profile = create_magicdns_profile()

        status_on = backend.enable(profile, mode="native", scope="global")
        self.assertTrue(status_on.enabled)
        self.assertEqual(status_on.scope, "global")
        self.assertEqual(status_on.mode, "native")
        enable_script = mock_ps.call_args_list[0][0][0]
        self.assertIn("Add-DnsClientNrptRule", enable_script)
        self.assertIn("Add-DnsClientDohServerAddress", enable_script)

        status_off = backend.disable()
        self.assertFalse(status_off.enabled)
        disable_script = mock_ps.call_args_list[2][0][0]
        self.assertIn("Remove-DnsClientNrptRule", disable_script)
        self.assertIn("Clear-DnsClientCache", disable_script)


if __name__ == "__main__":
    unittest.main()
