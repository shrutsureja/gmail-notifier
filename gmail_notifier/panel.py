"""The panel window drawn to match design/mockups/Main.dc.html.

A GNOME tray menu can only show plain text, so the colored tab markers, the
expanding account rows and the toggle live here, in a small window that opens
from the tray icon (menu item "Open Gmail Notifier", or middle-click the icon).
Colors and sizes come from design/tokens.json.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Callable

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from .models import CATEGORIES, CATEGORY_TITLES, AccountSnapshot, Message  # noqa: E402

if TYPE_CHECKING:
    from .app import TrayApp

PANEL_WIDTH = 460
MAX_HEIGHT = 640

CSS = b"""
window.gn-panel { background: #2b2b2b; border: 1px solid #424242; border-radius: 14px;
  font-family: Ubuntu, "Segoe UI", sans-serif; font-size: 14px; color: #f2f2f2; }
.gn-panel scrolledwindow, .gn-panel viewport { background: transparent; }
.gn-panel button.gn-row { background: none; border: none; box-shadow: none; border-radius: 8px;
  min-height: 32px; padding: 0 14px; color: #f2f2f2; text-shadow: none; }
.gn-panel button.gn-row:hover { background: #3b3b3b; }
.gn-panel button.gn-row:focus { outline: 2px solid #e95420; outline-offset: -2px; }
.gn-panel .gn-muted { color: #b5b5b5; }
.gn-panel .gn-small { font-size: 13px; }
.gn-panel .gn-link { color: #f6a27f; }
.gn-panel .gn-label { font-size: 11px; letter-spacing: 1px; color: #b5b5b5; font-weight: 500; }
.gn-panel .gn-header { color: #b5b5b5; font-size: 13px; padding: 8px 14px; }
.gn-panel .gn-warn { color: #fdd663; font-size: 13px; }
.gn-panel .gn-mono { font-family: "Ubuntu Mono", monospace; font-size: 13px; color: #b5b5b5; }
.gn-panel separator { background: #424242; min-height: 1px; margin: 4px 6px; }
.gn-panel .gn-account-open { background: #333333; border-radius: 10px; }
.gn-panel .gn-dot { min-width: 8px; min-height: 8px; border-radius: 2px; }
.gn-panel .gn-dot-primary { background: #8ab4f8; }
.gn-panel .gn-dot-updates { background: #fdd663; }
.gn-panel .gn-dot-social { background: #81c995; }
.gn-panel .gn-dot-promotions { background: #f28b82; }
.gn-panel switch { background: #555555; border: none; min-height: 20px; min-width: 36px; border-radius: 10px; }
.gn-panel switch:checked { background: #e95420; }
.gn-panel switch slider { background: #ffffff; border: none; border-radius: 8px; min-width: 16px; min-height: 16px; margin: 2px; }
"""

_css_loaded = False


def _load_css() -> None:
    global _css_loaded
    if _css_loaded:
        return
    prov = Gtk.CssProvider()
    prov.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _css_loaded = True


def _label(text: str, *classes: str, ellipsize: bool = False, xalign: float = 0.0) -> Gtk.Label:
    lab = Gtk.Label(label=text, xalign=xalign)
    for c in classes:
        lab.get_style_context().add_class(c)
    if ellipsize:
        lab.set_ellipsize(Pango.EllipsizeMode.END)
        lab.set_max_width_chars(1)  # let the label shrink; hexpand gives it the room
    return lab


class Panel(Gtk.Window):
    def __init__(self, app: "TrayApp"):
        _load_css()
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.app = app
        self.expanded: set[str] = set()
        self._auto_expanded = False
        self._built_for = None
        self.set_title("Gmail Notifier")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_keep_above(True)
        self.set_default_size(PANEL_WIDTH, -1)
        self.get_style_context().add_class("gn-panel")
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.connect("key-press-event", self._on_key)
        self.connect("focus-out-event", self._on_focus_out)
        self.connect("delete-event", lambda *_a: (self.hide(), True)[1])

        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_propagate_natural_height(True)
        self.scroll.set_max_content_height(MAX_HEIGHT)
        self.scroll.set_min_content_width(PANEL_WIDTH)
        self.add(self.scroll)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.body.set_border_width(8)
        self.scroll.add(self.body)
        self.footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.footer.set_border_width(8)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.remove(self.scroll)
        root.pack_start(self.scroll, True, True, 0)
        root.pack_start(self.footer, False, False, 0)  # stays visible however long the list is
        self.add(root)
        self.refresh()

    # -- show / hide -------------------------------------------------------------
    def toggle(self) -> None:
        if self.get_visible():
            self.hide()
        else:
            self.refresh()
            self.show_all()
            self._place()
            self.present()

    def _place(self) -> None:
        """Top-right, under the top bar. (Wayland ignores this and places it itself.)"""
        try:
            disp = Gdk.Display.get_default()
            mon = disp.get_primary_monitor() or disp.get_monitor(0)
            geo = mon.get_geometry()
            # never taller than the screen: the list scrolls, the footer stays
            self.scroll.set_max_content_height(max(200, min(MAX_HEIGHT, geo.height - 36 - 24 - 230)))
            self.move(geo.x + geo.width - PANEL_WIDTH - 24, geo.y + 36)
        except Exception:  # noqa: BLE001
            pass

    def _on_key(self, _w, ev) -> bool:
        if ev.keyval == Gdk.KEY_Escape:
            self.hide()
            return True
        return False

    def _on_focus_out(self, *_a) -> bool:
        # A short delay avoids closing during the focus shuffle while opening.
        GLib.timeout_add(150, lambda: (self.hide() if self.get_visible() and not self.is_active() else None,
                                       GLib.SOURCE_REMOVE)[1])
        return False

    def _act(self, fn: Callable[[], None], close: bool = True) -> Callable[..., None]:
        def run(*_a):
            if close:
                self.hide()
            fn()
        return run

    # -- content -----------------------------------------------------------------
    def refresh(self) -> None:
        from . import app as A  # helpers live there; imported late to avoid an import cycle

        app = self.app
        snaps = [app.snapshots[a.email] for a in app.cfg.accounts if a.email in app.snapshots]
        if not self._auto_expanded and snaps and any(s.status == "ok" for s in snaps):
            first = next((s for s in snaps if s.recent_count), snaps[0])
            self.expanded.add(first.email)
            self._auto_expanded = True
        for box in (self.body, self.footer):
            for child in box.get_children():
                box.remove(child)

        multi = len(snaps) > 1
        badge = sum(app.badge_count(s) for s in snaps)
        period = A._period(app.cfg.settings.recent_days)
        if snaps:
            header = f"{badge:,} unread{(' ' + period) if period else ''}"
            header += f" across {len(snaps)} accounts" if multi else ""
        else:
            header = "No accounts set up yet"
        self.body.pack_start(_label(header, "gn-header"), False, False, 0)
        if not snaps:
            self.body.pack_start(self._row("Add a Gmail account…", app._launch_add_account), False, False, 0)
        self.body.pack_start(Gtk.Separator(), False, False, 0)

        notify = app.cfg.settings.notify
        latest = sorted((m for s in snaps for m in s.unread if m.category in notify),
                        key=lambda m: m.date, reverse=True)[:A.LATEST_COUNT]
        if latest:
            self.body.pack_start(_label("LATEST", "gn-label"), False, False, 0)
            self.body.get_children()[-1].set_margin_start(14)
            self.body.get_children()[-1].set_margin_top(6)
            for m in latest:
                suffix = app.label_for(m.account) if multi else ""
                self.body.pack_start(self._message_row(m, suffix), False, False, 0)
            self.body.pack_start(Gtk.Separator(), False, False, 0)

        for s in snaps:
            self.body.pack_start(self._account(s), False, False, 0)
        self.footer.pack_start(Gtk.Separator(), False, False, 0)
        self.footer.pack_start(self._row("Refresh now", app.refresh_all), False, False, 0)
        pause_row = Gtk.Button(relief=Gtk.ReliefStyle.NONE)
        pause_row.get_style_context().add_class("gn-row")
        box = Gtk.Box(spacing=10)
        box.pack_start(_label("Pause notifications", xalign=0.0), True, True, 0)
        sw = Gtk.Switch(active=app.paused, valign=Gtk.Align.CENTER)
        sw.connect("state-set", lambda _s, on: (self._set_paused(on), False)[1])
        box.pack_end(sw, False, False, 0)
        pause_row.add(box)
        pause_row.connect("clicked", lambda *_a: sw.set_active(not sw.get_active()))
        self.footer.pack_start(pause_row, False, False, 0)
        if snaps:
            self.footer.pack_start(self._row("Add another account…", app._launch_add_account), False, False, 0)
        import os
        from . import config as config_mod
        self.footer.pack_start(self._row("Open settings folder",
                                       lambda: app.open_uri("file://" + config_mod.config_dir())), False, False, 0)
        self.footer.pack_start(self._row("Quit", app.quit), False, False, 0)
        self.footer.show_all()
        self.body.show_all()

    def _set_paused(self, on: bool) -> None:
        self.app.paused = on
        self.app.rebuild_menu()

    def _row(self, text: str, cb: Callable[[], None], *classes: str, close: bool = True) -> Gtk.Button:
        b = Gtk.Button(relief=Gtk.ReliefStyle.NONE)
        b.get_style_context().add_class("gn-row")
        lab = _label(text, *classes, ellipsize=True)
        lab.set_hexpand(True)
        b.add(lab)
        b.connect("clicked", self._act(cb, close))
        return b

    def _message_row(self, m: Message, suffix: str = "", with_time: bool = False) -> Gtk.Button:
        from . import app as A
        b = Gtk.Button(relief=Gtk.ReliefStyle.NONE)
        b.get_style_context().add_class("gn-row")
        box = Gtk.Box(spacing=10)
        if with_time:
            t = _label(f"{A._ago(m.date):>4}", "gn-mono", xalign=1.0)
            t.set_width_chars(4)
            box.pack_start(t, False, False, 0)
        text = Gtk.Label(xalign=0.0)
        text.set_markup(f"<b>{GLib.markup_escape_text(m.sender)}</b> — {GLib.markup_escape_text(m.subject)}")
        text.set_ellipsize(Pango.EllipsizeMode.END)
        text.set_max_width_chars(1)
        box.pack_start(text, True, True, 0)
        if suffix:
            box.pack_end(_label(suffix, "gn-muted", "gn-small"), False, False, 0)
        b.add(box)
        b.connect("clicked", self._act(lambda: self.app.open_message(m)))
        return b

    def _account(self, s: AccountSnapshot) -> Gtk.Widget:
        from . import app as A
        open_ = s.email in self.expanded
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        if open_:
            wrap.get_style_context().add_class("gn-account-open")

        head = Gtk.Button(relief=Gtk.ReliefStyle.NONE)
        head.get_style_context().add_class("gn-row")
        box = Gtk.Box(spacing=10)
        name = Gtk.Label(xalign=0.0)
        name.set_markup(f"<b>{GLib.markup_escape_text(s.label)}</b>  "
                        f"<span foreground='#b5b5b5'>({GLib.markup_escape_text(s.email)})</span>")
        name.set_ellipsize(Pango.EllipsizeMode.END)
        name.set_max_width_chars(1)
        box.pack_start(name, True, True, 0)
        state = A._account_line(s).split("  —  ", 1)[1]
        box.pack_start(_label(state, "gn-small", "gn-warn" if s.status in ("auth_error", "error") else "gn-muted"),
                       False, False, 0)
        arrow = Gtk.Image.new_from_icon_name("pan-down-symbolic" if open_ else "pan-end-symbolic", Gtk.IconSize.MENU)
        box.pack_end(arrow, False, False, 0)
        head.add(box)

        def toggle(*_a):
            self.expanded.symmetric_difference_update({s.email})
            self.refresh()
        head.connect("clicked", toggle)
        wrap.pack_start(head, False, False, 0)

        if open_:
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            inner.set_margin_start(16)
            inner.set_margin_bottom(6)
            inner.pack_start(self._row("Open inbox in browser", lambda: self.app.open_uri(s.inbox_link()), "gn-link"),
                             False, False, 0)
            if s.status in ("auth_error", "error", "offline") and s.error:
                inner.pack_start(_label("⚠ " + s.error, "gn-warn"), False, False, 0)
                inner.get_children()[-1].set_margin_start(14)
                inner.pack_start(self._row("Retry now", lambda: self.app.workers[s.email].kick()), False, False, 0)
            listed: dict[str, list[Message]] = {c: [] for c in CATEGORIES}
            for m in s.unread:
                listed.setdefault(m.category, []).append(m)
            for cat, msgs in listed.items():
                count = s.category_counts.get(cat, len(msgs)) if s.category_counts else len(msgs)
                if not count:
                    continue
                title = CATEGORY_TITLES.get(cat, cat)
                hdr = Gtk.Box(spacing=8)
                hdr.set_margin_start(14)
                hdr.set_margin_top(8)
                dot = Gtk.Box()
                dot.get_style_context().add_class("gn-dot")
                dot.get_style_context().add_class(f"gn-dot-{cat}")
                dot.set_valign(Gtk.Align.CENTER)
                hdr.pack_start(dot, False, False, 0)
                hdr.pack_start(_label(f"{title.upper()}  ·  {count:,}", "gn-label"), False, False, 0)
                inner.pack_start(hdr, False, False, 0)
                for m in msgs:
                    inner.pack_start(self._message_row(m, with_time=True), False, False, 0)
                if count > len(msgs):
                    inner.pack_start(self._row(f"…{count - len(msgs):,} more in {title}",
                                               (lambda cat=cat: self.app.open_uri(s.category_link(cat))), "gn-link"),
                                     False, False, 0)
            if s.status == "ok" and not s.recent_count:
                inner.pack_start(_label(f"Nothing new {A._period(s.recent_days)}" if s.unread_count
                                        else "Inbox zero 🎉", "gn-muted"), False, False, 0)
                inner.get_children()[-1].set_margin_start(14)
            if s.recent_days and s.unread_count > s.recent_count:
                inner.pack_start(Gtk.Separator(), False, False, 0)
                inner.pack_start(self._row(f"All {s.unread_count:,} unread in Gmail…",
                                           lambda: self.app.open_uri(s.all_unread_link()), "gn-link"), False, False, 0)
            inner.pack_start(Gtk.Separator(), False, False, 0)
            inner.pack_start(self._row("Remove this account…", lambda: self.app.confirm_remove_account(s.email),
                                       "gn-muted"), False, False, 0)
            wrap.pack_start(inner, False, False, 0)
        return wrap
