# Migration Guide: Password Encryption

## For Existing Users

If you're upgrading from a version without password encryption, follow these steps:

### Automatic Migration (Recommended)

The easiest way is to let the application automatically migrate your passwords:

1. **Stop the application** if it's running
2. **Update to the new version** (via .deb package or rebuild)
3. **Run the application** - it will automatically:
   - Generate a unique encryption key (stored in `~/.config/gmail-notifier/.encryption_key`)
   - Detect plaintext passwords
   - Encrypt them on the first save
   - Update your config file

Your passwords will be preserved and automatically encrypted!

### Upgrading Between Versions

When upgrading from one version to another (e.g., 1.1 to 1.2):

1. **Install the new version**
2. **Run the application** - it will automatically:
   - Use the existing encryption key
   - Decrypt passwords with the same key
   - Everything works seamlessly

**No need to re-enter passwords when upgrading!** The encryption key persists across versions.

### Manual Migration (Optional)

If you prefer more control:

1. **Backup your config:**
   ```bash
   cp ~/.config/gmail-notifier/config.json ~/.config/gmail-notifier/config.json.backup
   ```

2. **Note your passwords** (you'll need to re-enter them)

3. **Update the application**

4. **Delete the old config:**
   ```bash
   rm ~/.config/gmail-notifier/config.json
   ```

5. **Run the application** - it will create a new config

6. **Add your accounts** using the menu or by editing the new config file

### Verification

After migration, check your config file:

```bash
cat ~/.config/gmail-notifier/config.json
```

You should see encrypted passwords (long base64 strings) instead of plaintext:

```json
{
  "accounts": [
    {
      "email": "your-email@gmail.com",
      "password": "ynjQmJvpZxyGYJDxgg2MkcLi5mwprrq2UI5Yao7085R062LtRVAbFI9Flz3Dng4="
    }
  ]
}
```

### Troubleshooting

**Problem:** Application fails to connect after migration

**Solution:** 
1. Check logs: `cat ~/.config/gmail-notifier/gmail-notifier.log`
2. If you see decryption errors, the encryption key may be corrupted
3. Delete both files and start fresh:
   ```bash
   rm ~/.config/gmail-notifier/config.json
   rm ~/.config/gmail-notifier/.encryption_key
   ```
4. Re-enter your passwords in a new config

**Problem:** Passwords are still in plaintext

**Solution:**
1. Make sure you're running the new version
2. Trigger a config save by adding/removing an account
3. Check file permissions: `ls -la ~/.config/gmail-notifier/`

### Important Notes

✅ **Version upgrades are seamless**: The encryption key persists, so passwords remain encrypted and accessible across version upgrades.

✅ **Each user has their own key**: Every user on the system has a unique encryption key, providing better security than a shared key.

✅ **Backward compatible**: Old plaintext passwords work with the new version - they'll be encrypted automatically.

🔒 **Secure**: The encryption key is stored with 0600 permissions (owner-only access).

## For Developers Rebuilding

When rebuilding from source:

1. **Build the new version:** `./build.sh`
2. **Run the application** - it will use the existing encryption key
3. **No need to re-enter passwords** - the key persists across rebuilds

The encryption key is stored in your config directory, not in the binary, so rebuilding doesn't affect it.
