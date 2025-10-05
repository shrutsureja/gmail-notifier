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

## Step 3: Application Saves Config

When config is saved (e.g., after adding/removing account):

1. `SaveConfig()` is called
2. For each account:
   - Generate random 12-byte nonce
   - Encrypt password with AES-GCM using build-time key
   - Encode as base64 string
3. Write encrypted config to file with 0600 permissions

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
2. `DecryptPassword()` decodes base64
3. Extracts nonce (first 12 bytes)
4. Decrypts using AES-GCM with build-time key
5. Returns plaintext password to application
6. Application uses decrypted password to connect to Gmail

## Technical Details

### Encryption Process

```
Plaintext: "abcd efgh ijkl mnop"
    ↓
Generate random nonce (12 bytes)
    ↓
AES-GCM encrypt with build-time key
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
Base64 decode
    ↓
Extract nonce (first 12 bytes)
    ↓
Extract ciphertext (remaining bytes)
    ↓
AES-GCM decrypt with build-time key
    ↓
Plaintext: "abcd efgh ijkl mnop"
```

### Key Generation (Build Time)

```bash
# In build.sh
ENCRYPTION_KEY=$(openssl rand -base64 32 | tr -d '\n')
# Example output: "x0JQYs/038y0HvcrXefUInGkz+hbSGxyrUsPDuvQX8U="

# Embed in binary
go build -ldflags "-X 'main.encryptionKey=${ENCRYPTION_KEY}'" -o gmail-notifier
```

### Key Derivation

```go
// Build-time key (example): "x0JQYs/038y0HvcrXefUInGkz+hbSGxyrUsPDuvQX8U="
//    ↓
// Convert to bytes
//    ↓
// Ensure exactly 32 bytes (pad or truncate)
//    ↓
// Use with AES-256
```

## Security Notes

1. **Random Nonce**: Each encryption uses a fresh random nonce, so the same password encrypts to different ciphertext each time

2. **Authenticated Encryption**: AES-GCM provides both encryption and authentication - any tampering will be detected

3. **Build-Time Key**: Each build has a unique key, preventing cross-binary decryption

4. **File Permissions**: Config stored with 0600 (owner read/write only)

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
