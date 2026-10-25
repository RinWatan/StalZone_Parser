import tempfile
import unittest
from pathlib import Path

import stalzone_license as lic


class LicenseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_month_key_starts_when_pasted_and_remembers_ip(self):
        key = lic.issue(30)
        opened = lic.activate(key, self.root, machine="pc-a", ip="10.1.1.5", host="home", now=1_000_000)
        self.assertTrue(opened["active"])
        self.assertEqual(opened["days_left"], 30)
        self.assertEqual(opened["ip"], "10.1.1.5")
        later = lic.activate(key, self.root, machine="pc-a", ip="10.1.1.9", host="home", now=1_000_000 + lic.DAY)
        self.assertEqual(later["days_left"], 29)
        self.assertEqual(later["ip"], "10.1.1.9")
        dead = lic.status(self.root, now=1_000_000 + 31 * lic.DAY)
        self.assertFalse(dead["active"])
        self.assertEqual(dead["reason"], "Срок ключа кончился")

    def test_user_key_stays_on_the_first_pc(self):
        key = lic.issue(30)
        lic.activate(key, self.root, machine="pc-a", ip="10.0.0.2", now=50)
        moved = lic.activate(key, self.root, machine="pc-b", ip="10.0.0.3", now=60)
        self.assertFalse(moved["active"])
        self.assertIn("другому ПК", moved["reason"])

    def test_owner_key_has_no_end_and_a_label(self):
        key = lic.issue_owner()
        opened = lic.activate(key, self.root, machine="pc-a", ip="10.0.0.1", now=10)
        self.assertTrue(opened["active"])
        self.assertEqual(opened["role"], "owner")
        self.assertEqual(opened["label"], "владелец")
        self.assertIsNone(opened["days_left"])
        again = lic.activate(key, self.root, machine="pc-b", ip="10.0.0.8", now=99)
        self.assertTrue(again["active"])
        self.assertEqual(again["role"], "owner")

    def test_drop_closes_access_but_keeps_the_pc_binding(self):
        key = lic.issue(30)
        lic.activate(key, self.root, machine="pc-a", ip="10.0.0.2", now=1_000)
        closed = lic.drop(self.root)
        self.assertFalse(closed["active"])
        self.assertEqual(closed["reason"], "Нет ключа")
        again = lic.activate(key, self.root, machine="pc-a", ip="10.0.0.4", now=1_000 + lic.DAY)
        self.assertEqual(again["days_left"], 29)
        other = lic.activate(key, self.root, machine="pc-b", ip="10.0.0.9", now=2_000)
        self.assertFalse(other["active"])

    def test_logout_does_not_give_the_unused_days_back(self):
        key = lic.issue(30)
        lic.activate(key, self.root, machine="pc-a", ip="10.0.0.2", now=1_000)
        lic.drop(self.root)
        late = lic.activate(key, self.root, machine="pc-a", ip="10.0.0.4", now=1_000 + 29 * lic.DAY)
        self.assertTrue(late["active"])
        self.assertEqual(late["days_left"], 1)
        lic.drop(self.root)
        dead = lic.activate(key, self.root, machine="pc-a", ip="10.0.0.4", now=1_000 + 30 * lic.DAY)
        self.assertFalse(dead["active"])
        self.assertEqual(dead["reason"], "Срок ключа кончился")
        again = lic.activate(key, self.root, machine="pc-a", ip="10.0.0.4", now=1_000 + 40 * lic.DAY)
        self.assertFalse(again["active"])
        self.assertEqual(again["reason"], "Срок ключа кончился")

    def test_broken_key_is_refused(self):
        refused = lic.activate("not-a-key", self.root, machine="pc-a", ip="1.1.1.1", now=1)
        self.assertFalse(refused["active"])
        self.assertEqual(refused["reason"], "Ключ не подходит")

    def test_windows_shortcut_still_gives_the_server_address(self):
        text = "[InternetShortcut]\nURL=http://127.0.0.1:8787/\n"
        self.assertEqual(lic._url_from_text(text), "http://127.0.0.1:8787/")
        self.assertEqual(lic._url_from_text("http://127.0.0.1:8787\n"), "http://127.0.0.1:8787")


if __name__ == "__main__":
    unittest.main()
