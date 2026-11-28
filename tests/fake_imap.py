"""A tiny in-process IMAP server that behaves enough like Gmail for tests:
LOGIN, CAPABILITY, SELECT/EXAMINE, UID SEARCH (ALL, UNSEEN, UID set, X-GM-RAW
category queries), UID FETCH (incl. partial BODY.PEEK[] and X-GM-MSGID),
UID STORE, IDLE/DONE with live EXISTS pushes, NOOP, LOGOUT."""

from __future__ import annotations

import re
import shlex
import socket
import socketserver
import threading
import time
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import format_datetime, localtime


@dataclass
class FakeMsg:
    uid: int
    raw: bytes
    category: str = "primary"
    flags: set = field(default_factory=set)
    gm_msgid: int = 0
    date: float = field(default_factory=time.time)


def make_email(sender: str, subject: str, body: str, html: bool = False) -> bytes:
    m = EmailMessage()
    m["From"] = sender
    m["To"] = "me@example.com"
    m["Subject"] = subject
    m["Message-ID"] = f"<{abs(hash((sender, subject, time.time())))}@test>"
    m["Date"] = format_datetime(localtime())
    if html:
        m.set_content("plain fallback")
        m.add_alternative(f"<html><body><p>{body}</p></body></html>", subtype="html")
        # make HTML the only part to test HTML snippet extraction
        m = EmailMessage()
        m["From"] = sender
        m["Subject"] = subject
        m.set_content(f"<html><body><style>p{{}}</style><p>{body}</p></body></html>", subtype="html")
    else:
        m.set_content(body)
    return m.as_bytes()


class Mailbox:
    def __init__(self, user: str, password: str):
        self.user, self.password = user, password
        self.uidvalidity = 1000
        self.next_uid = 1
        self.msgs: list[FakeMsg] = []
        self.lock = threading.RLock()
        self.sessions: set = set()
        self.logins = 0

    def deliver(self, sender: str, subject: str, body: str = "Hello there",
                category: str = "primary", seen: bool = False, html: bool = False,
                age_days: float = 0) -> FakeMsg:
        with self.lock:
            m = FakeMsg(uid=self.next_uid, raw=make_email(sender, subject, body, html),
                        category=category, gm_msgid=0x1800000000 + self.next_uid,
                        date=time.time() - age_days * 86400)
            if seen:
                m.flags.add("\\Seen")
            self.next_uid += 1
            self.msgs.append(m)
            n = len(self.msgs)
        self._push(f"* {n} EXISTS")
        return m

    def set_seen(self, uid: int) -> None:
        with self.lock:
            for i, m in enumerate(self.msgs, 1):
                if m.uid == uid:
                    m.flags.add("\\Seen")
                    seq = i
        self._push(f"* {seq} FETCH (UID {uid} FLAGS (\\Seen))")

    def reset_uidvalidity(self) -> None:
        with self.lock:
            self.uidvalidity += 1

    def _push(self, line: str) -> None:
        for s in list(self.sessions):
            s.push(line)

    def drop_all_connections(self) -> None:
        for s in list(self.sessions):
            try:
                s.request.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


