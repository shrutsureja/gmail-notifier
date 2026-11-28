"""Plain data types shared between the IMAP engine and the tray UI."""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass, field

# Gmail's four default inbox tabs. "forums" is folded into "updates".
CATEGORIES = ("primary", "updates", "social", "promotions")
CATEGORY_TITLES = {
    "primary": "Primary",
    "updates": "Updates",
    "social": "Social",
    "promotions": "Promotions",
}


@dataclass
class Message:
    account: str
    uid: int
    sender: str
    sender_email: str
    subject: str
    snippet: str
    date: float  # unix timestamp (server INTERNALDATE)
    unread: bool
    category: str = "primary"
    gm_msgid: int | None = None  # Gmail X-GM-MSGID
    message_id: str = ""  # RFC 822 Message-ID header

    def link(self) -> str:
        """URL that opens this exact email in Gmail, in the right account."""
        base = gmail_base(self.account)
        if self.gm_msgid:
            return f"{base}#all/{self.gm_msgid:x}"
        if self.message_id:
            query = urllib.parse.quote(f"rfc822msgid:{self.message_id.strip('<>')}")
            return f"{base}#search/{query}"
        return f"{base}#inbox"


def gmail_base(account: str) -> str:
    # /mail/u/<address>/ routes to the right account when several are signed in.
    return f"https://mail.google.com/mail/u/{urllib.parse.quote(account)}/"


@dataclass
class AccountSnapshot:
    """What the UI needs to know about one account after a sync."""

    email: str
    label: str
    status: str = "connecting"  # connecting | ok | offline | auth_error | error
    error: str = ""
    unread_count: int = 0  # every unread email in the inbox, however old
    recent_count: int = 0  # unread that arrived in the last `recent_days` days
    recent_days: int = 0  # 0 = no window: recent_count == unread_count
    category_counts: dict[str, int] = field(default_factory=dict)  # recent unread per tab
    unread: list[Message] = field(default_factory=list)  # newest few per tab, newest first

    def inbox_link(self) -> str:
        return gmail_base(self.email) + "#inbox"

    def category_link(self, category: str) -> str:
        if category == "primary":
            return self.inbox_link()
        return gmail_base(self.email) + f"#category/{category}"

    def all_unread_link(self) -> str:
        return gmail_base(self.email) + "#search/in%3Ainbox+is%3Aunread"
