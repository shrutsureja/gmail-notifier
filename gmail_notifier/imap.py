"""Thin, testable wrapper around imaplib for the handful of commands we need.

Python's imaplib (before 3.14) has no IDLE support, so IDLE is implemented
here by hand. While idling we only *read* on the socket; to wake a worker
early (shutdown, laptop resume, "Refresh now") another thread calls
interrupt(), which shuts the socket down and makes the blocked read return.
"""

from __future__ import annotations

import email
import email.policy
import email.utils
import html
import imaplib
import re
import socket
import ssl
import time

from .models import Message

# X-GM-RAW queries for Gmail's tabs. Anything matching none of them is Primary.
CATEGORY_QUERIES = {
    "social": "category:social",
    "promotions": "category:promotions",
    "updates": "{category:updates category:forums}",
}

BODY_PEEK_BYTES = 32768  # enough for headers + the start of the text
FETCH_BATCH = 25


class IdleTimeout(Exception):
    """IDLE ran for its full timeout with no mailbox changes."""


class ImapConnection:
    def __init__(self, host: str, port: int, use_ssl: bool, user: str, password: str,
                 timeout: float = 60.0):
        self.host, self.port, self.use_ssl = host, port, use_ssl
        self.user = user
        # Google displays app passwords as "abcd efgh ijkl mnop"; the spaces aren't part of it.
        self.password = password.replace(" ", "") if host.endswith("gmail.com") else password
        self.timeout = timeout
        self.M: imaplib.IMAP4 | None = None
        self.gmail_ext = False

    # -- connection ---------------------------------------------------------
    def open(self) -> None:
        if self.use_ssl:
            self.M = imaplib.IMAP4_SSL(self.host, self.port, timeout=self.timeout,
                                       ssl_context=ssl.create_default_context())
        else:
            self.M = imaplib.IMAP4(self.host, self.port, timeout=self.timeout)
        _enable_keepalive(self.M.sock)
        self.M.login(self.user, self.password)
        self.gmail_ext = "X-GM-EXT-1" in self.M.capabilities

    def close(self) -> None:
        M, self.M = self.M, None
        if M is None:
            return
        try:
            M.logout()
        except Exception:
            try:
                M.shutdown()
            except Exception:
                pass

    def interrupt(self) -> None:
        """Called from another thread: abort whatever the connection is blocked on."""
        M = self.M
        if M is not None:
            try:
                M.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    # -- mailbox ------------------------------------------------------------
    def select_inbox(self, readonly: bool = True) -> tuple[int, int | None]:
        """Returns (UIDVALIDITY, UIDNEXT or None)."""
        typ, data = self.M.select("INBOX", readonly=readonly)
        if typ != "OK":
            raise imaplib.IMAP4.error(f"SELECT INBOX failed: {data}")
        uidvalidity = int(self.M.response("UIDVALIDITY")[1][0])
        uidnext_raw = self.M.response("UIDNEXT")[1]
        uidnext = int(uidnext_raw[0]) if uidnext_raw and uidnext_raw[0] else None
        # imaplib keeps SELECT's own "* N EXISTS" around. Drop it, so idle() only
        # sees changes reported *after* this point (otherwise it re-syncs forever).
        self.M.untagged_responses.clear()
        return uidvalidity, uidnext

    def search(self, *criteria: str) -> list[int]:
        typ, data = self.M.uid("SEARCH", *criteria)
        if typ != "OK":
            raise imaplib.IMAP4.error(f"SEARCH failed: {data}")
        return [int(x) for x in b" ".join(d for d in data if d).split()]

    def max_uid(self) -> int:
        uids = self.search("ALL")
        return max(uids) if uids else 0

    def uids_after(self, last_uid: int) -> list[int]:
        # "n:*" matches the highest UID even when it is < n, so filter afterwards.
        return sorted(u for u in self.search("UID", f"{last_uid + 1}:*") if u > last_uid)

    def unseen_uids(self) -> list[int]:
        return sorted(self.search("UNSEEN"))

    def category_uids(self, *criteria: str) -> dict[str, set[int]]:
        """UIDs per non-primary Gmail tab among messages matching `criteria`,
        searched on the server (works for tens of thousands of messages)."""
        if not self.gmail_ext:
            return {}
        return {name: set(self.search("X-GM-RAW", _quote(query), *criteria))
                for name, query in CATEGORY_QUERIES.items()}

    def categorize(self, uids: list[int]) -> dict[int, str]:
        cats = {u: "primary" for u in uids}
        if not uids or not self.gmail_ext:
            return cats
        uidset = _uidset(uids)
        for name, query in CATEGORY_QUERIES.items():
            for u in self.search("X-GM-RAW", _quote(query), "UID", uidset):
                if u in cats and cats[u] == "primary":
                    cats[u] = name
        return cats

    def fetch(self, uids: list[int], categorize: bool = True) -> list[Message]:
        out: list[Message] = []
        items = "UID FLAGS INTERNALDATE"
        if self.gmail_ext:
            items += " X-GM-MSGID"
        items += f" BODY.PEEK[]<0.{BODY_PEEK_BYTES}>"
        for i in range(0, len(uids), FETCH_BATCH):
            chunk = uids[i:i + FETCH_BATCH]
            typ, data = self.M.uid("FETCH", _uidset(chunk), f"({items})")
            if typ != "OK":
                raise imaplib.IMAP4.error(f"FETCH failed: {data}")
            for meta, body in _group_fetch(data):
                msg = _parse_message(self.user, meta, body)
                if msg is not None:
                    out.append(msg)
        if not categorize:
            return out
        cats = self.categorize([m.uid for m in out])
        for m in out:
            m.category = cats.get(m.uid, "primary")
        return out

    def mark_seen(self, uids: list[int]) -> None:
        if uids:
            self.M.uid("STORE", _uidset(uids), "+FLAGS", r"(\Seen)")

    # -- IDLE ---------------------------------------------------------------
    def idle(self, timeout: float) -> None:
        """Block until the INBOX changes. Raises IdleTimeout if nothing happened.

        After IdleTimeout the connection must be discarded (the socket's
        buffered reader is unusable after a timeout).
        """
        M = self.M
        if "IDLE" not in M.capabilities:
            # Server without IDLE: poll instead.
            time.sleep(min(timeout, 30))
            M.noop()
            return
        # A change may have been reported while we were busy syncing (servers
        # attach it to the next command's reply). If so, re-sync right away
        # instead of idling past it.
        changed = any(k in M.untagged_responses for k in ("EXISTS", "EXPUNGE", "FETCH"))
        M.untagged_responses.clear()
        if changed:
            return
        tag = M._new_tag()
        M.send(tag + b" IDLE\r\n")
        M.sock.settimeout(timeout)
        change = re.compile(rb"\* \d+ (EXISTS|EXPUNGE|FETCH)")
        try:
            # The server may report a change *before* its "+ idling" reply.
            changed = False
            while True:
                line = M.readline()
                if not line or line.startswith(b"* BYE"):
                    raise ConnectionError("server closed the connection")
                if line.startswith(b"+"):
                    break
                if line.startswith(tag):
                    raise imaplib.IMAP4.error(f"IDLE rejected: {line!r}")
                changed = changed or bool(change.match(line))
            while not changed:
                line = M.readline()
                if not line or line.startswith(b"* BYE"):
                    raise ConnectionError("server closed the connection")
                changed = bool(change.match(line))
        except (socket.timeout, TimeoutError) as e:
            raise IdleTimeout() from e
        M.sock.settimeout(self.timeout)
        M.send(b"DONE\r\n")
        while True:
            line = M.readline()
            if not line:
                raise ConnectionError("server closed the connection")
            if line.startswith(tag):
                break


