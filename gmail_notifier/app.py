"""The tray icon, its menu, and desktop notifications (GTK main thread)."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import time
from typing import Callable

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Notify", "0.7")
try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator
except (ValueError, ImportError):  # older Ubuntu
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import AppIndicator3 as AppIndicator
from gi.repository import Gio, GLib, Gtk, Notify  # noqa: E402

from . import config as config_mod  # noqa: E402
from . import keyring_store  # noqa: E402
from .models import CATEGORIES, CATEGORY_TITLES, AccountSnapshot, Message  # noqa: E402
from .state import StateStore  # noqa: E402
from .worker import AccountWorker  # noqa: E402

log = logging.getLogger(__name__)

ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
APP_ICON = os.path.join(ICON_DIR, "gmail-notifier.svg")
LATEST_COUNT = 5
CATCHUP_GATHER_SECONDS = 4  # collect catch-up mail from all accounts into one notification
MAX_INDIVIDUAL = 3  # more than this arriving at once -> one summary notification


def default_open_uri(uri: str) -> None:
    subprocess.Popen(["xdg-open", uri], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class TrayApp:
    def __init__(self, cfg: config_mod.Config, store: StateStore | None = None,
                 open_uri: Callable[[str], None] = default_open_uri,
                 password_lookup: Callable[[config_mod.Account], str] | None = None):
        self.cfg = cfg
        self.store = store or StateStore()
        self.open_uri = open_uri
        self.password_lookup = password_lookup or (lambda a: a.app_password or keyring_store.get_password(a.email))
        self.snapshots: dict[str, AccountSnapshot] = {}
        self.workers: dict[str, AccountWorker] = {}
        self.paused = False
        self.notifications: dict[int, Notify.Notification] = {}  # keep alive for click callbacks
        self.sent: list[tuple[str, str]] = []  # (summary, body) – for tests/debugging
        self._catchup: list[Message] = []
        self._catchup_timer = 0
        self._wall, self._mono = time.time(), time.monotonic()

        Notify.init("Gmail Notifier")
        caps = Notify.get_server_caps() or []
        self.can_markup = "body-markup" in caps
        self.can_actions = "actions" in caps

        self.indicator = AppIndicator.Indicator.new(
            "gmail-notifier", "gmail-notifier-read", AppIndicator.IndicatorCategory.COMMUNICATIONS)
        self.indicator.set_icon_theme_path(ICON_DIR)
        self.indicator.set_title("Gmail Notifier")
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.menu = Gtk.Menu()
        self.indicator.set_menu(self.menu)
        self.rebuild_menu()

    # -- lifecycle --------------------------------------------------------------
    def start(self) -> None:
        self._sync_workers()
        self._watch_system()
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, self._on_reload_signal)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self.quit)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self.quit)

    def quit(self, *_a) -> bool:
        for w in self.workers.values():
            w.stop()
        Gtk.main_quit()
        return GLib.SOURCE_REMOVE

    def reload(self) -> None:
        self.cfg = config_mod.load()
        self._sync_workers()

    def _on_reload_signal(self) -> bool:
        log.info("reloading config (SIGUSR1)")
        self.reload()
        return GLib.SOURCE_CONTINUE

    def _sync_workers(self) -> None:
        wanted = {a.email: a for a in self.cfg.accounts}
        for addr in list(self.workers):
            if addr not in wanted:
                self.workers.pop(addr).stop()
                self.snapshots.pop(addr, None)
        for addr, acct in wanted.items():
            if addr in self.workers:
                continue
            w = AccountWorker(acct, self.password_lookup(acct), self.store, self, self.cfg.settings)
            self.workers[addr] = w
            self.snapshots[addr] = w._copy()
            w.start()
        self.rebuild_menu()

    def refresh_all(self) -> None:
        for w in self.workers.values():
            w.kick()

    def _watch_system(self) -> None:
        """Reconnect immediately after suspend/resume or when the network returns,
        instead of waiting for a dead TCP connection to time out."""
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            bus.signal_subscribe("org.freedesktop.login1", "org.freedesktop.login1.Manager",
                                 "PrepareForSleep", "/org/freedesktop/login1", None,
                                 Gio.DBusSignalFlags.NONE, self._on_sleep_signal)
        except GLib.Error as e:
            log.info("no logind on system bus (%s); relying on clock-jump detection", e.message)
        mon = Gio.NetworkMonitor.get_default()
        mon.connect("network-changed", lambda _m, up: up and self._after(2, self.refresh_all))
        GLib.timeout_add_seconds(20, self._check_clock_jump)

    def _on_sleep_signal(self, _conn, _sender, _path, _iface, _sig, params) -> None:
        going_to_sleep = params.unpack()[0]
        if not going_to_sleep:
            log.info("resumed from suspend; reconnecting")
            self._after(3, self.refresh_all)

    def _check_clock_jump(self) -> bool:
        # Wall clock keeps running during suspend, the monotonic clock doesn't.
        wall, mono = time.time(), time.monotonic()
        if (wall - self._wall) - (mono - self._mono) > 60:
            log.info("clock jump detected (suspend?); reconnecting")
            self.refresh_all()
        self._wall, self._mono = wall, mono
        return GLib.SOURCE_CONTINUE

    @staticmethod
    def _after(seconds: float, fn: Callable[[], None]) -> None:
        GLib.timeout_add(int(seconds * 1000), lambda: (fn(), GLib.SOURCE_REMOVE)[1])

    # -- worker callbacks (called on worker threads) -----------------------------
    def on_snapshot(self, snap: AccountSnapshot) -> None:
        GLib.idle_add(self._apply_snapshot, snap)

    def on_new_mail(self, snap: AccountSnapshot, new: list[Message], catchup: bool) -> None:
        GLib.idle_add(self._handle_new_mail, snap, new, catchup)

    def _apply_snapshot(self, snap: AccountSnapshot) -> bool:
        if snap.email in self.workers:
            self.snapshots[snap.email] = snap
            self.rebuild_menu()
        return GLib.SOURCE_REMOVE

    def _handle_new_mail(self, snap: AccountSnapshot, new: list[Message], catchup: bool) -> bool:
        new = [m for m in new if m.category in self.cfg.settings.notify]
        if not new or self.paused:
            return GLib.SOURCE_REMOVE
        if catchup:
            self._catchup.extend(new)
            if not self._catchup_timer:
                self._catchup_timer = GLib.timeout_add_seconds(CATCHUP_GATHER_SECONDS, self._flush_catchup)
        elif len(new) <= MAX_INDIVIDUAL:
            for m in new:
                self.notify_message(m)
        else:
            self.notify_summary(new, f"{len(new)} new emails")
        return GLib.SOURCE_REMOVE

    def _flush_catchup(self) -> bool:
        msgs, self._catchup, self._catchup_timer = self._catchup, [], 0
        if len(msgs) == 1:
            self.notify_message(msgs[0])
        elif msgs:
            n = len(msgs)
            self.notify_summary(msgs, f"📬 {n} new email{'s' if n != 1 else ''} while you were away")
        return GLib.SOURCE_REMOVE

    # -- notifications ------------------------------------------------------------
    def label_for(self, addr: str) -> str:
        s = self.snapshots.get(addr)
        return s.label if s else addr

    def notify_message(self, m: Message) -> None:
        summary = f"{m.sender}  ·  {self.label_for(m.account)}"
        if self.can_markup:
            body = f"<b>{GLib.markup_escape_text(m.subject)}</b>"
            if m.snippet:
                body += "\n" + GLib.markup_escape_text(m.snippet)
        else:
            body = m.subject + (f"\n{m.snippet}" if m.snippet else "")
        self._show(summary, body,
                   default=lambda: self.open_message(m),
                   actions=[("open", "Open", lambda: self.open_message(m)),
                            ("read", "Mark as read", lambda: self.mark_read(m))])

    def notify_summary(self, msgs: list[Message], title: str) -> None:
        msgs = sorted(msgs, key=lambda m: m.date, reverse=True)
        per_account: dict[str, int] = {}
        for m in msgs:
            per_account[m.account] = per_account.get(m.account, 0) + 1
        esc = GLib.markup_escape_text if self.can_markup else (lambda s: s)
        lines = []
        if len(per_account) > 1:
            lines.append("  ·  ".join(f"{self.label_for(a)}: {c}" for a, c in per_account.items()))
        for m in msgs[:4]:
            lines.append(f"• {esc(m.sender)}: {esc(m.subject)}")
        if len(msgs) > 4:
            lines.append(f"…and {len(msgs) - 4} more – click the tray icon to see them")
        busiest = max(per_account, key=per_account.get)
        actions = [(f"inbox:{a}", f"Open {self.label_for(a)}",
                    (lambda a=a: self.open_uri(self.snapshots[a].inbox_link())))
                   for a in list(per_account)[:3]]
        self._show(title, "\n".join(lines),
                   default=lambda: self.open_uri(self.snapshots[busiest].inbox_link()),
                   actions=actions if len(per_account) > 1 else [])

    def _show(self, summary: str, body: str, default: Callable[[], None],
              actions: list[tuple[str, str, Callable[[], None]]]) -> None:
        self.sent.append((summary, body))
        n = Notify.Notification.new(summary, body, APP_ICON)
        n.set_hint("desktop-entry", GLib.Variant("s", "gmail-notifier"))
        n.set_category("email.arrived")
        if self.can_actions:
            n.add_action("default", "Open", lambda *_a: default())
            for key, label, cb in actions:
                n.add_action(key, label, lambda *_a, cb=cb: cb())
        n.connect("closed", lambda nn: self.notifications.pop(id(nn), None))
        self.notifications[id(n)] = n
        try:
            n.show()
        except GLib.Error as e:
            log.warning("could not show notification: %s", e.message)

    # -- actions --------------------------------------------------------------------
    def open_message(self, m: Message) -> None:
        self.open_uri(m.link())

    def mark_read(self, m: Message) -> None:
        w = self.workers.get(m.account)
        if not w:
            return
        snap = self.snapshots.get(m.account)
        if snap:  # optimistic: drop it from the menu right away
            snap.unread = [x for x in snap.unread if x.uid != m.uid]
            snap.unread_count = max(0, snap.unread_count - 1)
            self.rebuild_menu()
        w.mark_read([m.uid])

    # -- tray menu --------------------------------------------------------------------
    def rebuild_menu(self) -> None:
        for child in self.menu.get_children():
            self.menu.remove(child)
        snaps = [self.snapshots[a.email] for a in self.cfg.accounts if a.email in self.snapshots]
        total = sum(s.unread_count for s in snaps)
        multi = len(snaps) > 1

        self._header(self.menu, f"{total} unread" + (f" across {len(snaps)} accounts" if multi else "")
                     if snaps else "No accounts set up yet")
        if not snaps:
            self._item(self.menu, "Add a Gmail account…", self._launch_add_account)

        latest = sorted((m for s in snaps for m in s.unread), key=lambda m: m.date, reverse=True)[:LATEST_COUNT]
        if latest:
            self._sep(self.menu)
            self._header(self.menu, "LATEST")
            for m in latest:
                suffix = f"   ({self.label_for(m.account)})" if multi else ""
                self._item(self.menu, _ellipsize(f"{m.sender} — {m.subject}", 64) + suffix,
                           lambda m=m: self.open_message(m))

        if snaps:
            self._sep(self.menu)
        for s in snaps:
            item = Gtk.MenuItem.new_with_mnemonic(_mnemonic_safe(_account_line(s)))
            item.set_submenu(self._account_submenu(s))
            self.menu.append(item)

        self._sep(self.menu)
        self._item(self.menu, "Refresh now", self.refresh_all)
        pause = Gtk.CheckMenuItem.new_with_label("Pause notifications")
        pause.set_active(self.paused)
        pause.connect("toggled", lambda it: setattr(self, "paused", it.get_active()))
        self.menu.append(pause)
        if snaps:
            self._item(self.menu, "Add another account…", self._launch_add_account)
        self._item(self.menu, "Open settings folder", lambda: self.open_uri("file://" + config_mod.config_dir()))
        self._item(self.menu, "Quit", self.quit)
        self.menu.show_all()
        self._update_icon(snaps, total)

    def _account_submenu(self, s: AccountSnapshot) -> Gtk.Menu:
        sub = Gtk.Menu()
        self._item(sub, "Open inbox in browser", lambda: self.open_uri(s.inbox_link()))
        if s.status in ("auth_error", "error", "offline") and s.error:
            self._header(sub, "⚠ " + s.error)
            self._item(sub, "Retry now", lambda: self.workers[s.email].kick())
        by_cat: dict[str, list[Message]] = {c: [] for c in CATEGORIES}
        for m in s.unread:
            by_cat.setdefault(m.category, []).append(m)
        for cat, msgs in by_cat.items():
            if not msgs:
                continue
            self._sep(sub)
            self._header(sub, f"{CATEGORY_TITLES.get(cat, cat).upper()}  ·  {len(msgs)}")
            for m in msgs:
                self._item(sub, f"{_ago(m.date):>4}  " + _ellipsize(f"{m.sender} — {m.subject}", 70),
                           lambda m=m: self.open_message(m))
        if s.status == "ok" and not s.unread:
            self._sep(sub)
            self._header(sub, "Inbox zero 🎉")
        elif s.unread_count > len(s.unread):
            self._sep(sub)
            self._item(sub, f"…{s.unread_count - len(s.unread)} more unread in Gmail",
                       lambda: self.open_uri(s.inbox_link()))
        sub.show_all()
        return sub

    def _update_icon(self, snaps: list[AccountSnapshot], total: int) -> None:
        if any(s.status == "auth_error" for s in snaps):
            icon = "gmail-notifier-error"
        elif total:
            icon = "gmail-notifier-unread"
        else:
            icon = "gmail-notifier-read"
        self.indicator.set_icon_full(icon, f"{total} unread emails")
        self.indicator.set_label(str(total) if total else "", "999")

    @staticmethod
    def _item(menu: Gtk.Menu, label: str, cb: Callable[[], None]) -> Gtk.MenuItem:
        it = Gtk.MenuItem.new_with_mnemonic(_mnemonic_safe(label))
        it.connect("activate", lambda *_a: cb())
        menu.append(it)
        return it

    @staticmethod
    def _header(menu: Gtk.Menu, label: str) -> None:
        it = Gtk.MenuItem.new_with_mnemonic(_mnemonic_safe(label))
        it.set_sensitive(False)
        menu.append(it)

    @staticmethod
    def _sep(menu: Gtk.Menu) -> None:
        menu.append(Gtk.SeparatorMenuItem())

    def _launch_add_account(self) -> None:
        exe = os.path.expanduser("~/.local/bin/gmail-notifier")
        cmd = exe if os.path.exists(exe) else "gmail-notifier"
        for term in (["x-terminal-emulator", "-e", cmd, "add-account"],
                     ["gnome-terminal", "--", cmd, "add-account"]):
            try:
                subprocess.Popen(term)
                return
            except FileNotFoundError:
                continue


def _account_line(s: AccountSnapshot) -> str:
    state = {
        "ok": f"{s.unread_count} unread",
        "connecting": "connecting…",
        "offline": "offline – retrying",
        "auth_error": "⚠ login failed",
        "error": "⚠ error",
    }.get(s.status, s.status)
    return f"{s.label}  ({s.email})  —  {state}"


def _mnemonic_safe(s: str) -> str:
    # Menu labels treat "_" as a keyboard-shortcut marker; "__" is a literal underscore.
    return s.replace("_", "__")


def _ellipsize(s: str, n: int) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _ago(ts: float) -> str:
    d = max(0, time.time() - ts)
    if d < 3600:
        return f"{int(d // 60)}m"
    if d < 86400:
        return f"{int(d // 3600)}h"
    return f"{int(d // 86400)}d"