class _Handler(socketserver.StreamRequestHandler):
    mailbox: Mailbox

    def setup(self):
        super().setup()
        self.wlock = threading.Lock()
        self.idling = False
        self.authed = False
        self.pending: list[str] = []

    def push(self, line: str) -> None:
        # Like real servers: live while idling, otherwise queued and sent with
        # the reply to the next command.
        if self.idling:
            self.send(line)
        else:
            self.pending.append(line)

    def flush_pending(self) -> None:
        pending, self.pending = self.pending, []
        for line in pending:
            self.send(line)

    def send(self, line: str | bytes) -> None:
        data = line if isinstance(line, bytes) else line.encode()
        with self.wlock:
            try:
                self.wfile.write(data + b"\r\n")
                self.wfile.flush()
            except (OSError, ValueError):  # client already disconnected
                pass

    def handle(self):
        try:
            self._handle()
        except OSError:
            pass  # client went away / test dropped the connection

    def _handle(self):
        mb = self.mailbox
        mb.sessions.add(self)
        try:
            self.send("* OK FakeGmail ready")
            while True:
                line = self.rfile.readline()
                if not line:
                    return
                line = line.decode().rstrip("\r\n")
                tag, _, rest = line.partition(" ")
                cmd, _, args = rest.partition(" ")
                cmd = cmd.upper()
                if cmd == "UID":
                    sub, _, args = args.partition(" ")
                    cmd = "UID " + sub.upper()
                if self.authed and cmd not in ("LOGOUT",):
                    self.flush_pending()
                fn = getattr(self, "cmd_" + cmd.replace(" ", "_"), None)
                if fn is None:
                    self.send(f"{tag} BAD unknown command {cmd}")
                    continue
                if fn(tag, args) == "logout":
                    return
        finally:
            mb.sessions.discard(self)

    # -- commands -----------------------------------------------------------
    def cmd_CAPABILITY(self, tag, args):
        self.send("* CAPABILITY IMAP4rev1 IDLE X-GM-EXT-1 UIDPLUS")
        self.send(f"{tag} OK done")

    def cmd_LOGIN(self, tag, args):
        user, password = shlex.split(args)
        if user == self.mailbox.user and password == self.mailbox.password:
            self.authed = True
            self.mailbox.logins += 1
            self.send(f"{tag} OK logged in")
        else:
            self.send(f"{tag} NO [AUTHENTICATIONFAILED] Invalid credentials (Failure)")

    def cmd_SELECT(self, tag, args, readonly=False):
        mb = self.mailbox
        with mb.lock:
            self.send(f"* {len(mb.msgs)} EXISTS")
            self.send("* 0 RECENT")
            self.send(f"* OK [UIDVALIDITY {mb.uidvalidity}] UIDs valid")
            self.send(f"* OK [UIDNEXT {mb.next_uid}] Predicted next UID")
        self.send(f"{tag} OK [{'READ-ONLY' if readonly else 'READ-WRITE'}] selected")

    def cmd_EXAMINE(self, tag, args):
        self.cmd_SELECT(tag, args, readonly=True)

    def cmd_NOOP(self, tag, args):
        self.send(f"{tag} OK noop")

    def cmd_LOGOUT(self, tag, args):
        self.send("* BYE bye")
        self.send(f"{tag} OK bye")
        return "logout"

    def cmd_CLOSE(self, tag, args):
        self.send(f"{tag} OK closed")

    def cmd_IDLE(self, tag, args):
        self.idling = True
        self.send("+ idling")
        self.flush_pending()
        line = self.rfile.readline()
        self.idling = False
        if line.strip().upper() == b"DONE":
            self.send(f"{tag} OK IDLE terminated")
        return None if line else "logout"

    def _match_set(self, spec: str) -> list[FakeMsg]:
        mb = self.mailbox
        maxuid = max((m.uid for m in mb.msgs), default=0)
        out = []
        for m in mb.msgs:
            for part in spec.split(","):
                if ":" in part:
                    a, b = part.split(":")
                    a = maxuid if a == "*" else int(a)
                    b = maxuid if b == "*" else int(b)
                    lo, hi = min(a, b), max(a, b)  # RFC: "n:*" with n>max matches max
                    if lo <= m.uid <= hi:
                        out.append(m)
                        break
                elif int(part) == m.uid:
                    out.append(m)
                    break
        return out

    def cmd_UID_SEARCH(self, tag, args):
        mb = self.mailbox
        toks = shlex.split(args)
        with mb.lock:
            result = list(mb.msgs)
            i = 0
            while i < len(toks):
                t = toks[i].upper()
                if t == "ALL":
                    pass
                elif t == "UNSEEN":
                    result = [m for m in result if "\\Seen" not in m.flags]
                elif t == "UID":
                    allowed = {m.uid for m in self._match_set(toks[i + 1])}
                    result = [m for m in result if m.uid in allowed]
                    i += 1
                elif t == "SINCE":
                    since = time.mktime(time.strptime(toks[i + 1], "%d-%b-%Y"))
                    result = [m for m in result if m.date >= since]
                    i += 1
                elif t == "X-GM-RAW":
                    q = toks[i + 1]
                    cats = set(re.findall(r"category:(\w+)", q))
                    if "forums" in cats:
                        cats.add("updates")
                    result = [m for m in result if m.category in cats]
                    i += 1
                i += 1
            uids = " ".join(str(m.uid) for m in result)
        self.send(f"* SEARCH {uids}".rstrip())
        self.send(f"{tag} OK search done")

    def cmd_UID_FETCH(self, tag, args):
        mb = self.mailbox
        spec, _, items = args.partition(" ")
        partial = re.search(r"BODY\.PEEK\[\]<0\.(\d+)>", items)
        with mb.lock:
            for seq, m in enumerate(mb.msgs, 1):
                if m not in self._match_set(spec):
                    continue
                flags = " ".join(sorted(m.flags))
                idate = time.strftime("%d-%b-%Y %H:%M:%S +0000", time.gmtime(m.date))
                head = f'* {seq} FETCH (UID {m.uid} INTERNALDATE "{idate}" X-GM-MSGID {m.gm_msgid}'
                if partial:
                    body = m.raw[: int(partial.group(1))]
                    self.send(f"{head} BODY[]<0> {{{len(body)}}}".encode())
                    with self.wlock:
                        self.wfile.write(body)
                    # Gmail sends FLAGS *after* the literal; mimic that.
                    self.send(f" FLAGS ({flags}))")
                else:
                    self.send(f"{head} FLAGS ({flags}))")
        self.send(f"{tag} OK fetch done")

    def cmd_UID_STORE(self, tag, args):
        mb = self.mailbox
        spec, _, rest = args.partition(" ")
        with mb.lock:
            targets = self._match_set(spec)
            for m in targets:
                if "+FLAGS" in rest.upper() and "\\SEEN" in rest.upper():
                    m.flags.add("\\Seen")
        for m in targets:
            self.mailbox._push(f"* 1 FETCH (UID {m.uid} FLAGS (\\Seen))")
        self.send(f"{tag} OK store done")


class FakeImapServer:
    def __init__(self, user="me@example.com", password="secret-pass"):
        self.mailbox = Mailbox(user, password)
        handler = type("H", (_Handler,), {"mailbox": self.mailbox})
        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.mailbox.drop_all_connections()
        self.server.shutdown()
        self.server.server_close()
