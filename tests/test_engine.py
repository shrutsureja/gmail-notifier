import os
import queue
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gmail_notifier.config import Account, Settings  # noqa: E402
from gmail_notifier.imap import ImapConnection  # noqa: E402
from gmail_notifier.state import StateStore  # noqa: E402
from gmail_notifier.worker import AccountWorker  # noqa: E402
from tests.fake_imap import FakeImapServer  # noqa: E402


class Recorder:
    def __init__(self):
        self.snaps = queue.Queue()
        self.mail = queue.Queue()

    def on_snapshot(self, snap):
        self.snaps.put(snap)

    def on_new_mail(self, snap, new, catchup):
        self.mail.put((new, catchup))

    def wait_snapshot(self, pred, timeout=5):
        end = time.time() + timeout
        while time.time() < end:
            try:
                s = self.snaps.get(timeout=end - time.time())
            except queue.Empty:
                break
            if pred(s):
                return s
        raise AssertionError("expected snapshot never arrived")

    def wait_mail(self, timeout=5):
        return self.mail.get(timeout=timeout)

    def assert_no_mail(self, wait=0.6):
        try:
            got = self.mail.get(timeout=wait)
        except queue.Empty:
            return
        raise AssertionError(f"unexpected notification: {got}")


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.srv = FakeImapServer()
        self.mb = self.srv.mailbox
        self.tmp = tempfile.mkdtemp()
        self.store_path = os.path.join(self.tmp, "state.json")
        self.workers = []

    def tearDown(self):
        for w in self.workers:
            w.stop()
        self.srv.close()

    def start(self, password="secret-pass", settings=None):
        rec = Recorder()
        acct = Account(email="me@example.com", label="Me", host="127.0.0.1",
                       port=self.srv.port, use_ssl=False)
        w = AccountWorker(acct, password, StateStore(self.store_path), rec,
                          settings or Settings(idle_timeout_minutes=0.05))
        w.start()
        self.workers.append(w)
        return w, rec

    def test_first_run_lists_existing_unread_but_does_not_notify(self):
        self.mb.deliver("Old <old@x.com>", "old unread")
        self.mb.deliver("Read <r@x.com>", "already read", seen=True)
        _, rec = self.start()
        snap = rec.wait_snapshot(lambda s: s.status == "ok")
        self.assertEqual(snap.unread_count, 1)
        self.assertEqual([m.subject for m in snap.unread], ["old unread"])
        rec.assert_no_mail()

    def test_realtime_push_while_idle(self):
        _, rec = self.start()
        rec.wait_snapshot(lambda s: s.status == "ok")
        t0 = time.time()
        self.mb.deliver("Alice Smith <alice@x.com>", "Lunch tomorrow?", "Are you free at 1pm?")
        new, catchup = rec.wait_mail()
        self.assertLess(time.time() - t0, 2, "IDLE should deliver within ~a second")
        self.assertFalse(catchup)
        m = new[0]
        self.assertEqual((m.sender, m.sender_email, m.subject), ("Alice Smith", "alice@x.com", "Lunch tomorrow?"))
        self.assertIn("Are you free at 1pm?", m.snippet)
        self.assertEqual(m.link(), f"https://mail.google.com/mail/?authuser=me@example.com#all/{m.gm_msgid:x}")

    def test_catchup_after_downtime(self):
        w, rec = self.start()
        rec.wait_snapshot(lambda s: s.status == "ok")
        w.stop()
        w.join(3)
        # Laptop is "off": mail keeps arriving.
        for i in range(5):
            self.mb.deliver(f"Sender {i} <s{i}@x.com>", f"while away {i}")
        self.mb.deliver("Phone <p@x.com>", "read on phone", seen=True)
        _, rec2 = self.start()
        new, catchup = rec2.wait_mail()
        self.assertTrue(catchup)
        self.assertEqual([m.subject for m in new], [f"while away {i}" for i in range(5)])
        rec2.assert_no_mail()  # nothing notified twice

    def test_no_duplicate_notifications_across_restarts(self):
        w, rec = self.start()
        rec.wait_snapshot(lambda s: s.status == "ok")
        self.mb.deliver("A <a@x.com>", "once")
        rec.wait_mail()
        w.stop()
        w.join(3)
        _, rec2 = self.start()
        rec2.wait_snapshot(lambda s: s.status == "ok")
        rec2.assert_no_mail()

    def test_idle_waits_quietly_when_nothing_changes(self):
        # Regression: a leftover EXISTS from SELECT made the worker re-sync in a tight loop.
        self.mb.deliver("A <a@x.com>", "existing")
        _, rec = self.start(settings=Settings(idle_timeout_minutes=5))
        rec.wait_snapshot(lambda s: s.status == "ok")
        time.sleep(2)
        self.assertEqual(rec.snaps.qsize(), 0, "worker kept re-syncing with no mailbox changes")
        self.mb.deliver("B <b@x.com>", "now one change")
        new, _ = rec.wait_mail()
        self.assertEqual(new[0].subject, "now one change")

    def test_big_old_backlog_is_counted_but_not_shown(self):
        for i in range(200):
            self.mb.deliver(f"Shop{i} <s{i}@x.com>", f"old deal {i}", category="promotions", age_days=30)
        for i in range(3):
            self.mb.deliver(f"Friend{i} <f{i}@x.com>", f"recent hello {i}")
        for i in range(6):
            self.mb.deliver(f"Store{i} <n{i}@x.com>", f"new deal {i}", category="promotions")
        _, rec = self.start()
        snap = rec.wait_snapshot(lambda s: s.status == "ok")
        self.assertEqual(snap.unread_count, 209)  # everything unread, however old
        self.assertEqual(snap.recent_count, 9)  # only the last 7 days
        self.assertEqual(snap.category_counts["primary"], 3)
        self.assertEqual(snap.category_counts["promotions"], 6)
        shown = [m.subject for m in snap.unread]
        # newest few of *each* tab: all 3 primary are listed, promotions capped at 4
        self.assertEqual(sorted(s for s in shown if s.startswith("recent")), [f"recent hello {i}" for i in range(3)])
        self.assertEqual(len([s for s in shown if "deal" in s]), 4)
        self.assertFalse(any(s.startswith("old deal") for s in shown))

    def test_categories(self):
        _, rec = self.start()
        rec.wait_snapshot(lambda s: s.status == "ok")
        for cat in ("primary", "social", "promotions", "updates"):
            self.mb.deliver(f"{cat} <{cat}@x.com>", f"a {cat} mail", category=cat)
        got = {}
        while len(got) < 4:
            new, _ = rec.wait_mail()
            got.update({m.subject: m.category for m in new})
        self.assertEqual(got, {f"a {c} mail": c for c in ("primary", "social", "promotions", "updates")})

    def test_read_elsewhere_disappears_from_tray(self):
        _, rec = self.start()
        rec.wait_snapshot(lambda s: s.status == "ok")
        m = self.mb.deliver("A <a@x.com>", "read me on phone")
        rec.wait_mail()
        self.mb.set_seen(m.uid)
        snap = rec.wait_snapshot(lambda s: s.unread_count == 0)
        self.assertEqual(snap.unread, [])

    def test_mark_read_action(self):
        w, rec = self.start()
        rec.wait_snapshot(lambda s: s.status == "ok")
        m = self.mb.deliver("A <a@x.com>", "mark me")
        rec.wait_mail()
        w.mark_read([m.uid])
        rec.wait_snapshot(lambda s: s.unread_count == 0)
        self.assertIn("\\Seen", m.flags)

    def test_bad_password_reports_auth_error(self):
        _, rec = self.start(password="wrong")
        snap = rec.wait_snapshot(lambda s: s.status == "auth_error")
        self.assertIn("app password", snap.error)

    def test_reconnects_after_connection_drop_and_catches_up(self):
        w, rec = self.start()
        rec.wait_snapshot(lambda s: s.status == "ok")
        logins = self.mb.logins
        self.mb.drop_all_connections()
        self.mb.deliver("A <a@x.com>", "arrived during the blip")
        new, _ = rec.wait_mail(timeout=10)
        self.assertEqual(new[0].subject, "arrived during the blip")
        self.assertGreater(self.mb.logins, logins)

    def test_kick_reconnects_immediately(self):
        w, rec = self.start(settings=Settings(idle_timeout_minutes=30))
        rec.wait_snapshot(lambda s: s.status == "ok")
        logins = self.mb.logins
        w.kick()
        deadline = time.time() + 3
        while self.mb.logins == logins and time.time() < deadline:
            time.sleep(0.05)
        self.assertGreater(self.mb.logins, logins)

    def test_uidvalidity_change_rebaselines_without_flood(self):
        w, rec = self.start()
        rec.wait_snapshot(lambda s: s.status == "ok")
        w.stop()
        w.join(3)
        self.mb.deliver("A <a@x.com>", "x")
        self.mb.reset_uidvalidity()
        _, rec2 = self.start()
        rec2.wait_snapshot(lambda s: s.status == "ok")
        rec2.assert_no_mail()

    def test_uid_star_range_edge_case(self):
        self.mb.deliver("A <a@x.com>", "only one")
        c = ImapConnection("127.0.0.1", self.srv.port, False, "me@example.com", "secret-pass")
        c.open()
        c.select_inbox()
        self.assertEqual(c.uids_after(1), [])  # "2:*" would naively return UID 1
        c.close()

    def test_html_only_snippet_and_encoded_subject(self):
        _, rec = self.start()
        rec.wait_snapshot(lambda s: s.status == "ok")
        self.mb.deliver("Bänk <b@x.com>", "Ünïcode subject ✓", "Your <b>statement</b> is ready", html=True)
        new, _ = rec.wait_mail()
        self.assertEqual(new[0].subject, "Ünïcode subject ✓")
        self.assertEqual(new[0].sender, "Bänk")
        self.assertIn("Your statement is ready", new[0].snippet)
        self.assertNotIn("<", new[0].snippet)


if __name__ == "__main__":
    unittest.main()
