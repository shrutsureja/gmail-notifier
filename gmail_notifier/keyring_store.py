"""Store app passwords in the GNOME keyring (libsecret), unlocked at login."""

from __future__ import annotations

_SCHEMA = None


def _secret():
    global _SCHEMA
    import gi
    gi.require_version("Secret", "1")
    from gi.repository import Secret
    if _SCHEMA is None:
        _SCHEMA = Secret.Schema.new(
            "io.github.shrutsureja.GmailNotifier",
            Secret.SchemaFlags.NONE,
            {"email": Secret.SchemaAttributeType.STRING},
        )
    return Secret


def get_password(addr: str) -> str:
    try:
        Secret = _secret()
        return Secret.password_lookup_sync(_SCHEMA, {"email": addr}, None) or ""
    except Exception:
        return ""


def set_password(addr: str, password: str) -> None:
    Secret = _secret()
    ok = Secret.password_store_sync(_SCHEMA, {"email": addr}, Secret.COLLECTION_DEFAULT,
                                    f"Gmail Notifier: {addr}", password, None)
    if not ok:
        raise RuntimeError("keyring refused to store the password")


def delete_password(addr: str) -> None:
    try:
        Secret = _secret()
        Secret.password_clear_sync(_SCHEMA, {"email": addr}, None)
    except Exception:
        pass
