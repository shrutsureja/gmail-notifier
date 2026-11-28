"""One background thread per account.

Loop:  connect -> sync -> IDLE until something changes -> sync -> IDLE ...
Any network error: drop the connection, wait (3s, 6s, ... up to 60s), retry.
kick() wakes the thread immediately (used on resume from suspend, when the
network comes back, and for "Refresh now").
"""

from __future__ import annotations

import imaplib
import logging
import ssl
import threading
import time
from typing import Callable, Protocol

from .config import Account, Settings
from .imap import IdleTimeout, ImapConnection, imap_date
from .models import CATEGORIES, AccountSnapshot, Message
from .state import AccountState, StateStore

log = logging.getLogger(__name__)

# If we couldn't talk to the server for longer than this, the first sync after
# reconnecting is a "while you were away" catch-up (one summary notification).
CATCHUP_AFTER_SECONDS = 120
MAX_NEW_TO_FETCH = 50


class Listener(Protocol):
    def on_snapshot(self, snap: AccountSnapshot) -> None: ...
    def on_new_mail(self, snap: AccountSnapshot, new: list[Message], catchup: bool) -> None: ...


class AccountWorker(threading.Thread):
    def __init__(self, account: Account, password: str, store: StateStore,
                 listener: Listener, settings: Settings,
                 connection_factory: Callable[..., ImapConnection] = ImapConnection):
        super().__init__(name=f"imap-{account.email}", daemon=True)
        self.account = account
        self.password = password
        self.store = store
        self.listener = listener
        self.settings = settings
        self._factory = connection_factory
        self._stopping = threading.Event()
        self._wake = threading.Event()
        self._conn: ImapConnection | None = None
        self._cache: dict[int, Message] = {}
        self._last_alive = 0.0  # wall clock; 0 = never synced in this run
        self.snapshot = AccountSnapshot(email=account.email, label=account.label)

    # -- control (any thread) -------------------------------------------------
    def stop(self) -> None:
        self._stopping.set()
        self.kick()

    def kick(self) -> None:
        self._wake.set()
        conn = self._conn
        if conn is not None:
            conn.interrupt()

    # -- thread body ------------------------------------------------------------
    def run(self) -> None:
        backoff = 3.0
        while not self._stopping.is_set():
            self._wake.clear()
            conn = self._factory(self.account.host, self.account.port, self.account.use_ssl,
                                 self.account.email, self.password)
            try:
                if not self.password:
                    raise imaplib.IMAP4.error("no app password stored for this account")
                conn.open()
                self._conn = conn
                catchup = (self._last_alive == 0.0
                           or time.time() - self._last_alive > CATCHUP_AFTER_SECONDS)
                self._sync(conn, catchup=catchup)
                backoff = 3.0
                while not self._stopping.is_set():
                    try:
                        conn.idle(self.settings.idle_timeout_minutes * 60)
                    except IdleTimeout:
                        self._last_alive = time.time()
                        break  # reconnect quietly; a fresh socket is cheap
                    self._sync(conn, catchup=False)
            except (OSError, ssl.SSLError, EOFError, ConnectionError, imaplib.IMAP4.abort) as e:
                if self._stopping.is_set():
                    break
                log.info("%s: connection problem: %s", self.account.email, e)
                if not self._wake.is_set():
                    self._set_status("offline", "No connection – retrying…")
                self._sleep(backoff if not self._wake.is_set() else 1)
                backoff = min(backoff * 2, 60)
            except imaplib.IMAP4.error as e:
                if self._stopping.is_set():
                    break
                msg = str(e)
                if "AUTHENTICATIONFAILED" in msg or "Invalid credentials" in msg or "no app password" in msg:
                    self._set_status("auth_error", _auth_hint(msg))
                    self._sleep(300)  # don't hammer Google with bad passwords
                else:
                    self._set_status("error", msg)
                    self._sleep(backoff)
                    backoff = min(backoff * 2, 60)
            finally:
                self._conn = None
                conn.close()

    def _sleep(self, seconds: float) -> None:
        self._wake.wait(seconds)
        self._wake.clear()

    def _set_status(self, status: str, error: str = "") -> None:
        if self.snapshot.status == status and self.snapshot.error == error:
            return
        self.snapshot.status, self.snapshot.error = status, error
        self.listener.on_snapshot(self._copy())

    def _copy(self) -> AccountSnapshot:
        s = self.snapshot
        return AccountSnapshot(email=s.email, label=s.label, status=s.status, error=s.error,
                               unread_count=s.unread_count, recent_count=s.recent_count,
                               recent_days=s.recent_days, category_counts=dict(s.category_counts),
                               unread=list(s.unread))

    # -- the actual work --------------------------------------------------------
    def _sync(self, conn: ImapConnection, catchup: bool) -> None:
        email = self.account.email
        uidvalidity, uidnext = conn.select_inbox(readonly=True)
        st = self.store.get(email)

        new_uids: list[int] = []
        if st is None or st.uidvalidity != uidvalidity:
            # First run for this account (or the server renumbered the mailbox):
            # remember where we are but don't notify about the existing backlog.
            top = (uidnext - 1) if uidnext else conn.max_uid()
            st = AccountState(uidvalidity=uidvalidity, last_uid=top)
        else:
            new_uids = conn.uids_after(st.last_uid)

        unseen = conn.unseen_uids()
        unseen_set = set(unseen)
        new_unseen = [u for u in new_uids if u in unseen_set][-MAX_NEW_TO_FETCH:]

        # Big inboxes often have thousands of old unread emails. The badge and
        # menu only count unread from the last `recent_days` days.
        days = self.settings.recent_days
        criteria = ["UNSEEN"] + (["SINCE", imap_date(time.time() - days * 86400)] if days > 0 else [])
        window = sorted(conn.search(*criteria)) if days > 0 else unseen
        tabs = conn.category_uids(*criteria)
        cat_of = {u: "primary" for u in window}
        for name, uids in tabs.items():
            for u in uids:
                if cat_of.get(u) == "primary":
                    cat_of[u] = name
        by_cat: dict[str, list[int]] = {c: [] for c in CATEGORIES}
        for u in window:
            by_cat.setdefault(cat_of[u], []).append(u)
        if tabs:  # Gmail: the newest few of *each* tab, so Primary isn't buried under Promotions
            shown = {u for uids in by_cat.values() for u in uids[-self.settings.max_items_per_category:]}
        else:
            shown = set(window[-self.settings.max_items_per_account:])

        wanted = shown | set(new_unseen)
        missing = sorted(u for u in wanted if u not in self._cache)
        for m in conn.fetch(missing, categorize=not tabs):
            self._cache[m.uid] = m
        self._cache = {u: m for u, m in self._cache.items() if u in wanted}
        for u, m in self._cache.items():
            if u in cat_of:
                m.category = cat_of[u]
            elif tabs:  # new mail outside the window (odd dates): look it up directly
                m.category = next((n for n, uids in tabs.items() if u in uids), "primary")

        unread = sorted((self._cache[u] for u in shown if u in self._cache), key=lambda m: m.uid, reverse=True)
        new_msgs = [self._cache[u] for u in new_unseen if u in self._cache]

        if new_uids:
            st = AccountState(uidvalidity=uidvalidity, last_uid=max(st.last_uid, max(new_uids)))
        self.store.set(email, st)
        self._last_alive = time.time()

        self.snapshot.status, self.snapshot.error = "ok", ""
        self.snapshot.unread_count = len(unseen)
        self.snapshot.recent_count = len(window)
        self.snapshot.recent_days = days
        self.snapshot.category_counts = {c: len(v) for c, v in by_cat.items()}
        self.snapshot.unread = unread
        snap = self._copy()
        self.listener.on_snapshot(snap)
        if new_msgs:
            self.listener.on_new_mail(snap, new_msgs, catchup)

    # -- actions ---------------------------------------------------------------
    def mark_read(self, uids: list[int], done: Callable[[], None] | None = None) -> None:
        """Marks messages read on the server using a short-lived second connection.
        The main connection's IDLE then sees the flag change and refreshes."""
        def work():
            conn = self._factory(self.account.host, self.account.port, self.account.use_ssl,
                                 self.account.email, self.password)
            try:
                conn.open()
                conn.select_inbox(readonly=False)
                conn.mark_seen(uids)
            except Exception as e:  # noqa: BLE001 - surfaced in the log only
                log.warning("%s: mark as read failed: %s", self.account.email, e)
            finally:
                conn.close()
                if done:
                    done()
        threading.Thread(target=work, daemon=True).start()


def _auth_hint(msg: str) -> str:
    if "no app password" in msg:
        return "No password saved – run: gmail-notifier add-account"
    return "Login failed – check the app password (gmail-notifier add-account)"
