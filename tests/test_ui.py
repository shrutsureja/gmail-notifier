"""Runs the real tray app against the fake IMAP server on a headless desktop
(Xvfb + session D-Bus + dunst). Start it with tests/run_ui_tests.sh."""

import os
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

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


def menu_labels(menu_or_panel, depth=0):
    """Every piece of text in the native menu or in the panel window."""
    out = []
    def walk(w):
        if isinstance(w, Gtk.Label):
            t = w.get_text()
            if t:
                out.append(t.replace("__", "_"))
        if hasattr(w, "get_children"):
            for c in w.get_children():
                walk(c)
    if hasattr(menu_or_panel, "body"):  # the panel
        walk(menu_or_panel.body)
        walk(menu_or_panel.footer)
    else:
        walk(menu_or_panel)
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

    def panel_labels(self, expand=("me@gmail.com", "work@gmail.com")):
        """All text in the panel window, with the given accounts expanded."""
        self.app.toggle_panel() if getattr(self.app, "panel", None) is None else None
        self.app.panel.show_all()
        self.app.panel.expanded = set(expand)
        self.app.panel._auto_expanded = True
        self.app.panel.refresh()
        pump_until(lambda: False, 0.2)
        return menu_labels(self.app.panel)

    def wait_ready(self):
        self.assertTrue(pump_until(lambda: all(s.status == "ok" for s in self.app.snapshots.values())),
                        f"accounts never connected: {[(s.email, s.status, s.error) for s in self.app.snapshots.values()]}")

    def test_panel_groups_by_account_and_category(self):
        p, w = (s.mailbox for s in self.servers)
        p.deliver("Alice <a@x.com>", "Lunch tomorrow?")
        p.deliver("Shop <deals@x.com>", "50% off everything", category="promotions")
        w.deliver("Boss <boss@x.com>", "Q4 planning", category="updates")
        self.wait_ready()
        labels = self.panel_labels()
        print("\n".join(labels))
        self.assertEqual(labels[0], "3 unread this week across 2 accounts")
        self.assertIn("LATEST", labels)
        self.assertIn("Personal  (me@gmail.com)", labels)
        self.assertIn("2 unread", labels)
        self.assertIn("Work  (work@gmail.com)", labels)
        self.assertIn("PRIMARY  ·  1", labels)
        self.assertIn("PROMOTIONS  ·  1", labels)
        self.assertIn("UPDATES  ·  1", labels)
        for text in ("Refresh now", "Pause notifications", "Quit"):
            self.assertIn(text, labels)
        self.assertEqual(self.app.indicator.get_label(), "3")
        self.assertEqual(self.app.indicator.get_icon(), "gmail-notifier-unread")

    def test_tray_menu_is_small_and_opens_the_panel(self):
        self.wait_ready()
        items = [it.get_label() for it in self.app.menu.get_children() if hasattr(it, "get_label") and it.get_label()]
        self.assertEqual([i.replace("__", "_").replace("<b>", "").replace("</b>", "") for i in items],
                         ["0 unread this week", "Open Gmail Notifier", "Refresh now", "Pause notifications", "Quit"])
        self.assertIsNone(getattr(self.app, "panel", None))
        self.app.toggle_panel()
        self.assertTrue(self.app.panel.get_visible())
        self.app.toggle_panel()
        self.assertFalse(self.app.panel.get_visible())

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

    def test_big_backlog_panel(self):
        mb = self.servers[0].mailbox
        for i in range(30):
            mb.deliver(f"Shop{i} <s{i}@x.com>", f"old deal {i}", category="promotions", age_days=40)
        for i in range(9):
            mb.deliver(f"Store{i} <n{i}@x.com>", f"deal {i}", category="promotions")
        mb.deliver("Alice <a@x.com>", "Lunch?")
        self.wait_ready()
        labels = self.panel_labels(expand=("me@gmail.com",))
        self.assertEqual(labels[0], "10 unread this week across 2 accounts")  # all tabs notify by default
        self.app.cfg.settings.notify = ["primary", "updates"]
        labels = self.panel_labels(expand=("me@gmail.com",))
        self.assertEqual(labels[0], "1 unread this week across 2 accounts")  # promotions now don't count
        self.assertIn("10 this week · 40 unread", labels)
        self.assertIn("PROMOTIONS  ·  9", labels)
        self.assertIn("…5 more in Promotions", labels)
        self.assertIn("All 40 unread in Gmail…", labels)
        latest = labels[labels.index("LATEST") + 1:]
        self.assertEqual(latest[0], "Alice — Lunch?")

    def test_remove_account_from_tray(self):
        os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
        self.wait_ready()
        self.app.remove_account("work@gmail.com")
        self.assertEqual(list(self.app.workers), ["me@gmail.com"])
        labels = self.panel_labels(expand=("me@gmail.com",))
        self.assertFalse(any("work@gmail.com" in l for l in labels))
        self.assertIn("Remove this account…", labels)

    def test_pause_suppresses_notifications(self):
        self.wait_ready()
        self.app.paused = True
        self.servers[0].mailbox.deliver("A <a@x.com>", "quiet please")
        self.assertTrue(pump_until(lambda: any(s.unread_count for s in self.app.snapshots.values())))
        self.assertEqual(self.app.sent, [])


if __name__ == "__main__":
    unittest.main()
