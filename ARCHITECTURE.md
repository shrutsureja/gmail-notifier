# Gmail Notifier Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                           Ubuntu Desktop                             │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                       System Tray                               │ │
│  │  ┌──────────────────────────────────────────────────────────┐  │ │
│  │  │  [📧 3]  Gmail Notifier                                   │  │ │
│  │  │  ┌────────────────────────────────────────────────────┐  │  │ │
│  │  │  │  • user1@gmail.com: 2 unread                       │  │  │ │
│  │  │  │  • user2@gmail.com: 1 unread                       │  │  │ │
│  │  │  │  ───────────────────────────────                   │  │  │ │
│  │  │  │  • Refresh                                         │  │  │ │
│  │  │  │  • Quit                                            │  │  │ │
│  │  │  └────────────────────────────────────────────────────┘  │  │ │
│  │  └──────────────────────────────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                    ▲                                  │
│                                    │                                  │
└────────────────────────────────────┼──────────────────────────────────┘
                                     │
                                     │ systray library
                                     │
┌────────────────────────────────────┼──────────────────────────────────┐
│                    gmail-notifier Application                         │
│                                    │                                  │
│  ┌─────────────────────────────────┴─────────────────────────────┐  │
│  │                          ui.go (TrayUI)                        │  │
│  │  • Manages system tray icon and menu                           │  │
│  │  • Displays total unread count                                 │  │
│  │  • Shows per-account status                                    │  │
│  │  • Handles user interactions (Refresh, Quit)                   │  │
│  └────────────────────────┬────────────────────────────────────────┘  │
│                           │                                           │
│                           │ Updates                                   │
│                           ▼                                           │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │                    state.go (State)                             │  │
│  │  • Thread-safe unread count storage                            │  │
│  │  • Per-account state tracking                                  │  │
│  │  • Persists to ~/.config/gmail-notifier/state.json             │  │
│  │  • Calculates total unread count                               │  │
│  └────────────────────────┬────────────────────────────────────────┘  │
│                           ▲                                           │
│                           │ State Updates                             │
│                           │                                           │
│  ┌────────────────────────┴───────────────────┐                      │
│  │                                             │                      │
│  │  ┌────────────────────┐  ┌────────────────────┐                  │
│  │  │  imap.go           │  │  imap.go           │  ...              │
│  │  │  IMAPClient #1     │  │  IMAPClient #2     │                  │
│  │  │                    │  │                    │                  │
│  │  │  • Connects via    │  │  • Connects via    │                  │
│  │  │    IMAP/TLS        │  │    IMAP/TLS        │                  │
│  │  │  • Uses IDLE       │  │  • Uses IDLE       │                  │
│  │  │  • Monitors inbox  │  │  • Monitors inbox  │                  │
│  │  │  • Auto-reconnect  │  │  • Auto-reconnect  │                  │
│  │  └────────┬───────────┘  └────────┬───────────┘                  │
│  │           │                       │                               │
│  └───────────┼───────────────────────┼───────────────────────────────┘
│              │                       │                               │
│  ┌───────────┴───────────────────────┴───────────────────────────┐  │
│  │                   config.go (Config)                           │  │
│  │  • Loads account configurations                                │  │
│  │  • From ~/.config/gmail-notifier/config.json                   │  │
│  │  • Stores email + app password pairs                           │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │                      main.go                                    │  │
│  │  • Application entry point                                      │  │
│  │  • Initializes logging                                          │  │
│  │  • Creates and starts TrayUI                                    │  │
│  └────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────┘
                           │                       │
                           │ IMAP/TLS              │ IMAP/TLS
                           │ Port 993              │ Port 993
                           ▼                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Gmail IMAP Servers                            │
│                     imap.gmail.com:993                               │
│                                                                       │
│  ┌───────────────────┐           ┌───────────────────┐              │
│  │  user1@gmail.com  │           │  user2@gmail.com  │              │
│  │  Inbox            │           │  Inbox            │              │
│  │  • 2 unread       │           │  • 1 unread       │              │
│  └───────────────────┘           └───────────────────┘              │
│                                                                       │
│  IDLE Push Notifications ──────────────────────────────────▲         │
│  (Real-time updates when new email arrives)                          │
└─────────────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

### main.go
- **Purpose**: Application bootstrap
- **Responsibilities**:
  - Initialize logging system
  - Create log file at `~/.config/gmail-notifier/gmail-notifier.log`
  - Create TrayUI instance
  - Start the application event loop

