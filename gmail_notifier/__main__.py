"""Gmail Notifier command line.

Every read-only command takes --json for scripts and AI assistants. App
passwords never appear on the command line or in any output: only
`add-account` asks for one, at a hidden prompt, and only in a real terminal.
"""

from __future__ import annotations

import argparse
import fcntl
import getpass
import json
import logging
import logging.handlers
import os
import signal
import socket
import sys
import time

from . import config as config_mod
from . import keyring_store
from .config import state_dir


# -- helpers -------------------------------------------------------------------

def _lock_path() -> str:
    base = os.environ.get("XDG_RUNTIME_DIR") or state_dir()
    return os.path.join(base, "gmail-notifier.lock")


def _log_path() -> str:
    return os.path.join(state_dir(), "gmail-notifier.log")


def _running_pid() -> int | None:
    """PID of the running tray app, if any (it holds an flock on the lock file)."""
    try:
        f = open(_lock_path())
    except OSError:
        return None
    with f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f, fcntl.LOCK_UN)
            return None  # we could take the lock, so nobody holds it
        except OSError:
            try:
                return int(f.read().strip() or 0) or None
            except ValueError:
                return None


def _password_source(acct: config_mod.Account) -> tuple[str, str]:
    """(source, password). source is 'config', 'keyring' or 'missing'."""
    if acct.app_password:
        return "config", acct.app_password
    pw = keyring_store.get_password(acct.email)
    return ("keyring", pw) if pw else ("missing", "")


def _redact(text: str, *secrets: str) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "[redacted]")
            if " " in s:
                text = text.replace(s.replace(" ", ""), "[redacted]")
    return text


def _emit(data, as_json: bool, human) -> None:
    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        human(data)


def _select_accounts(cfg: config_mod.Config, only: str | None) -> list[config_mod.Account]:
    if not only:
        return cfg.accounts
    picked = [a for a in cfg.accounts if a.email == only or a.label.lower() == only.lower()]
    if not picked:
        raise SystemExit(f"No account '{only}' in {config_mod.config_path()}")
    return picked


def _message_dict(m) -> dict:
    return {
        "account": m.account, "uid": m.uid, "category": m.category, "unread": m.unread,
        "from": m.sender, "from_email": m.sender_email, "subject": m.subject, "snippet": m.snippet,
        "date": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(m.date)), "link": m.link(),
    }


def _open_account(acct: config_mod.Account, pw: str):
    from .imap import ImapConnection
    conn = ImapConnection(acct.host, acct.port, acct.use_ssl, acct.email, pw, timeout=20)
    conn.open()
    conn.select_inbox(readonly=True)  # read-only: nothing is ever marked as read
    return conn


def _signal_running_app() -> None:
    pid = _running_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGUSR1)
            print("The running tray app picked up the change.")
        except OSError:
            pass


# -- commands --------------------------------------------------------------------

def cmd_run(args) -> int:
    os.makedirs(state_dir(), exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.handlers.RotatingFileHandler(_log_path(), maxBytes=1_000_000, backupCount=2),
                  logging.StreamHandler()])
    lock = open(_lock_path(), "a+")
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
    TrayApp(cfg).start()
    Gtk.main()
    return 0


def cmd_accounts(args) -> int:
    cfg = config_mod.load()
    data = {"config_path": config_mod.config_path(), "accounts": [
        {"email": a.email, "label": a.label, "host": a.host, "port": a.port,
         "password": _password_source(a)[0]} for a in cfg.accounts]}

    def human(d):
        if not d["accounts"]:
            print(f"No accounts yet ({d['config_path']}). A person needs to run: gmail-notifier add-account")
        for a in d["accounts"]:
            print(f"{a['label']:<14} {a['email']:<32} password: {a['password']}")
    _emit(data, args.json, human)
    return 0


