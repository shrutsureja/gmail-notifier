"""Remembers, per account, the highest UID we've already handled.

This is what makes "emails that arrived while the laptop was off" work: on
startup we ask the server for everything with a UID above the stored one.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass

from .config import state_dir


@dataclass
class AccountState:
    uidvalidity: int
    last_uid: int


class StateStore:
    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(state_dir(), "state.json")
        self._lock = threading.Lock()
        self._data: dict[str, AccountState] = {}
        try:
            with open(self.path) as f:
                raw = json.load(f)
            self._data = {k: AccountState(**v) for k, v in raw.items()}
        except (OSError, ValueError, TypeError):
            pass

    def get(self, account: str) -> AccountState | None:
        with self._lock:
            return self._data.get(account)

    def set(self, account: str, st: AccountState) -> None:
        with self._lock:
            self._data[account] = st
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump({k: asdict(v) for k, v in self._data.items()}, f, indent=2)
            os.replace(tmp, self.path)  # atomic: a crash never leaves half a file