### ui.go (TrayUI)
- **Purpose**: User interface management
- **Responsibilities**:
  - Initialize system tray icon
  - Create and manage menu items
  - Display unread counts
  - Handle user interactions (clicks on menu items)
  - Create IMAPClient instances for each account
  - Update display when counts change

### state.go (State)
- **Purpose**: Application state management
- **Responsibilities**:
  - Store unread counts per account
  - Provide thread-safe access to state
  - Calculate total unread count
  - Persist state to disk
  - Load state on startup

### imap.go (IMAPClient)
- **Purpose**: Email monitoring
- **Responsibilities**:
  - Connect to Gmail via IMAP over TLS
  - Authenticate using App Passwords
  - Monitor inbox using IDLE extension
  - Detect new emails in real-time
  - Refresh connection periodically
  - Handle connection errors and reconnect
  - Notify state manager of count changes

### config.go (Config)
- **Purpose**: Configuration management
- **Responsibilities**:
  - Load account configurations from JSON file
  - Save configurations to disk
  - Create default config if none exists
  - Validate configuration structure

## Data Flow

### Startup Sequence
```
1. main.go starts
2. Initializes logging
3. Creates TrayUI instance
4. TrayUI.Run() calls onReady()
5. onReady() loads Config from disk
6. For each account in config:
   a. Create IMAPClient
   b. Connect to Gmail
   c. Start IDLE monitoring
7. Display initial unread counts in tray
```

### Update Flow (New Email Arrives)
```
1. Gmail server detects new email
2. IDLE push notification sent to IMAPClient
3. IMAPClient receives update
4. IMAPClient queries current unread count
5. IMAPClient calls onUpdate callback
6. State.UpdateUnreadCount() updates state
7. State saves to disk (asynchronously)
8. TrayUI updates menu item for account
9. TrayUI updates total count in tray icon
```

### Manual Refresh Flow
```
1. User clicks "Refresh" in tray menu
2. TrayUI.refreshAll() called
3. For each IMAPClient:
   a. Query current unread count
   b. Call onUpdate callback
4. State updated for each account
5. Tray display updated
```

## Threading Model

### Main Thread
- System tray event loop
- UI updates
- Menu handling

### State Management
- Read operations: Multiple concurrent readers
- Write operations: Single writer with mutex lock
- Disk I/O: Asynchronous (goroutine per save)

### IMAP Clients
- Each account runs in its own goroutine
- Independent connection lifecycle
- Separate error handling and reconnection logic

## File System Layout

```
~/.config/gmail-notifier/
├── config.json          # User configuration (emails + passwords)
├── state.json           # Persisted state (unread counts)
└── gmail-notifier.log   # Application logs
```

## Security Considerations

1. **Password Storage**: App Passwords stored in plaintext in config.json
   - File should have restricted permissions (0644)
   - Users should use App Passwords, not regular passwords
   
2. **Network Security**: All IMAP communication over TLS (port 993)
   - Certificates validated by Go's TLS library
   
3. **Process Isolation**: Runs as user process
   - No elevated privileges required
   - Files stored in user's home directory

## Error Handling

### Connection Failures
- Automatic reconnection with exponential backoff
- Logged to gmail-notifier.log
- User sees stale count until reconnection

### Configuration Errors
- Invalid JSON: Shows error in tray menu
- Missing config: Creates default empty config

### IDLE Failures
- Falls back to periodic polling if IDLE not supported
- Refreshes IDLE connection every 5 minutes

## Performance Characteristics

### Resource Usage
- Memory: ~20-30 MB per instance
- CPU: Near zero when idle
- Network: Persistent IMAP connections (minimal bandwidth)

### Scalability
- Tested with multiple accounts
- Each account uses one persistent connection
- State updates are atomic and thread-safe

## Dependencies

### External Libraries
```
github.com/emersion/go-imap        # IMAP protocol
github.com/emersion/go-imap-idle   # IDLE extension
github.com/getlantern/systray      # System tray
```

### System Libraries
```
libayatana-appindicator3-1         # Ubuntu tray support
```

## Build Process

```
Source Files (.go)
      │
      ├─> go build
      │
      ▼
  gmail-notifier (binary)
      │
      ├─> Copy to debian/usr/bin/
      │
      ▼
  debian/ (package structure)
      │
      ├─> dpkg-deb --build
      │
      ▼
gmail-notifier-2_1.0.0_amd64.deb
```
