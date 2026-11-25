"""gmail-notifier                 run the tray app (what autostart does)
gmail-notifier add-account     add / update a Gmail account (asks for an app password)
gmail-notifier remove-account EMAIL
gmail-notifier check           test every account from the terminal and print unread mail
gmail-notifier test-notification   show a sample notification (checks your desktop setup)
"""

from __future__ import annotations

import fcntl
import getpass
import logging
import logging.handlers
import os
import signal
import sys

from . import config as config_mod
from . import keyring_store
from .config import state_dir


def _runtime_lock_path() -> str:
    base = os.environ.get("XDG_RUNTIME_DIR") or state_dir()
    return os.path.join(base, "gmail-notifier.lock")


def _setup_logging(verbose: bool) -> None:
    os.makedirs(state_dir(), exist_ok=True)
    handlers: list[logging.Handler] = [
        logging.handlers.RotatingFileHandler(os.path.join(state_dir(), "gmail-notifier.log"),
                                             maxBytes=1_000_000, backupCount=2),
        logging.StreamHandler(),
    ]
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _password_for(acct: config_mod.Account) -> str:
    return acct.app_password or keyring_store.get_password(acct.email)


def cmd_run(verbose: bool) -> int:
    _setup_logging(verbose)
    lock = open(_runtime_lock_path(), "a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("gmail-notifier is already running (look for the envelope in the top bar).")
        return 0
    lock.seek(0)
    lock.truncate()
    lock.write(str(os.getpid()))
    lock.flush()

    from .app import TrayApp  # imported after the lock: fast "already running" exit
    from gi.repository import Gtk

    cfg = config_mod.load()
    logging.getLogger(__name__).info("starting with %d account(s)", len(cfg.accounts))
    app = TrayApp(cfg)
    app.start()
    Gtk.main()
    return 0


def _signal_running_app() -> None:
    try:
        with open(_runtime_lock_path()) as f:
            pid = int(f.read().strip() or 0)
        if pid:
            os.kill(pid, signal.SIGUSR1)
            print("The running tray app picked up the change.")
    except (OSError, ValueError):
        pass


def cmd_add_account() -> int:
    from .imap import ImapConnection

    print("Add a Gmail account\n")
    print("You need an *app password* (not your normal password):")
    print("  1. Turn on 2-Step Verification:  https://myaccount.google.com/signinoptions/two-step-verification")
    print("  2. Create an app password:       https://myaccount.google.com/apppasswords")
    print("  3. IMAP must be on in Gmail → Settings → See all settings → Forwarding and POP/IMAP\n")
    addr = input("Gmail address: ").strip()
    if "@" not in addr:
        print("That doesn't look like an email address.")
        return 1
    label = input(f"Short name for the tray menu [{addr.split('@')[0]}]: ").strip() or addr.split("@")[0]
    pw = getpass.getpass("App password (16 letters, typing is hidden): ").replace(" ", "")

    print("Checking the login…", end=" ", flush=True)
    conn = ImapConnection("imap.gmail.com", 993, True, addr, pw)
    try:
        conn.open()
        conn.select_inbox()
        unread = len(conn.unseen_uids())
        print(f"OK – {unread} unread in the inbox.")
    except Exception as e:  # noqa: BLE001
        print(f"FAILED\n  {e}")
        print("  Double-check the app password and that IMAP is enabled. Nothing was saved.")
        return 1
    finally:
        conn.close()

    try:
        keyring_store.set_password(addr, pw)
        config_mod.add_account(addr, label)
        print("Saved (password is in your GNOME keyring).")
    except Exception as e:  # noqa: BLE001
        print(f"Couldn't use the keyring ({e}).")
        if input("Store the app password in the config file instead (readable only by you)? [y/N] ").lower() != "y":
            return 1
        config_mod.add_account(addr, label, app_password=pw)
        print(f"Saved to {config_mod.config_path()}")
    _signal_running_app()
    return 0


def cmd_remove_account(addr: str) -> int:
    removed = config_mod.remove_account(addr)
    keyring_store.delete_password(addr)
    print("Removed." if removed else "No such account in the config.")
    _signal_running_app()
    return 0 if removed else 1


def cmd_check() -> int:
    from .imap import ImapConnection
    from .models import CATEGORY_TITLES

    cfg = config_mod.load()
    if not cfg.accounts:
        print(f"No accounts in {config_mod.config_path()} – run: gmail-notifier add-account")
        return 1
    ok = True
    for a in cfg.accounts:
        print(f"\n== {a.label} <{a.email}>")
        pw = _password_for(a)
        if not pw:
            print("   no app password saved – run: gmail-notifier add-account")
            ok = False
            continue
        conn = ImapConnection(a.host, a.port, a.use_ssl, a.email, pw)
        try:
            conn.open()
            conn.select_inbox()
            unseen = conn.unseen_uids()
            print(f"   login OK · {len(unseen)} unread · IDLE={'IDLE' in conn.M.capabilities} "
                  f"· gmail-ext={conn.gmail_ext}")
            for m in sorted(conn.fetch(unseen[-5:]), key=lambda m: m.date, reverse=True):
                print(f"   [{CATEGORY_TITLES.get(m.category, m.category):<10}] {m.sender}: {m.subject}")
                print(f"      {m.link()}")
        except Exception as e:  # noqa: BLE001
            print(f"   FAILED: {e}")
            ok = False
        finally:
            conn.close()
    return 0 if ok else 1


def cmd_test_notification() -> int:
    import gi
    gi.require_version("Notify", "0.7")
    from gi.repository import Notify
    Notify.init("Gmail Notifier")
    caps = Notify.get_server_caps() or []
    info = Notify.get_server_info()
    print(f"Notification server: {info[1:3] if info and info[0] else 'unknown'} · capabilities: {', '.join(caps)}")
    n = Notify.Notification.new("Alice Smith  ·  Personal",
                                "<b>Lunch tomorrow?</b>\nAre you free at 1pm? There's a new place…",
                                os.path.join(os.path.dirname(__file__), "icons", "gmail-notifier.svg"))
    n.show()
    print("Sent – you should see a popup now.")
    if "actions" not in caps:
        print("Note: this desktop's notification server doesn't support click actions.")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    verbose = "-v" in argv or "--verbose" in argv
    argv = [a for a in argv if a not in ("-v", "--verbose")]
    cmd = argv[0] if argv else "run"
    if cmd == "run":
        return cmd_run(verbose)
    if cmd == "add-account":
        try:
            return cmd_add_account()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled – nothing was saved.")
            return 1
    if cmd == "remove-account" and len(argv) == 2:
        return cmd_remove_account(argv[1])
    if cmd == "check":
        return cmd_check()
    if cmd == "test-notification":
        return cmd_test_notification()
    print(__doc__)
    return 0 if cmd in ("-h", "--help", "help") else 2


if __name__ == "__main__":
    sys.exit(main())