# -- helpers ----------------------------------------------------------------

def _enable_keepalive(sock: socket.socket) -> None:
    """Notice dead connections (e.g. after Wi-Fi drops) within ~2 minutes."""
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        for opt, val in (("TCP_KEEPIDLE", 60), ("TCP_KEEPINTVL", 20), ("TCP_KEEPCNT", 3)):
            if hasattr(socket, opt):
                sock.setsockopt(socket.IPPROTO_TCP, getattr(socket, opt), val)
    except OSError:
        pass


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def imap_date(ts: float) -> str:
    """IMAP date for SEARCH SINCE (month names must be English, whatever the locale)."""
    t = time.localtime(ts)
    return f"{t.tm_mday}-{_MONTHS[t.tm_mon - 1]}-{t.tm_year}"


def _quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _uidset(uids: list[int]) -> str:
    return ",".join(str(u) for u in sorted(set(uids)))


def _group_fetch(data: list) -> list[tuple[bytes, bytes]]:
    """imaplib returns FETCH responses as a flat list mixing (meta, literal)
    tuples and trailing byte strings (Gmail puts FLAGS after the body)."""
    groups: list[list] = []
    for item in data:
        if isinstance(item, tuple):
            groups.append([item[0], item[1]])
        elif isinstance(item, bytes):
            if re.match(rb"\d+ \(", item):
                groups.append([item, b""])
            elif groups:
                groups[-1][0] += b" " + item
    return [(g[0], g[1]) for g in groups]


