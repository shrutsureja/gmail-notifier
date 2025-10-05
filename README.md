# gmail-notifier-2
Gmail notification system tray app for Ubuntu across multiple Gmail accounts

## Features

- 📧 Real-time email notifications using IMAP IDLE
- 👥 Support for multiple Gmail accounts
- 🔒 Secure authentication using Gmail App Passwords
- 🖥️ System tray integration for Ubuntu
- 💾 Persistent state management
- 🔄 Automatic reconnection on network issues

## Installation

### From .deb Package

1. Download the latest `.deb` package from releases
2. Install it:
   ```bash
   sudo dpkg -i gmail-notifier-2_1.0.0_amd64.deb
   sudo apt-get install -f  # Install dependencies if needed
   ```

### From Source

1. Install dependencies:
   ```bash
   sudo apt-get install -y libayatana-appindicator3-dev golang
   ```

2. Clone and build:
   ```bash
   git clone https://github.com/shrutsureja/gmail-notifier-2.git
   cd gmail-notifier-2
   go build -o gmail-notifier
   ```

## Configuration

1. **Enable IMAP in Gmail:**
   - Go to Gmail Settings → Forwarding and POP/IMAP
   - Enable IMAP access

2. **Create App Password:**
   - Go to Google Account → Security → 2-Step Verification
   - At the bottom, select "App passwords"
   - Generate a new app password for "Mail"
   - Save this password (you'll need it for configuration)

3. **Configure the Application:**
   
   Create a config file at `~/.config/gmail-notifier/config.json`:
   
   ```json
   {
     "accounts": [
       {
         "email": "your-email@gmail.com",
         "password": "your-app-password-here"
       },
       {
         "email": "another-email@gmail.com",
         "password": "another-app-password"
       }
     ]
   }
   ```

   **Important:** Use App Passwords, NOT your regular Gmail password!

## Usage

1. Run the application:
   ```bash
   gmail-notifier
   ```

2. The app will appear in your system tray
3. Click the tray icon to see:
   - Total unread count
   - Unread count per account
   - Refresh option
   - Quit option

## Building the .deb Package

```bash
# Build the binary
go build -o gmail-notifier

# Create package structure
mkdir -p debian/DEBIAN debian/usr/bin debian/usr/share/applications

# Copy files
cp gmail-notifier debian/usr/bin/

# Build .deb
dpkg-deb --build debian gmail-notifier-2_1.0.0_amd64.deb
```

## Project Structure

```
.
├── main.go           # Application entry point
├── config.go         # Configuration management
├── state.go          # State management (unread counts)
├── imap.go           # IMAP client with IDLE support
├── ui.go             # System tray UI
├── go.mod            # Go module definition
├── go.sum            # Go dependencies
└── debian/           # Debian package structure
    ├── DEBIAN/
    │   └── control   # Package metadata
    └── usr/
        ├── bin/
        │   └── gmail-notifier
        └── share/
            └── applications/
                └── gmail-notifier.desktop
```

## Dependencies

- Go 1.16 or higher
- [go-imap](https://github.com/emersion/go-imap) - IMAP client library
- [go-imap-idle](https://github.com/emersion/go-imap-idle) - IMAP IDLE extension
- [systray](https://github.com/getlantern/systray) - System tray library
- libayatana-appindicator3 (Ubuntu system library)

## Troubleshooting

### Application not starting

1. Check logs at `~/.config/gmail-notifier/gmail-notifier.log`
2. Verify config file exists and is valid JSON
3. Ensure App Passwords are correct

### No notifications appearing

1. Verify IMAP is enabled in Gmail settings
2. Check firewall allows connections to `imap.gmail.com:993`
3. Try the "Refresh" option in the tray menu

### Connection errors

- Ensure you're using App Passwords, not regular passwords
- Check internet connectivity
- Gmail may temporarily block new logins - check your Gmail security page

## License

MIT

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