def cmd_check(args) -> int:
    from .imap import ImapConnection  # noqa: F401
    cfg = config_mod.load()
    results = []
    for a in _select_accounts(cfg, args.account):
        source, pw = _password_source(a)
        r = {"email": a.email, "label": a.label, "password": source, "ok": False}
        if not pw:
            r["error"] = "no app password saved; a person must run: gmail-notifier add-account"
            results.append(r)
            continue
        t0 = time.monotonic()
        conn = None
        try:
            conn = _open_account(a, pw)
            r.update(ok=True, unread=len(conn.unseen_uids()), idle="IDLE" in conn.M.capabilities,
                     gmail_extensions=conn.gmail_ext, seconds=round(time.monotonic() - t0, 2))
        except Exception as e:  # noqa: BLE001
            r["error"] = _redact(f"{type(e).__name__}: {e}", pw)
        finally:
            if conn:
                conn.close()
        results.append(r)
    data = {"ok": bool(results) and all(r["ok"] for r in results), "accounts": results}

    def human(d):
        if not d["accounts"]:
            print("No accounts yet. A person needs to run: gmail-notifier add-account")
        for r in d["accounts"]:
            if r["ok"]:
                print(f"OK    {r['label']} <{r['email']}>  {r['unread']} unread  "
                      f"(IDLE: {r['idle']}, Gmail tabs: {r['gmail_extensions']}, {r['seconds']}s)")
            else:
                print(f"FAIL  {r['label']} <{r['email']}>  {r['error']}")
    _emit(data, args.json, human)
    return 0 if data["ok"] else 1


def cmd_unread(args) -> int:
    from .models import CATEGORY_TITLES
    cfg = config_mod.load()
    out, errors = [], []
    for a in _select_accounts(cfg, args.account):
        source, pw = _password_source(a)
        if not pw:
            errors.append({"email": a.email, "error": "no app password saved"})
            continue
        conn = None
        try:
            conn = _open_account(a, pw)
            uids = conn.unseen_uids()[-args.limit:]
            out += [_message_dict(m) for m in conn.fetch(uids)]
        except Exception as e:  # noqa: BLE001
            errors.append({"email": a.email, "error": _redact(f"{type(e).__name__}: {e}", pw)})
        finally:
            if conn:
                conn.close()
    out.sort(key=lambda m: m["date"], reverse=True)
    if args.category:
        out = [m for m in out if m["category"] == args.category]
    data = {"ok": not errors, "messages": out, "errors": errors}

    def human(d):
        for m in d["messages"]:
            print(f"{m['date'][:16].replace('T', ' ')}  [{CATEGORY_TITLES[m['category']]:<10}] "
                  f"{m['account']}\n    {m['from']}: {m['subject']}\n    {m['link']}")
        for e in d["errors"]:
            print(f"FAIL  {e['email']}: {e['error']}")
        if not d["messages"] and not d["errors"]:
            print("No unread email.")
    _emit(data, args.json, human)
    return 0 if not errors else 1


def cmd_status(args) -> int:
    from .state import StateStore
    pid = _running_pid()
    store = StateStore()
    cfg = config_mod.load()
    last_lines = []
    try:
        with open(_log_path()) as f:
            last_lines = [ln.rstrip("\n") for ln in f.readlines()[-5:]]
    except OSError:
        pass
    data = {
        "running": pid is not None, "pid": pid,
        "config_path": config_mod.config_path(), "log_path": _log_path(),
        "accounts": [{"email": a.email, "label": a.label,
                      "last_seen_uid": (store.get(a.email).last_uid if store.get(a.email) else None)}
                     for a in cfg.accounts],
        "recent_log": last_lines,
    }

    def human(d):
        print(f"Tray app: {'running (pid %s)' % d['pid'] if d['running'] else 'not running'}")
        print(f"Config:   {d['config_path']}\nLog:      {d['log_path']}")
        for a in d["accounts"]:
            print(f"  {a['label']:<14} {a['email']:<32} last seen UID: {a['last_seen_uid']}")
        if d["recent_log"]:
            print("Recent log:\n  " + "\n  ".join(d["recent_log"]))
    _emit(data, args.json, human)
    return 0


