# Security Implementation

## Overview

This document describes the security measures implemented in Gmail Notifier to protect user credentials (Gmail App Passwords).

## Problem

Previously, Gmail App Passwords were stored in plain text in the config file (`~/.config/gmail-notifier/config.json`). This posed a security risk if the file was accidentally shared or accessed by unauthorized users.

## Solution

We implemented a multi-layered security approach:

### 1. Password Encryption (AES-GCM)

All passwords in the config file are encrypted using AES-GCM (Galois/Counter Mode), a modern authenticated encryption algorithm that provides both confidentiality and authenticity.

**Implementation Details:**
- Algorithm: AES-256-GCM
- Key size: 32 bytes (256 bits)
- Nonce: Randomly generated for each encryption (12 bytes)
- Output: Base64-encoded ciphertext

**Code Location:** `crypto.go`

### 2. User-Specific Persistent Encryption Key

Each user has their own unique encryption key that is generated on first use and persists across version upgrades.

**How it works:**
1. On first run, a random 32-byte encryption key is generated
2. The key is stored at `~/.config/gmail-notifier/.encryption_key` with 0600 permissions
3. The same key is reused for all encryption/decryption operations
4. **The key persists across version upgrades** - no need to re-enter passwords when updating

**Key Location:** `~/.config/gmail-notifier/.encryption_key`

**Build Script:** `build.sh` (no longer needs to generate keys)

### 3. Restricted File Permissions

Config files and encryption keys are created with restrictive permissions to prevent unauthorized access:

- Config directory: `0700` (rwx------)
- Config file: `0600` (rw-------)
- Encryption key file: `0600` (rw-------)

This ensures only the file owner can read or write the config and encryption key.

**Code Location:** `config.go` and `crypto.go` (getEncryptionKey function)

### 4. Backward Compatibility

The implementation includes backward compatibility for existing users:

- If a password cannot be decrypted (because it's plaintext), it's returned as-is
- On the next save, it will be encrypted automatically
- This allows seamless migration from unencrypted to encrypted passwords

## Security Properties

### What's Protected

1. **Passwords at rest**: Encrypted in the config file
2. **Casual file access**: File permissions prevent other users from reading
3. **Accidental sharing**: Encrypted passwords are useless without the binary

### What's NOT Protected

1. **Memory**: Passwords are decrypted in memory during runtime
2. **Binary analysis**: A determined attacker could extract the encryption key from the binary
3. **Root access**: Root users can read any file regardless of permissions
4. **Process inspection**: Running processes can be inspected to extract passwords

## Threat Model

This implementation protects against:

- ✅ Accidental exposure of config file
- ✅ Casual file browsing by other users
- ✅ Config file being committed to version control
- ✅ Shoulder surfing (encrypted passwords are not readable)

This implementation does NOT protect against:

- ❌ Malware with root privileges
- ❌ Memory dumping attacks
- ❌ Sophisticated reverse engineering of the binary
- ❌ Keyloggers or runtime inspection

## Usage

### For Users

1. **Initial Setup:**
   - Create config file with plaintext passwords
   - Run the application - passwords are automatically encrypted
   - An encryption key is automatically generated and stored
   - Check the config file - passwords are now encrypted strings

2. **Upgrading to New Version:**
   - Install the new version
   - Run the application with existing encrypted config
   - **No need to re-enter passwords** - the encryption key persists across upgrades
   - Everything works seamlessly

### For Developers

1. **Building:**
   ```bash
   ./build.sh  # Simply builds the binary
   ```

2. **Testing:**
   ```bash
   go test -v crypto_test.go crypto.go
   ```

3. **Development Build:**
   ```bash
   go build -o gmail-notifier
   ```

## Implementation Files

- `crypto.go`: Encryption/decryption functions and key management
- `crypto_test.go`: Tests for encryption functionality
- `config.go`: Modified to encrypt on save and decrypt on load
- `build.sh`: Standard build script (no key generation needed)

## Future Improvements

Potential enhancements for even better security:

1. **System Keyring Integration**: Use system keyrings (GNOME Keyring, KWallet) to store the encryption key
2. **Key Derivation**: Use PBKDF2 or Argon2 for additional key derivation
3. **Hardware Security**: Support for hardware security modules (HSM)
4. **Secure Memory**: Use mlock/munlock to prevent password swapping
5. **Auto-lock**: Implement timeout-based password clearing from memory

## Compliance

This implementation follows security best practices:

- Uses industry-standard encryption (AES-GCM)
- Implements proper file permissions
- Provides defense in depth
- Maintains backward compatibility
- Includes comprehensive testing

## Questions?

For security concerns or questions, please open an issue on GitHub.
