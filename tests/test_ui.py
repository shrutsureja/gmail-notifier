"""Runs the real tray app against the fake IMAP server on a headless desktop
(Xvfb + session D-Bus + dunst). Start it with tests/run_ui_tests.sh."""

import os
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gi.repository import GLib  # noqa: E402

from gmail_notifier.app import TrayApp  # noqa: E402
from gmail_notifier.config import Account, Config, Settings  # noqa: E402
from gmail_notifier.state import StateStore  # noqa: E402
from tests.fake_imap import FakeImapServer  # noqa: E402


def pump_until(pred, timeout=8.0):
    ctx = GLib.MainContext.default()
    end = time.time() + timeout
    while time.time() < end:
        while ctx.pending():
            ctx.iteration(False)
        if pred():
            return True
        time.sleep(0.05)
    return False


def menu_labels(menu, depth=0):
    out = []
    for it in menu.get_children():
        label = it.get_label() if hasattr(it, "get_label") else None
        if label:
            out.append("  " * depth + label.replace("__", "_"))
        sub = it.get_submenu() if hasattr(it, "get_submenu") else None
        if sub:
            out += menu_labels(sub, depth + 1)
    return out


class TrayUITest(unittest.TestCase):
    def setUp(self):
        subprocess.run(["dunstctl", "close-all"], check=False)
        self.servers = [FakeImapServer(user="me@gmail.com"), FakeImapServer(user="work@gmail.com")]
        self.opened = []
        accounts = [Account(email=s.mailbox.user, label=lbl, host="127.0.0.1", port=s.port, use_ssl=False)
                    for s, lbl in zip(self.servers, ("Personal", "Work"))]
        cfg = Config(accounts=accounts, settings=Settings(idle_timeout_minutes=5))
        self.state_path = os.path.join(tempfile.mkdtemp(), "state.json")
        self.cfg = cfg
        self.app = self._make_app()

    def _make_app(self):
        app = TrayApp(self.cfg, store=StateStore(self.state_path), open_uri=self.opened.append,
                      password_lookup=lambda a: "secret-pass")
        app.start()
        return app

    def tearDown(self):
        for w in self.app.workers.values():
            w.stop()
        for s in self.servers:
            s.close()

    def wait_ready(self):
        self.assertTrue(pump_until(lambda: all(s.status == "ok" for s in self.app.snapshots.values())),
                        f"accounts never connected: {[(s.email, s.status, s.error) for s in self.app.snapshots.values()]}")

    def test_menu_groups_by_account_and_category(self):
        p, w = (s.mailbox for s in self.servers)
        p.deliver("Alice <a@x.com>", "Lunch tomorrow?")
        p.deliver("Shop <deals@x.com>", "50% off everything", category="promotions")
        w.deliver("Boss <boss@x.com>", "Q4 planning", category="updates")
        self.wait_ready()
        labels = menu_labels(self.app.menu)
        print("\n".join(labels))
        self.assertEqual(labels[0], "3 unread this week across 2 accounts")
        self.assertIn("LATEST", labels)
        self.assertTrue(any(l.startswith("Personal  (me@gmail.com)  —  2 unread") for l in labels))
        self.assertTrue(any(l.startswith("Work  (work@gmail.com)  —  1 unread") for l in labels))
        self.assertTrue(any("PRIMARY  ·  1" in l for l in labels))
        self.assertTrue(any("PROMOTIONS  ·  1" in l for l in labels))
        self.assertTrue(any("UPDATES  ·  1" in l for l in labels))
        self.assertEqual(self.app.indicator.get_label(), "3")
        self.assertEqual(self.app.indicator.get_icon(), "gmail-notifier-unread")

    def test_new_mail_pops_notification_and_click_opens_that_email(self):
        self.wait_ready()
        self.servers[0].mailbox.deliver("Alice Smith <alice@x.com>", "Dinner on Friday?", "Let me know by Thursday")
        self.assertTrue(pump_until(lambda: self.app.sent))
        summary, body = self.app.sent[-1]
        self.assertEqual(summary, "Alice Smith  ·  Personal")
        self.assertIn("Dinner on Friday?", body)
        self.assertIn("Let me know by Thursday", body)
        # The notification really reached the desktop's notification daemon:
        time.sleep(0.5)
        # ...and clicking it (dunst "default action") opens that exact email:
        subprocess.run(["dunstctl", "action", "0"], check=False)
        self.assertTrue(pump_until(lambda: self.opened), "clicking the notification didn't open anything")
        self.assertRegex(self.opened[-1], r"^https://mail\.google\.com/mail/\?authuser=me@gmail\.com#all/[0-9a-f]+$")

    def test_catchup_after_being_off_is_one_summary_notification(self):
        self.wait_ready()
        for w in self.app.workers.values():
            w.stop()
        # laptop off for a while...
        for i in range(4):
            self.servers[0].mailbox.deliver(f"P{i} <p{i}@x.com>", f"personal {i}")
        for i in range(2):
            self.servers[1].mailbox.deliver(f"W{i} <w{i}@x.com>", f"work {i}")
        self.app = self._make_app()
        self.assertTrue(pump_until(lambda: self.app.sent, timeout=12))
        self.assertEqual(len(self.app.sent), 1, self.app.sent)
        summary, body = self.app.sent[0]
        self.assertEqual(summary, "6 new emails while you were away")
        self.assertIn("Personal: 4", body)
        self.assertIn("Work: 2", body)

    def test_trickle_of_mail_becomes_one_growing_summary(self):
        self.app.GATHER_SECONDS = 0.3
        self.wait_ready()
        mb = self.servers[0].mailbox
        for i in range(7):
            mb.deliver(f"List{i} <l{i}@x.com>", f"thread reply {i}")
            pump_until(lambda: False, timeout=0.7)  # arrive ~0.7s apart: separate syncs
        self.assertTrue(pump_until(lambda: len(self.app.sent) >= 7, timeout=5))
        pump_until(lambda: False, timeout=0.8)
        titles = [t for t, _ in self.app.sent]
        print(titles)
        self.assertEqual(titles[:3], ["List0  ·  Personal", "List1  ·  Personal", "List2  ·  Personal"])
        self.assertEqual(titles[-1], "4 more new emails")
        # the extra mail updates ONE popup instead of adding new ones
        self.assertEqual(len(self.app.notifications), 4, "expected 3 popups + 1 updating summary")

    def test_big_backlog_menu(self):
        mb = self.servers[0].mailbox
        for i in range(30):
            mb.deliver(f"Shop{i} <s{i}@x.com>", f"old deal {i}", category="promotions", age_days=40)
        for i in range(9):
            mb.deliver(f"Store{i} <n{i}@x.com>", f"deal {i}", category="promotions")
        mb.deliver("Alice <a@x.com>", "Lunch?")
        self.wait_ready()
        labels = menu_labels(self.app.menu)
        print("\n".join(labels))
        self.assertEqual(labels[0], "10 unread this week across 2 accounts")  # all tabs notify by default
        self.app.cfg.settings.notify = ["primary", "updates"]
        self.app.rebuild_menu()
        labels = menu_labels(self.app.menu)
        self.assertEqual(labels[0], "1 unread this week across 2 accounts")  # promotions now don't count
        self.assertTrue(any("Personal  (me@gmail.com)  —  10 this week · 40 unread" in l for l in labels))
        self.assertTrue(any("PROMOTIONS  ·  9" in l for l in labels))
        self.assertTrue(any(l.strip() == "…5 more in Promotions" for l in labels))
        self.assertTrue(any(l.strip() == "All 40 unread in Gmail…" for l in labels))
        latest = labels[labels.index("LATEST") + 1:]
        self.assertTrue(latest[0].startswith("Alice — Lunch?"))
        self.assertFalse(any("deal" in l for l in latest[:1]))

    def test_remove_account_from_tray(self):
        os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
        self.wait_ready()
        self.app.remove_account("work@gmail.com")
        self.assertEqual(list(self.app.workers), ["me@gmail.com"])
        labels = menu_labels(self.app.menu)
        self.assertFalse(any("work@gmail.com" in l for l in labels))
        self.assertTrue(any(l.strip() == "Remove this account…" for l in labels))

    def test_pause_suppresses_notifications(self):
        self.wait_ready()
        self.app.paused = True
        self.servers[0].mailbox.deliver("A <a@x.com>", "quiet please")
        self.assertTrue(pump_until(lambda: any(s.unread_count for s in self.app.snapshots.values())))
        self.assertEqual(self.app.sent, [])


if __name__ == "__main__":
    unittest.main()
