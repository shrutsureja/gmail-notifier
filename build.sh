#!/bin/bash
set -e

echo "Building Gmail Notifier..."

# Generate a random encryption key for this build
ENCRYPTION_KEY=$(openssl rand -base64 32 | tr -d '\n')
echo "Generated encryption key for this build"

# Build the binary with the encryption key embedded
echo "Compiling Go binary..."
go build -ldflags "-X 'main.encryptionKey=${ENCRYPTION_KEY}'" -o gmail-notifier

# Create debian package structure
echo "Creating package structure..."
rm -rf debian
mkdir -p debian/DEBIAN debian/usr/bin debian/usr/share/applications

# Copy control file
cat > debian/DEBIAN/control << 'EOF'
Package: gmail-notifier-2
Version: 1.0.0
Section: utils
Priority: optional
Architecture: amd64
Depends: libayatana-appindicator3-1
Maintainer: shrutsureja <shrutsureja@users.noreply.github.com>
Description: Gmail notifier for Ubuntu
 A system tray notifier for Gmail that supports multiple accounts.
 Uses Gmail App Passwords for authentication and IMAP IDLE for
 real-time notifications.
EOF

# Copy desktop file
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
X-GNOME-Autostart-enabled=true
EOF

# Copy binary
cp gmail-notifier debian/usr/bin/
chmod 755 debian/usr/bin/gmail-notifier

# Build .deb package
echo "Building .deb package..."
dpkg-deb --build debian gmail-notifier-2_1.0.0_amd64.deb

echo "Done! Package created: gmail-notifier-2_1.0.0_amd64.deb"
ls -lh gmail-notifier-2_1.0.0_amd64.deb
