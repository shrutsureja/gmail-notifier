# Migration Guide: Password Encryption

## For Existing Users

If you're upgrading from a version without password encryption, follow these steps:

### Automatic Migration (Recommended)

The easiest way is to let the application automatically migrate your passwords:

1. **Stop the application** if it's running
2. **Update to the new version** (via .deb package or rebuild)
3. **Run the application** - it will automatically:
   - Detect plaintext passwords
   - Encrypt them on the first save
   - Update your config file

Your passwords will be preserved and automatically encrypted!

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
2. If you see decryption errors, delete the config and re-enter passwords
3. Ensure you're using the correct binary (from the new build)

**Problem:** Passwords are still in plaintext

**Solution:**
1. Make sure you're running the new version
2. Trigger a config save by adding/removing an account
3. Check file permissions: `ls -la ~/.config/gmail-notifier/config.json`

### Important Notes

⚠️ **Different builds, different keys**: Each build has a unique encryption key. If you rebuild the application, you'll need to re-enter your passwords.

✅ **Backward compatible**: Old plaintext passwords work with the new version - they'll be encrypted automatically.

🔒 **Secure**: Encrypted passwords cannot be decrypted without the specific binary that encrypted them.

## For Developers Rebuilding

If you're rebuilding from source:

1. **Export your passwords** before rebuilding (save them somewhere secure)
2. **Run `./build.sh`** to create a new build with a new encryption key
3. **Delete the old config:** `rm ~/.config/gmail-notifier/config.json`
4. **Re-enter your passwords** in the new config

This is necessary because each build generates a unique encryption key that's embedded in the binary.
