import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

import stalzone_license as lic
import stalzone_license_server as server


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = server.Store(Path(self.temp.name) / "keys.db")

    def tearDown(self):
        self.temp.cleanup()

    def test_logout_does_not_move_the_end_and_second_pc_is_refused(self):
        token, _key_id, _days = self.store.issue(30, now=1_000)
        first = self.store.activate(token, "pc-a", now=1_000)
        self.assertTrue(first["active"])
        self.assertEqual(first["days_left"], 30)
        later = self.store.activate(token, "pc-a", now=1_000 + 10 * lic.DAY)
        self.assertEqual(later["days_left"], 20)
        other = self.store.activate(token, "pc-b", now=1_000 + 10 * lic.DAY)
        self.assertFalse(other["active"])
        self.assertIn("другому ПК", other["reason"])
        dead = self.store.activate(token, "pc-a", now=1_000 + 30 * lic.DAY)
        self.assertEqual(dead["reason"], "Срок ключа кончился")

    def test_revoked_and_unknown_keys_do_not_open(self):
        token, key_id, _days = self.store.issue(7, now=50)
        self.assertTrue(self.store.revoke(key_id))
        closed = self.store.activate(token, "pc-a", now=60)
        self.assertEqual(closed["reason"], "Ключ отозван")
        foreign = lic.issue(30)
        self.assertEqual(self.store.activate(foreign, "pc-a", now=60)["reason"], "Ключ не подходит")

    def test_owner_key_has_no_end(self):
        token, _key_id, _days = self.store.issue(role="owner", now=10)
        opened = self.store.activate(token, "pc-a", now=10)
        self.assertTrue(opened["active"])
        self.assertIsNone(opened["days_left"])
        again = self.store.activate(token, "pc-b", now=99)
        self.assertTrue(again["active"])
        self.assertEqual(again["role"], "owner")

    def test_bot_issues_a_key_only_for_the_owner(self):
        text = server.answer(self.store, 7, "/ключ 30", now=1_000)
        token = text.splitlines()[2]
        opened = self.store.activate(token, "pc-a", now=1_000)
        self.assertTrue(opened["active"])
        self.assertEqual(server.answer(self.store, 8, "/список", now=1_000), "Это пульт владельца.")

    def test_http_activate_returns_a_signed_lease(self):
        token, _key_id, _days = self.store.issue(30, now=1_000)
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(self.store))
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            port = httpd.server_address[1]
            body = json.dumps({"key": token, "machine": "pc-a"}).encode()
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/activate",
                data=body,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                data = json.loads(response.read().decode())
            self.assertTrue(data["active"])
            self.assertEqual(lic.unpack_lease(data["lease"])["machine"], "pc-a")
        finally:
            httpd.shutdown()


if __name__ == "__main__":
    unittest.main()
