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

## Counting: big inboxes

The **top-bar number** is unread mail from the last `recent_days` days (default 7) in the tabs listed in `notify`, summed across accounts. It's capped at `999+`. Old unread mail is never counted there; it shows only as each account's total. Counts per tab come from Gmail's own search, so they stay accurate with tens of thousands of unread emails, and only the few emails actually listed are downloaded.

## Menu (chosen layout: accounts with Gmail tabs)

Top to bottom:

1. **Header** (insensitive): `7 unread this week across 3 accounts`, or `No accounts set up yet` with an *Add a Gmail account…* item.
2. **LATEST**: the 5 newest unread emails across all accounts, from the `notify` tabs only, `Sender — Subject   (Account)`. The account is shown only when there's more than one. Click to open that email.
3. **One row per account**: `Label  (email)  —  4 unread`, or `23 this week · 12,483 unread` when old unread mail exists, or `connecting…`, `offline – retrying`, `⚠ login failed`. Each expands to:
   - *Open inbox in browser*
   - one section per Gmail tab with recent unread mail, in this order: **PRIMARY, UPDATES, SOCIAL, PROMOTIONS**, each `TITLE  ·  count` (the real count, from the server), then that tab's newest `max_items_per_category` (default 4) as `12m  Sender — Subject`
   - `…138 more in Promotions` when a tab has more than that; opens that tab in Gmail
   - `All 12,483 unread in Gmail…` when there's older unread mail outside the window
   - `Nothing new this week` (old unread only) or `Inbox zero 🎉` (none at all)
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
| A new email, and fewer than 3 popups in the last minute | `Sender  ·  Account` | **Subject** + first ~180 characters of the text | opens that exact email | Open · Mark as read |
| More than that (a burst, or mail trickling in) | `N new emails`, or `N more new emails` once individual popups were already shown | per-account counts, then up to 4 `• Sender: Subject` lines | opens the inbox with the most new mail | one *Open Account* button per account (up to 3), only when several accounts are involved |
| First sync after the laptop was off or offline for 2+ minutes | `N new emails while you were away` | same as above; all accounts are gathered for 4 s into **one** notification | same | same |
| Login fails | *(no popup)* | the tray icon turns yellow and the account row shows the error | | |

Rules:
- New mail waits 3 seconds before notifying, so mail arriving together is grouped.
- At most 3 individual popups per minute. After that, one summary popup collects the rest and is **updated in place** (same popup, new count) until a minute passes with no new mail.
- Never notify about mail that was already unread the first time an account is added. That's the baseline.
- Never notify twice about the same email, even across restarts.
- Only unread mail notifies; something you already read on your phone doesn't.
- Which tabs pop up is configurable (`notify = primary, updates, social, promotions`). Every tab always shows in the menu.
- *Pause notifications* silences popups; the menu keeps updating.
- No emoji in notification titles. GNOME already shows the app icon.

## Copy

Plain, short, from the user's side: "login failed", "offline – retrying", "Remove this account…". Errors say how to fix them, e.g. `Login failed – check the app password (gmail-notifier add-account)`. A trailing `…` means the item opens a dialog or terminal.