def cmd_doctor(args) -> int:
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str = "", fix: str = "") -> None:
        checks.append({"check": name, "ok": ok, "detail": detail, **({"fix": fix} if fix and not ok else {})})

    add("python", sys.version_info >= (3, 10), sys.version.split()[0], "Ubuntu 22.04 or newer is needed")
    try:
        import gi
        for ns, ver in (("Gtk", "3.0"), ("Notify", "0.7"), ("Secret", "1")):
            try:
                gi.require_version(ns, ver)
                __import__("gi.repository." + ns)
                add(f"library {ns}", True, ver)
            except (ValueError, ImportError) as e:
                add(f"library {ns}", False, str(e), "run ./install.sh")
        try:
            gi.require_version("AyatanaAppIndicator3", "0.1")
            from gi.repository import AyatanaAppIndicator3  # noqa: F401
            add("library AppIndicator", True, "AyatanaAppIndicator3")
        except (ValueError, ImportError) as e:
            add("library AppIndicator", False, str(e), "sudo apt install gir1.2-ayatanaappindicator3-0.1")
    except ImportError as e:
        add("python3-gi", False, str(e), "sudo apt install python3-gi (and use /usr/bin/python3)")

    try:
        from gi.repository import Notify
        Notify.init("Gmail Notifier")
        info = Notify.get_server_info()
        caps = Notify.get_server_caps() or []
        if info and info[0]:
            add("notification server", True, f"{info[1]} {info[3]}; caps: {', '.join(caps)}")
            add("clickable notifications", "actions" in caps, "",
                "this desktop's notification server ignores click actions")
        else:
            add("notification server", False, "none reachable", "run inside your desktop session")
    except Exception as e:  # noqa: BLE001
        add("notification server", False, str(e), "run inside your desktop session (needs D-Bus)")

    ext = "ubuntu-appindicators@ubuntu.com"
    try:
        import subprocess
        out = subprocess.run(["gnome-extensions", "info", ext], capture_output=True, text=True, timeout=5)
        on = any(w in out.stdout for w in ("State: ENABLED", "State: ACTIVE", "Enabled: Yes"))
        add("tray icon extension", on, out.stdout.strip().splitlines()[0] if out.stdout else out.stderr.strip(),
            f"gnome-extensions enable {ext}, then log out and back in")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        add("tray icon extension", True, "gnome-extensions not found (not GNOME?) – skipped")

    cfg = config_mod.load()
    add("config", bool(cfg.accounts), f"{config_mod.config_path()} – {len(cfg.accounts)} account(s)",
        "a person needs to run: gmail-notifier add-account")
    for a in cfg.accounts:
        source, _ = _password_source(a)
        add(f"password {a.email}", source != "missing", source,
            "a person needs to run: gmail-notifier add-account")

    hosts = sorted({(a.host, a.port) for a in cfg.accounts} or {("imap.gmail.com", 993)})
    for host, port in hosts:
        try:
            with socket.create_connection((host, port), timeout=5):
                add(f"network {host}:{port}", True, "reachable")
        except OSError as e:
            add(f"network {host}:{port}", False, str(e), "check internet / firewall")

    pid = _running_pid()
    add("tray app running", pid is not None, f"pid {pid}" if pid else "not running",
        "start it: gmail-notifier &  (or log out and in; it autostarts)")

    data = {"ok": all(c["ok"] for c in checks), "checks": checks}

    def human(d):
        for c in d["checks"]:
            line = f"{'ok ' if c['ok'] else 'BAD'}  {c['check']:<28} {c['detail']}"
            print(line + (f"\n     → {c['fix']}" if "fix" in c else ""))
    _emit(data, args.json, human)
    return 0 if data["ok"] else 1


def cmd_logs(args) -> int:
    try:
        with open(_log_path()) as f:
            lines = f.readlines()[-args.lines:]
    except OSError:
        print(f"No log yet at {_log_path()}")
        return 1
    sys.stdout.write("".join(lines))
    return 0


def cmd_test_notification(args) -> int:
    import gi
    gi.require_version("Notify", "0.7")
    from gi.repository import Notify
    Notify.init("Gmail Notifier")
    caps = Notify.get_server_caps() or []
    n = Notify.Notification.new("Alice Smith  ·  Personal",
                                "<b>Lunch tomorrow?</b>\nAre you free at 1pm? There's a new place…",
                                os.path.join(os.path.dirname(__file__), "icons", "gmail-notifier.svg"))
    n.show()
    print("Sent a sample notification." + ("" if "actions" in caps else
          " (This desktop's notification server doesn't support click actions.)"))
    return 0


