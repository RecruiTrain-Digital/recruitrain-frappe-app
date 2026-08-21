# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.utils.vapid_config
========================================

VAPID Key Management for Web Push Notifications.

Security rules (enforced):
1. VAPID private key is server-only — NEVER returned to frontend, logged, or in API responses.
2. VAPID public key may be returned to authenticated employer clients via the controlled API.
3. Key persistence precedence (checked in order):
   a. frappe.conf (site_config.json / common_site_config.json) — PERSISTENT, survives restarts.
   b. Redis cache — fast-path secondary lookup.
   c. Auto-generate + persist to site_config immediately.

IMPORTANT: Keys are written to site_config.json via frappe.installer.update_site_config.
A Redis flush or restart DOES NOT invalidate existing browser push subscriptions.
"""

from __future__ import annotations

import frappe
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat
from py_vapid import Vapid
from py_vapid.utils import b64urlencode

# Redis cache key — fast-path secondary lookup after site_config.
VAPID_CACHE_KEY = "recruitrain_vapid_keypair"


def get_vapid_credentials() -> tuple[str, str, str]:
    """Retrieve VAPID public key (b64url), private key (PEM str), and subject.

    Key resolution order:
    1. site_config.json (persistent — survives Redis flush/restart).
    2. Redis cache (fast path).
    3. Auto-generate and persist to site_config.json.

    Returns
    -------
    tuple[str, str, str]
        (public_key_b64url, private_key_pem, subject)
    """
    subject = (
        frappe.conf.get("vapid_subject")
        or frappe.conf.get("VAPID_SUBJECT")
        or "mailto:admin@recruitrain.de"
    )

    # 1. site_config.json — authoritative persistent store
    conf_pub = frappe.conf.get("vapid_public_key") or frappe.conf.get("VAPID_PUBLIC_KEY")
    conf_priv = frappe.conf.get("vapid_private_key") or frappe.conf.get("VAPID_PRIVATE_KEY")

    if conf_pub and conf_priv:
        _update_cache(conf_pub, conf_priv)
        return conf_pub, conf_priv, subject

    # 2. Redis cache fast path
    cached = frappe.cache().get_value(VAPID_CACHE_KEY)
    if cached and isinstance(cached, dict) and cached.get("public_key") and cached.get("private_key"):
        # Persist these to site_config so next restart doesn't regenerate
        _persist_to_site_config(cached["public_key"], cached["private_key"])
        return cached["public_key"], cached["private_key"], subject

    # 3. Auto-generate and persist immediately
    frappe.logger("vapid").info("[VAPID] Generating new VAPID keypair and persisting to site_config.")
    pub_b64, priv_pem = _generate_vapid_keypair()
    _persist_to_site_config(pub_b64, priv_pem)
    _update_cache(pub_b64, priv_pem)
    return pub_b64, priv_pem, subject


def get_vapid_public_key_string() -> str:
    """Return the VAPID public key string safely for browser Web Push subscription setup.
    The private key is NEVER returned from this module.
    """
    pub_key, _, _ = get_vapid_credentials()
    return pub_key


def ensure_vapid_keys_persisted() -> str:
    """
    Ensure VAPID keys exist in site_config.json.
    Safe to call multiple times — no-op if already persisted.

    Returns
    -------
    str
        The active VAPID public key (b64url).
    """
    conf_pub = frappe.conf.get("vapid_public_key") or frappe.conf.get("VAPID_PUBLIC_KEY")
    conf_priv = frappe.conf.get("vapid_private_key") or frappe.conf.get("VAPID_PRIVATE_KEY")

    if conf_pub and conf_priv:
        frappe.logger("vapid").info(f"[VAPID] Keys already in site_config. prefix={conf_pub[:20]}...")
        return conf_pub

    # Try Redis cache first (preserve existing subscriptions)
    cached = frappe.cache().get_value(VAPID_CACHE_KEY)
    if cached and isinstance(cached, dict) and cached.get("public_key") and cached.get("private_key"):
        pub_b64 = cached["public_key"]
        priv_pem = cached["private_key"]
        frappe.logger("vapid").info(f"[VAPID] Migrating Redis-cached keys to site_config. prefix={pub_b64[:20]}...")
        _persist_to_site_config(pub_b64, priv_pem)
        return pub_b64

    # Generate fresh pair
    pub_b64, priv_pem = _generate_vapid_keypair()
    _persist_to_site_config(pub_b64, priv_pem)
    _update_cache(pub_b64, priv_pem)
    frappe.logger("vapid").info(f"[VAPID] New keypair generated and persisted. prefix={pub_b64[:20]}...")
    return pub_b64


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _generate_vapid_keypair() -> tuple[str, str]:
    """Generate a new VAPID keypair. Returns (public_key_b64url, private_key_pem)."""
    vapid = Vapid()
    vapid.generate_keys()
    pub_bytes = vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    pub_b64 = b64urlencode(pub_bytes)
    priv_pem = vapid.private_key.private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
    ).decode("utf-8")
    return pub_b64, priv_pem


def _persist_to_site_config(pub_b64: str, priv_pem: str) -> None:
    """Write VAPID keys to site_config.json using frappe.installer.update_site_config.
    Survives Redis flushes, container restarts, and bench restarts.
    The private key is stored server-side only.
    """
    try:
        from frappe.installer import update_site_config
        update_site_config("vapid_public_key", pub_b64)
        update_site_config("vapid_private_key", priv_pem)
        frappe.logger("vapid").info("[VAPID] Keys written to site_config.json via update_site_config.")
    except Exception as exc:
        frappe.logger("vapid").error(f"[VAPID] Failed to persist to site_config: {exc}")
        # Non-fatal — Redis cache is still valid for this session.


def _update_cache(pub_b64: str, priv_pem: str) -> None:
    """Store keypair in Redis cache for fast access between requests."""
    try:
        frappe.cache().set_value(VAPID_CACHE_KEY, {
            "public_key": pub_b64,
            "private_key": priv_pem,
        })
    except Exception:
        pass  # Cache failure is non-fatal — site_config is authoritative.
