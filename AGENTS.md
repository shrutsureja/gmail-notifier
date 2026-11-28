# Notes for AI assistants

This repo is a Gmail tray notifier for Ubuntu (Python 3 + GTK/AppIndicator/libnotify). The design spec is `design/DESIGN.md`.

## Secrets: hard rules
- **Never ask for, accept, store, print or pass a Gmail app password.** Only a person adds one, with `gmail-notifier add-account` in their own terminal. That command refuses to run without a real terminal, and there's no flag that takes a password.
- Don't read the GNOME keyring, and don't print `~/.config/gmail-notifier/config.ini` (it may contain an `app_password` line).
- If an account has no password or its login fails, tell the user to run `gmail-notifier add-account` themselves.

## Diagnose and inspect (safe, read-only, `--json` everywhere)
| Command | Use it to |
|---|---|
| `gmail-notifier doctor --json` | check libraries, notification server, tray extension, config, network, and whether the app is running. Each failed check has a `fix` |
| `gmail-notifier accounts --json` | list accounts; `password` is only `keyring` / `config` / `missing` |
| `gmail-notifier check --json [--account X]` | log in to each account: `ok`, `unread`, `idle`, `error` |
| `gmail-notifier unread --json [--account X] [--limit N] [--category primary\|updates\|social\|promotions]` | list unread emails (sender, subject, snippet, tab, date, Gmail link). Opens the mailbox read-only, so it never marks anything read |
| `gmail-notifier status --json` | is the tray app running, last seen UIDs, last log lines |
| `gmail-notifier logs -n 100` | the app log (`~/.local/state/gmail-notifier/gmail-notifier.log`) |
| `gmail-notifier test-notification` | pop up a sample notification |

Exit code 0 = all good, 1 = something failed (details in the JSON), 2 = refused (e.g. needs a person or `--yes`).

To check end to end that it works: `doctor --json`, then `check --json`. Ask the user to send a test email from one of their accounts to another; it should show up in `unread --json` and as a popup within seconds.

## Changes that need the user's OK
- `gmail-notifier remove-account EMAIL --yes` deletes the account and its saved password. Only do this when the user asked.
- Don't mark mail read, send mail, or open links on the user's behalf unless asked.

## Developing
- `python3 -m unittest tests.test_engine tests.test_cli` uses a fake Gmail-like IMAP server (`tests/fake_imap.py`). No real account is needed and no password is used.
- `tests/run_ui_tests.sh` runs the real tray app on a headless desktop (needs `xvfb dunst`).
- Use the system Python (`/usr/bin/python3`); the GTK bindings come from apt.
