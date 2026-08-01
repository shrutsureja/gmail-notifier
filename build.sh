#!/bin/bash
set -e

echo "Building Gmail Notifier..."

# Build the binary
echo "Compiling Go binary..."
go build -o gmail-notifier

# Create debian package structure
echo "Creating package structure..."
rm -rf debian
mkdir -p debian/DEBIAN debian/usr/bin debian/usr/share/applications debian/usr/lib/systemd/user

# Copy control file
cat > debian/DEBIAN/control << 'EOF'
Package: gmail-notifier-2
Version: 1.0.0
Section: utils
Priority: optional
Architecture: amd64
Depends: libayatana-appindicator3-1, libnotify-bin
Maintainer: shrutsureja <shrutsureja@users.noreply.github.com>
Description: Gmail notifier for Ubuntu
 A system tray notifier for Gmail that supports multiple accounts.
 Uses Gmail App Passwords for authentication and IMAP IDLE for
 real-time notifications, with desktop popups for new mail.
EOF

# Copy desktop file (application menu launcher)
cat > debian/usr/share/applications/gmail-notifier.desktop << 'EOF'
[Desktop Entry]
Name=Gmail Notifier
Comment=Gmail notification for Ubuntu
Exec=/usr/bin/gmail-notifier
Icon=mail-notification
Terminal=false
Type=Application
Categories=Network;Email;
StartupNotify=false
EOF

# Copy systemd --user unit (this is what actually autostarts the app on login;
# a plain .desktop file under /usr/share/applications does NOT autostart,
# regardless of X-GNOME-Autostart-enabled - that key only matters under
# /etc/xdg/autostart or ~/.config/autostart)
cp gmail-notifier.service debian/usr/lib/systemd/user/gmail-notifier.service

# Copy binary
cp gmail-notifier debian/usr/bin/
chmod 755 debian/usr/bin/gmail-notifier

# Build .deb package
echo "Building .deb package..."
dpkg-deb --build debian gmail-notifier-2_1.0.0_amd64.deb

echo "Done! Package created: gmail-notifier-2_1.0.0_amd64.deb"
ls -lh gmail-notifier-2_1.0.0_amd64.deb
echo ""
echo "After installing, enable autostart with:"
echo "  systemctl --user daemon-reload"
echo "  systemctl --user enable --now gmail-notifier.service"
