# Gmail Notifier design system

How the tray icon, menu and notifications look and behave. Colors, type and sizes are in [`tokens.json`](tokens.json). The mockups are in [`mockups/`](mockups/); they are Claude Design canvas files, and the live canvas is the "Gmail Notifier Tray UI" artifact.

What GNOME draws itself and what we control: the top bar, menu chrome and notification cards are drawn by GNOME Shell in the user's theme, so in the real app the colors below come from Yaru dark, not from us. A tray menu can't show colored text, chips or toggles (the AppIndicator protocol only carries plain labels). The tokens describe the mockups and keep our own pieces (icons, notification text) consistent with the Ubuntu look. Anything marked **(mockup only)** can't be reproduced exactly in the real menu.

## Tray icon

| State | Icon | Label next to it |
|---|---|---|
| No unread mail | `gmail-notifier-read.svg`: outline envelope | none |
| Unread mail | `gmail-notifier-unread.svg`: envelope with a red dot | total unread count, e.g. `7` |
| An account can't log in | `gmail-notifier-error.svg`: envelope with a yellow dot | total unread count |

The icons are 22×22 SVGs drawn in light grey/white so they read on the black top bar.

## Menu (chosen layout: accounts with Gmail tabs)

Top to bottom:

1. **Header** (insensitive): `7 unread across 3 accounts`, or `No accounts set up yet` with an *Add a Gmail account…* item.
2. **LATEST**: the 5 newest unread emails across all accounts, `Sender — Subject   (Account)`. The account is shown only when there's more than one. Click to open that email.
3. **One row per account**: `Label  (email)  —  4 unread`, or `connecting…`, `offline – retrying`, `⚠ login failed`. Each expands to:
   - *Open inbox in browser*
   - one section per Gmail tab that has unread mail, in this order: **PRIMARY, UPDATES, SOCIAL, PROMOTIONS**, each `TITLE  ·  count`, then rows of `12m  Sender — Subject`
   - `…N more unread in Gmail` when there are more than `max_items_per_account` (default 10)
   - `Inbox zero 🎉` when empty
   - on errors: the error text and *Retry now*
   - *Remove this account…* (asks for confirmation; deletes the saved password too)
4. **Actions**: Refresh now · Pause notifications (check item) · Add another account… · Open settings folder · Quit.

Text rules: labels are truncated to about 64–70 characters with `…`. Underscores are escaped (menus treat `_` as a shortcut marker). Times are relative (`12m`, `2h`, `3d`).

Category colors (blue, amber, green, salmon) appear only in the mockups. **(mockup only)**

### Alternatives considered

- **Option B: grouped by tab.** Tabs first, account as a tag on each email. Better if you care about "is anything important?" more than which inbox it's in.
- **Option C: compact.** The 3 newest emails, then one line per account with a count per tab. Better if popups are your main signal.

Switching layouts only touches `TrayApp.rebuild_menu()` in `gmail_notifier/app.py`.

## Notifications

| Situation | Title | Body | Click | Buttons |
|---|---|---|---|---|
| 1–3 new emails arrive | `Sender  ·  Account` | **Subject** + first ~180 characters of the text | opens that exact email | Open · Mark as read |
| More than 3 arrive at once | `N new emails` | per-account counts, then up to 4 `• Sender: Subject` lines | opens the inbox with the most new mail | one *Open Account* button per account (up to 3), only when several accounts are involved |
| First sync after the laptop was off or offline for 2+ minutes | `N new emails while you were away` | same as above; all accounts are gathered for 4 s into **one** notification | same | same |
| Login fails | *(no popup)* | the tray icon turns yellow and the account row shows the error | | |

Rules:
- Never notify about mail that was already unread the first time an account is added. That's the baseline.
- Never notify twice about the same email, even across restarts.
- Only unread mail notifies; something you already read on your phone doesn't.
- Which tabs pop up is configurable (`notify = primary, updates, social, promotions`). Every tab always shows in the menu.
- *Pause notifications* silences popups; the menu keeps updating.
- No emoji in notification titles. GNOME already shows the app icon.

## Copy

Plain, short, from the user's side: "login failed", "offline – retrying", "Remove this account…". Errors say how to fix them, e.g. `Login failed – check the app password (gmail-notifier add-account)`. A trailing `…` means the item opens a dialog or terminal.
