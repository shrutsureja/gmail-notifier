# Password Encryption Example

This example demonstrates how password encryption works in Gmail Notifier.

## Step 1: User Creates Config (Plaintext)

User creates `~/.config/gmail-notifier/config.json`:

```json
{
  "accounts": [
    {
      "email": "user@gmail.com",
      "password": "abcd efgh ijkl mnop"
    }
  ]
}
```

## Step 2: Application Loads Config

When the application starts:

1. `LoadConfig()` reads the file
2. Detects password is plaintext (not base64 encrypted)
3. Returns the password as-is (backward compatibility)
4. Application uses plaintext password to connect to Gmail
5. Encryption key is generated on first use and stored at `~/.config/gmail-notifier/.encryption_key`

## Step 3: Application Saves Config

When config is saved (e.g., after adding/removing account):

1. `SaveConfig()` is called
2. `getEncryptionKey()` retrieves or creates the user's encryption key
3. For each account:
   - Generate random 12-byte nonce
   - Encrypt password with AES-GCM using the user's persistent key
   - Encode as base64 string
4. Write encrypted config to file with 0600 permissions

## Step 4: Config File After Encryption

After the first save, the config file looks like:

```json
{
  "accounts": [
    {
      "email": "user@gmail.com",
      "password": "ynjQmJvpZxyGYJDxgg2MkcLi5mwprrq2UI5Yao7085R062LtRVAbFI9Flz3Dng4="
    }
  ]
}
```

## Step 5: Subsequent Loads

On subsequent runs:

1. `LoadConfig()` reads encrypted password
2. `getEncryptionKey()` retrieves the user's persistent encryption key
3. `DecryptPassword()` decodes base64
4. Extracts nonce (first 12 bytes)
5. Decrypts using AES-GCM with the user's persistent key
6. Returns plaintext password to application
7. Application uses decrypted password to connect to Gmail

## Step 6: Version Upgrades

When upgrading to a new version:

1. New version is installed
2. Application starts and loads config
3. `getEncryptionKey()` retrieves the **same** encryption key from `~/.config/gmail-notifier/.encryption_key`
4. Passwords decrypt successfully using the persistent key
5. **No need to re-enter passwords** - everything works seamlessly!

## Technical Details

### Encryption Process

```
Plaintext: "abcd efgh ijkl mnop"
    ↓
Get or create user's encryption key from ~/.config/gmail-notifier/.encryption_key
    ↓
Generate random nonce (12 bytes)
    ↓
AES-GCM encrypt with user's persistent key
    ↓
Prepend nonce to ciphertext
    ↓
Base64 encode
    ↓
Encrypted: "ynjQmJvpZxyGYJDxgg2MkcLi5mwprrq2UI5Yao7085R062LtRVAbFI9Flz3Dng4="
```

### Decryption Process

```
Encrypted: "ynjQmJvpZxyGYJDxgg2MkcLi5mwprrq2UI5Yao7085R062LtRVAbFI9Flz3Dng4="
    ↓
Get user's encryption key from ~/.config/gmail-notifier/.encryption_key
    ↓
Base64 decode
    ↓
Extract nonce (first 12 bytes)
    ↓
Extract ciphertext (remaining bytes)
    ↓
AES-GCM decrypt with user's persistent key
    ↓
Plaintext: "abcd efgh ijkl mnop"
```

### Key Generation (First Use)

```
First run of application
    ↓
Check if ~/.config/gmail-notifier/.encryption_key exists
    ↓
If not exists:
    Generate random 32-byte key
    Base64 encode the key
    Save to ~/.config/gmail-notifier/.encryption_key with 0600 permissions
    ↓
If exists:
    Read and decode existing key
    ↓
Return 32-byte encryption key for use
```

### Key Persistence Across Upgrades

```
Version 1.1 installed
    ↓
User runs app, encryption key created: ~/.config/gmail-notifier/.encryption_key
    ↓
Passwords encrypted with this key
    ↓
Version 1.2 released and installed
    ↓
User runs new version
    ↓
App reads SAME encryption key from ~/.config/gmail-notifier/.encryption_key
    ↓
Passwords decrypt successfully
    ↓
No re-entry needed!
```

## Security Notes

1. **Random Nonce**: Each encryption uses a fresh random nonce, so the same password encrypts to different ciphertext each time

2. **Authenticated Encryption**: AES-GCM provides both encryption and authentication - any tampering will be detected

3. **User-Specific Persistent Key**: Each user has their own unique key that persists across version upgrades

4. **File Permissions**: Both config and encryption key stored with 0600 (owner read/write only)

5. **Version Upgrade Safe**: Encryption key persists, so no need to re-enter passwords when upgrading

## Code Flow

```
User starts app
    ↓
main.go: NewTrayUI() → onReady()
    ↓
ui.go: LoadConfig()
    ↓
config.go: LoadConfig() reads file
    ↓
config.go: DecryptPassword() for each account
    ↓
crypto.go: getEncryptionKey() - retrieves or creates user's key
    ↓
crypto.go: Base64 decode → AES-GCM decrypt
    ↓
Return decrypted passwords
    ↓
imap.go: Connect to Gmail with plaintext passwords
```

## Testing

Run the encryption tests:

```bash
go test -v crypto_test.go crypto.go
```

This will verify:
- Encryption and decryption work correctly
- Empty passwords are handled
- Backward compatibility with plaintext
- Each encryption produces different output
- All decryptions produce correct plaintext