def _parse_message(account: str, meta: bytes, body: bytes) -> Message | None:
    m = re.search(rb"UID (\d+)", meta)
    if not m:
        return None
    uid = int(m.group(1))
    flags = re.search(rb"FLAGS \(([^)]*)\)", meta)
    unread = b"\\Seen" not in (flags.group(1) if flags else b"")
    gm = re.search(rb"X-GM-MSGID (\d+)", meta)
    date = time.time()
    idate = re.search(rb'INTERNALDATE "[^"]+"', meta)
    if idate:
        tt = imaplib.Internaldate2tuple(idate.group(0))
        if tt:
            date = time.mktime(tt)

    msg = email.message_from_bytes(body or b"", policy=email.policy.default)
    subject = _header(msg, "Subject") or "(no subject)"
    sender_name, sender_email = email.utils.parseaddr(_header(msg, "From"))
    return Message(
        account=account,
        uid=uid,
        sender=sender_name or sender_email or "Unknown sender",
        sender_email=sender_email,
        subject=" ".join(subject.split()),
        snippet=_snippet(msg),
        date=date,
        unread=unread,
        gm_msgid=int(gm.group(1)) if gm else None,
        message_id=_header(msg, "Message-ID"),
    )


def _header(msg, name: str) -> str:
    try:
        return str(msg.get(name, "") or "")
    except Exception:  # malformed encoded-words etc.
        raw = msg.get_all(name, failobj=[""])
        return str(raw[0]) if raw else ""


_TAG_RE = re.compile(r"<(script|style)\b.*?</\1>|<[^>]+>", re.S | re.I)


def _snippet(msg, limit: int = 180) -> str:
    """First readable text of the email. The body may be truncated (we only
    fetched the first few KB), so every step is best-effort."""
    text = ""
    try:
        for part in msg.walk():
            ctype = part.get_content_type()
            if part.is_multipart() or ctype not in ("text/plain", "text/html"):
                continue
            try:
                content = part.get_content()
            except Exception:
                payload = part.get_payload(decode=True) or b""
                content = payload.decode("utf-8", "replace")
            if ctype == "text/html":
                content = html.unescape(_TAG_RE.sub(" ", content))
            if content.strip():
                text = content
                if ctype == "text/plain":
                    break
    except Exception:
        pass
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith(">")]
    text = " ".join(" ".join(lines).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
