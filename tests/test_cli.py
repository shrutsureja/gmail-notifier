"""The agent-facing CLI, run as a real subprocess against the fake IMAP server."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.fake_imap import FakeImapServer  # noqa: E402

PASSWORD = "zq7-very-secret-pw"


class CliTest(unittest.TestCase):
    def setUp(self):
        self.srv = FakeImapServer(user="me@gmail.com", password=PASSWORD)
        self.srv.mailbox.deliver("Alice Smith <alice@x.com>", "Lunch tomorrow?", "Free at 1pm?")
        self.srv.mailbox.deliver("Shop <deals@x.com>", "50% off", category="promotions")
        self.srv.mailbox.deliver("Old <o@x.com>", "already read", seen=True)
        self.home = tempfile.mkdtemp()
        self.write_config(PASSWORD)
        self.outputs = []

    def tearDown(self):
        self.srv.close()
        for out in self.outputs:
            self.assertNotIn(PASSWORD, out, "the app password leaked into CLI output")

    def write_config(self, pw):
        d = os.path.join(self.home, ".config", "gmail-notifier")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "config.ini"), "w") as f:
            f.write(f"[account me@gmail.com]\nlabel = Personal\nhost = 127.0.0.1\nport = {self.srv.port}\n"
                    f"ssl = false\napp_password = {pw}\n")

    def run_cli(self, *args, stdin=None):
        env = dict(os.environ, HOME=self.home, XDG_RUNTIME_DIR=self.home, PYTHONPATH=ROOT)
        env.pop("XDG_CONFIG_HOME", None)
        env.pop("XDG_STATE_HOME", None)
        p = subprocess.run([sys.executable, "-m", "gmail_notifier", *args], capture_output=True, text=True,
                           env=env, cwd=ROOT, timeout=30, stdin=stdin if stdin is not None else subprocess.DEVNULL)
        self.outputs += [p.stdout, p.stderr]
        return p

    def test_accounts_json_never_shows_password(self):
        p = self.run_cli("accounts", "--json")
        data = json.loads(p.stdout)
        self.assertEqual(data["accounts"], [{"email": "me@gmail.com", "label": "Personal", "host": "127.0.0.1",
                                             "port": self.srv.port, "password": "config"}])

    def test_check_json(self):
        p = self.run_cli("check", "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        acct = json.loads(p.stdout)["accounts"][0]
        self.assertTrue(acct["ok"])
        self.assertEqual(acct["unread"], 2)
        self.assertTrue(acct["idle"])

    def test_check_wrong_password_fails_cleanly(self):
        self.write_config("wrong-" + PASSWORD)
        p = self.run_cli("check", "--json")
        self.assertEqual(p.returncode, 1)
        acct = json.loads(p.stdout)["accounts"][0]
        self.assertFalse(acct["ok"])
        self.assertIn("AUTHENTICATIONFAILED", acct["error"])
        self.assertNotIn("wrong-", p.stdout)

    def test_unread_json_is_read_only_and_has_links(self):
        p = self.run_cli("unread", "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        msgs = json.loads(p.stdout)["messages"]
        self.assertEqual({m["subject"]: m["category"] for m in msgs},
                         {"Lunch tomorrow?": "primary", "50% off": "promotions"})
        self.assertTrue(all(m["link"].startswith("https://mail.google.com/mail/u/me%40gmail.com/#all/") for m in msgs))
        self.assertTrue(all("\\Seen" not in m.flags for m in self.srv.mailbox.msgs if m.uid < 3))
        p = self.run_cli("unread", "--json", "--category", "promotions")
        self.assertEqual([m["subject"] for m in json.loads(p.stdout)["messages"]], ["50% off"])

    def test_status_and_doctor_json(self):
        st = json.loads(self.run_cli("status", "--json").stdout)
        self.assertFalse(st["running"])
        doc = json.loads(self.run_cli("doctor", "--json").stdout)
        names = {c["check"]: c for c in doc["checks"]}
        self.assertTrue(names["config"]["ok"])
        self.assertTrue(names["password me@gmail.com"]["ok"])
        self.assertTrue(names[f"network 127.0.0.1:{self.srv.port}"]["ok"])
        self.assertFalse(names["tray app running"]["ok"])
        self.assertIn("fix", names["tray app running"])

    def test_add_account_refuses_without_a_terminal(self):
        p = self.run_cli("add-account", stdin=subprocess.PIPE)
        self.assertEqual(p.returncode, 2)
        self.assertIn("must be run by a person in a terminal", p.stderr)

    def test_remove_account(self):
        p = self.run_cli("remove-account", "me@gmail.com")
        self.assertEqual(p.returncode, 2)  # no terminal and no --yes: refuses
        p = self.run_cli("remove-account", "Personal", "--yes")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(self.run_cli("accounts", "--json").stdout)["accounts"], [])


if __name__ == "__main__":
    unittest.main()