def cmd_add_account(args) -> int:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("add-account must be run by a person in a terminal: the app password is typed at a "
              "hidden prompt and is never accepted from scripts, arguments or pipes.", file=sys.stderr)
        return 2
    from .imap import ImapConnection
    print("Add a Gmail account\n")
    print("You need an *app password* (not your normal password):")
    print("  1. Turn on 2-Step Verification:  https://myaccount.google.com/signinoptions/two-step-verification")
    print("  2. Create an app password:       https://myaccount.google.com/apppasswords")
    print("  3. IMAP must be on in Gmail → Settings → See all settings → Forwarding and POP/IMAP\n")
    try:
        addr = input("Gmail address: ").strip()
        if "@" not in addr:
            print("That doesn't look like an email address.")
            return 1
        default_label = addr.split("@")[0]
        label = input(f"Short name for the tray menu [{default_label}]: ").strip() or default_label
        pw = getpass.getpass("App password (16 letters, typing is hidden): ").replace(" ", "")
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled – nothing was saved.")
        return 1

    print("Checking the login…", end=" ", flush=True)
    conn = ImapConnection("imap.gmail.com", 993, True, addr, pw)
    try:
        conn.open()
        conn.select_inbox()
        print(f"OK – {len(conn.unseen_uids())} unread in the inbox.")
    except Exception as e:  # noqa: BLE001
        print(f"FAILED\n  {_redact(str(e), pw)}")
        print("  Double-check the app password and that IMAP is enabled. Nothing was saved.")
        return 1
    finally:
        conn.close()

    try:
        keyring_store.set_password(addr, pw)
        config_mod.add_account(addr, label)
        print("Saved (the password is in your GNOME keyring).")
    except Exception as e:  # noqa: BLE001
        print(f"Couldn't use the keyring ({e}).")
        try:
            ok = input("Store the app password in the config file instead (readable only by you)? [y/N] ")
        except (EOFError, KeyboardInterrupt):
            ok = ""
        if ok.lower() != "y":
            return 1
        config_mod.add_account(addr, label, app_password=pw)
        print(f"Saved to {config_mod.config_path()}")
    _signal_running_app()
    return 0


def cmd_remove_account(args) -> int:
    cfg = config_mod.load()
    acct = next((a for a in cfg.accounts if a.email == args.email or a.label.lower() == args.email.lower()), None)
    if acct is None:
        print(f"No account '{args.email}'. Known: {', '.join(a.email for a in cfg.accounts) or 'none'}")
        return 1
    if not args.yes:
        if not sys.stdin.isatty():
            print("Refusing without confirmation: pass --yes to remove non-interactively.", file=sys.stderr)
            return 2
        try:
            if input(f"Remove {acct.label} <{acct.email}>? Its saved password is deleted too. [y/N] ").lower() != "y":
                print("Kept.")
                return 1
        except (EOFError, KeyboardInterrupt):
            print("\nKept.")
            return 1
    config_mod.remove_account(acct.email)
    keyring_store.delete_password(acct.email)
    print(f"Removed {acct.email}.")
    _signal_running_app()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gmail-notifier", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging (tray app)")
    sub = p.add_subparsers(dest="cmd", metavar="COMMAND")

    def add(name, fn, help_, json_flag=False):
        sp = sub.add_parser(name, help=help_, description=help_)
        sp.set_defaults(fn=fn)
        if json_flag:
            sp.add_argument("--json", action="store_true", help="machine-readable output")
        return sp

    add("run", cmd_run, "run the tray app (the default; autostart does this)")
    add("doctor", cmd_doctor, "check libraries, desktop, keyring, config, network", True)
    add("accounts", cmd_accounts, "list configured accounts (never shows passwords)", True)
    sp = add("check", cmd_check, "log in to each account and report unread counts", True)
    sp.add_argument("--account", help="email address or label")
    sp = add("unread", cmd_unread, "list unread emails with links (read-only; marks nothing read)", True)
    sp.add_argument("--account", help="email address or label")
    sp.add_argument("--limit", type=int, default=10, help="per account (default 10)")
    sp.add_argument("--category", choices=["primary", "updates", "social", "promotions"])
    add("status", cmd_status, "is the tray app running? what has it seen?", True)
    sp = add("logs", cmd_logs, "print the end of the log")
    sp.add_argument("-n", "--lines", type=int, default=50)
    add("test-notification", cmd_test_notification, "show a sample popup")
    add("add-account", cmd_add_account, "add/update an account – interactive, a person types the app password")
    sp = add("remove-account", cmd_remove_account, "remove an account and its saved password")
    sp.add_argument("email", help="email address or label")
    sp.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not getattr(args, "fn", None):
        args.fn = cmd_run
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
