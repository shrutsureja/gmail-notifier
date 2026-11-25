"""~/.config/gmail-notifier/config.ini

    [settings]
    notify = primary, updates, social, promotions

    [account you@gmail.com]
    label = Personal

    [account work@company.com]
    label = Work
    ; password normally lives in the GNOME keyring (`gmail-notifier add-account`).
    ; app_password = abcd efgh ijkl mnop   <- fallback, plain text, less safe
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field

from .models import CATEGORIES


def config_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "gmail-notifier")


def state_dir() -> str:
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "gmail-notifier")


def config_path() -> str:
    return os.path.join(config_dir(), "config.ini")


@dataclass
class Account:
    email: str
    label: str
    host: str = "imap.gmail.com"
    port: int = 993
    use_ssl: bool = True
    app_password: str = ""  # only if not stored in the keyring


@dataclass
class Settings:
    notify: list[str] = field(default_factory=lambda: list(CATEGORIES))
    max_items_per_account: int = 10
    idle_timeout_minutes: float = 10.0


@dataclass
class Config:
    accounts: list[Account]
    settings: Settings


def load(path: str | None = None) -> Config:
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(path or config_path())
    settings = Settings()
    if cp.has_section("settings"):
        s = cp["settings"]
        if "notify" in s:
            settings.notify = [c.strip().lower() for c in s["notify"].split(",") if c.strip()]
        settings.max_items_per_account = s.getint("max_items_per_account", settings.max_items_per_account)
        settings.idle_timeout_minutes = s.getfloat("idle_timeout_minutes", settings.idle_timeout_minutes)
    accounts = []
    for name in cp.sections():
        if not name.lower().startswith("account "):
            continue
        sec = cp[name]
        addr = name.split(" ", 1)[1].strip()
        accounts.append(Account(
            email=addr,
            label=sec.get("label", addr.split("@")[0]),
            host=sec.get("host", "imap.gmail.com"),
            port=sec.getint("port", 993),
            use_ssl=sec.getboolean("ssl", True),
            app_password=sec.get("app_password", ""),
        ))
    return Config(accounts=accounts, settings=settings)


def add_account(addr: str, label: str, app_password: str = "", path: str | None = None) -> None:
    path = path or config_path()
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(path)
    if not cp.has_section("settings"):
        cp["settings"] = {"notify": ", ".join(CATEGORIES)}
    sec = f"account {addr}"
    if not cp.has_section(sec):
        cp.add_section(sec)
    cp[sec]["label"] = label
    if app_password:
        cp[sec]["app_password"] = app_password
    elif "app_password" in cp[sec]:
        del cp[sec]["app_password"]
    _write(cp, path)


def remove_account(addr: str, path: str | None = None) -> bool:
    path = path or config_path()
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(path)
    removed = cp.remove_section(f"account {addr}")
    if removed:
        _write(cp, path)
    return removed


def _write(cp: configparser.ConfigParser, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        cp.write(f)
