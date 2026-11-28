# Gmail Notifier for Ubuntu

A tray icon in the Ubuntu top bar for all your Gmail accounts:

- **Real-time popups** – a desktop notification within a second or two of an email arriving (IMAP IDLE push, no polling).
- **"While you were away"** – when you turn the laptop on (or open the lid), everything that arrived while it was off shows up as **one** summary notification, and in the tray menu.
- **Click to open** – clicking a notification opens *that exact email* in your browser, in the right Gmail account. There's also a **Mark as read** button.
- **Tray menu** – unread count next to the icon. The menu shows the latest few emails across all accounts, plus one submenu per account with unread mail grouped by Gmail's four tabs: **Primary, Updates, Social, Promotions**.
- Multiple accounts (as many as you like), passwords kept in the GNOME keyring, reconnects by itself after sleep or Wi-Fi drops.

```
 ✉ 7 ▾
┌──────────────────────────────────────────────────────┐
│ 7 unread across 3 accounts                           │
│ ──────────────────────────────────────────────────── │
│ LATEST                                               │
│ Alice Smith — Lunch tomorrow?          (Personal)    │
│ GitHub — [repo] PR #12 approved        (Work)        │
│ ──────────────────────────────────────────────────── │
│ Personal  (me@gmail.com)  —  4 unread             ▸  │──┐
│ Work  (me@company.com)  —  2 unread               ▸  │  │ Open inbox in browser
│ Side  (side@gmail.com)  —  1 unread               ▸  │  │ PRIMARY · 2
│ ──────────────────────────────────────────────────── │  │  12m Alice Smith — Lunch tomorrow?
│ Refresh now                                          │  │   2h Mom — Photos from Sunday
│ ☐ Pause notifications                                │  │ UPDATES · 1
│ Add another account…                                 │  │   3h Bank — Your statement is ready
│ Open settings folder                                 │  │ PROMOTIONS · 1
│ Quit                                                 │  │   5h Shop — 50% off everything
│                                                      │  │ Remove this account…
└──────────────────────────────────────────────────────┘
```

## Install (Ubuntu 22.04 / 24.04, GNOME)

```bash
git clone -b claude/ubuntu-email-notifications-bak0b8 https://github.com/shrutsureja/gmail-notifier.git
cd gmail-notifier
./install.sh
```

The installer:
1. installs the desktop libraries with `apt` (asks for your password once),
2. removes the old Go version if it's installed,
3. copies the app to `~/.local/share/gmail-notifier` and adds `~/.local/bin/gmail-notifier`,
4. sets it to start at every login (`~/.config/autostart`) and turns on Ubuntu's tray-icon extension,
5. walks you through adding your accounts, then starts it.

### Getting an app password (once per account)

Gmail won't accept your normal password from apps. For each account:
1. Turn on **2-Step Verification**: <https://myaccount.google.com/signinoptions/two-step-verification>
2. Create an **app password**: <https://myaccount.google.com/apppasswords> (any name, e.g. "Ubuntu notifier")
3. Make sure **IMAP is enabled**: Gmail → ⚙ → See all settings → Forwarding and POP/IMAP → Enable IMAP.

Then run `gmail-notifier add-account`, which checks the login before saving anything. **Never paste app passwords into chats or files you share.**

## Commands

| Command | What it does |
|---|---|
| `gmail-notifier` | Runs the tray app (autostart does this for you) |
| `gmail-notifier add-account` | Add or update an account; asks for the app password at a hidden prompt and tests the login first |
| `gmail-notifier remove-account you@gmail.com` | Remove an account and delete its saved password (asks first; `--yes` skips that) |
| `gmail-notifier doctor` | Checks everything (libraries, notifications, tray extension, accounts, network) and says how to fix what's wrong. **Start here if something seems off.** |
| `gmail-notifier check` | Logs in to each account and shows the unread count |
| `gmail-notifier unread` | Lists unread emails with their Gmail links (`--account`, `--limit`, `--category`) |
| `gmail-notifier accounts` / `status` / `logs` | Configured accounts / is it running / the log |
| `gmail-notifier test-notification` | Shows a sample popup |

Add `--json` to `doctor`, `check`, `unread`, `accounts` and `status` for machine-readable output. That's what AI assistants should use (see [AGENTS.md](AGENTS.md)). No command takes a password as an argument or ever prints one.

### Removing an account

Either way works, and both also delete the saved app password from the keyring:
- **From the tray:** open the account's submenu → **Remove this account…** → **Remove**.
- **From a terminal:** `gmail-notifier remove-account you@gmail.com` (or use its label, e.g. `remove-account Work`).

If you also want to revoke the app password at Google, delete it at <https://myaccount.google.com/apppasswords>.

## Settings

`~/.config/gmail-notifier/config.ini` (the "Open settings folder" menu item opens it):

```ini
[settings]
; which tabs pop up a notification (all four still show in the tray menu)
notify = primary, updates, social, promotions
max_items_per_account = 10

[account me@gmail.com]
label = Personal

[account me@company.com]
label = Work
```

After editing, restart the app (Quit, then launch "Gmail Notifier" from the app grid) – `add-account`/`remove-account` reload it automatically.

## How it works

One background thread per account keeps an IMAP connection to `imap.gmail.com` in **IDLE** mode, so Gmail pushes "new mail" to us instantly. The highest message number already seen is saved in `~/.local/state/gmail-notifier/state.json`, so at the next start the app asks for everything newer. That's how mail from while the laptop was off is found, and nothing is ever notified twice. The very first run only records a starting point, so it doesn't spam you about your existing backlog (that still shows in the tray).

It reconnects on its own: immediately when Ubuntu resumes from suspend or the network comes back, and otherwise with backoff (3s → 60s). Dead connections are caught by TCP keepalive. Gmail's tabs are detected with Gmail's own search (`category:social` etc.). Links use Gmail's message ID, `https://mail.google.com/mail/u/<you@gmail.com>/#all/<id>`, which opens the email in the right account even when several are signed in.

The mailbox is opened read-only, so the app never marks anything read unless you press **Mark as read**.

## Troubleshooting

- **No icon in the top bar** – open the *Extensions* app and make sure **Ubuntu AppIndicators** is on, then log out and back in.
- **"login failed"** in the menu – run `gmail-notifier check`; re-create the app password and run `gmail-notifier add-account` again.
- **No popups** – run `gmail-notifier test-notification`; check *Settings → Notifications* (Do Not Disturb off, "Gmail Notifier" allowed). Also check the **Pause notifications** item in the menu.
- **Logs** – `~/.local/state/gmail-notifier/gmail-notifier.log`

Uninstall with `./uninstall.sh` (add `--purge` to remove settings too).

## Design

The menu layout, notification rules, colors and icons are in [`design/DESIGN.md`](design/DESIGN.md) and [`design/tokens.json`](design/tokens.json). Mockups of the layout options are in [`design/mockups/`](design/mockups/).

## Development

```bash
python3 -m unittest tests.test_engine tests.test_cli   # engine + CLI vs. a fake Gmail-like IMAP server
tests/run_ui_tests.sh                   # real tray app + notifications on a headless desktop
                                        # (needs: xvfb dunst; sudo apt install xvfb dunst)
```

The tests use an in-process fake IMAP server (`tests/fake_imap.py`) that supports IDLE, Gmail's X-GM extensions and categories. No real account is needed.
