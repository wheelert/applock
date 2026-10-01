import datetime
import tempfile
import unittest
from pathlib import Path

import applock_common as common


class WebsiteBlockingTests(unittest.TestCase):
    def test_parse_website_accepts_urls_and_adds_www(self):
        self.assertEqual(
            common.parse_website("HTTPS://WWW.Example.com/path"),
            ("example.com", ["example.com", "www.example.com"]),
        )
        self.assertEqual(
            common.parse_website("old.example.com"),
            ("old.example.com", ["old.example.com"]),
        )

    def test_invalid_domains_are_rejected(self):
        for value in ("", "not a domain", "example", "https:///path"):
            with self.assertRaises(ValueError):
                common.parse_website(value)

    def test_schedule_can_cross_midnight(self):
        schedule = {"always": False, "start": "19:00", "end": "07:00"}
        self.assertTrue(
            common.schedule_is_locked(schedule, datetime.time(23, 30))
        )
        self.assertFalse(
            common.schedule_is_locked(schedule, datetime.time(12, 0))
        )

    def test_active_website_domains_follow_schedule(self):
        websites = {
            "example.com": {
                "domain": "example.com",
                "domains": ["example.com", "www.example.com"],
                "schedule": {"always": False, "start": "19:00", "end": "07:00"},
            },
            "always.example": {
                "domain": "always.example",
                "domains": ["always.example"],
                "schedule": {"always": True},
            },
        }
        self.assertEqual(
            common.website_block_domains(websites, datetime.time(20, 0)),
            ["always.example", "example.com", "www.example.com"],
        )
        self.assertEqual(
            common.website_block_domains(websites, datetime.time(12, 0)),
            ["always.example"],
        )

    def test_hosts_section_is_managed_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            hosts = Path(directory) / "hosts"
            hosts.write_text(
                "127.0.0.1 localhost\n::1 localhost\n# custom entry\n",
                encoding="utf-8",
            )
            websites = {
                "example.com": {
                    "domain": "example.com",
                    "domains": ["example.com", "www.example.com"],
                    "schedule": {"always": True},
                }
            }

            common.write_website_blocks(websites, hosts_path=hosts)
            text = hosts.read_text(encoding="utf-8")
            self.assertIn(common.HOSTS_BEGIN, text)
            self.assertIn(common.HOSTS_END, text)
            self.assertIn("0.0.0.0 example.com", text)
            self.assertIn("0.0.0.0 www.example.com", text)
            self.assertIn("# custom entry", text)

            common.write_website_blocks({}, hosts_path=hosts)
            text = hosts.read_text(encoding="utf-8")
            self.assertNotIn(common.HOSTS_BEGIN, text)
            self.assertNotIn(common.HOSTS_END, text)
            self.assertNotIn("example.com", text)
            self.assertIn("# custom entry", text)

    def test_incomplete_hosts_section_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            hosts = Path(directory) / "hosts"
            hosts.write_text(
                f"127.0.0.1 localhost\n{common.HOSTS_BEGIN}\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                common.write_website_blocks({}, hosts_path=hosts)


if __name__ == "__main__":
    unittest.main()
