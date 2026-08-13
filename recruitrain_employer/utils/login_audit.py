# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.utils.login_audit
======================================

Production-grade Login Auditing Module for Employer User.

Architecture & Requirements
----------------------------
1. Backend is the single source of truth (uses ``frappe.utils.now_datetime()``).
2. Hooks into Frappe's ``on_login`` authentication event.
3. Automatically updates ``last_login_at``, ``last_login`` (backward compatibility),
   ``last_login_ip``, ``last_login_user_agent``, and increments ``login_count``.
4. Failed logins do NOT trigger this hook (Frappe raises error before ``on_login``).
5. Guest users are ignored.
6. Administrator or users without an ``Employer User`` mapping are ignored gracefully.
7. Performs updates inside database transaction using atomic SQL increments to prevent race conditions.
"""

from __future__ import annotations

import frappe
from frappe.utils import now_datetime

from recruitrain_employer.utils.constants import DOCTYPE_EMPLOYER_USER


def get_client_ip() -> str | None:
    """Safely extract the requester's IP address from Frappe's request environment.

    Returns
    -------
    str | None
        The client IP address, or None if unavailable.
    """
    try:
        if hasattr(frappe.local, "request_ip") and frappe.local.request_ip:
            return frappe.local.request_ip

        if getattr(frappe, "request", None):
            # Check headers directly for X-Forwarded-For if available
            forwarded = frappe.request.headers.get("X-Forwarded-For")
            if forwarded:
                return forwarded.split(",")[0].strip()
            return getattr(frappe.request, "remote_addr", None)
    except Exception:
        pass
    return None


def get_client_user_agent() -> str | None:
    """Safely extract the requester's HTTP User-Agent string.

    Returns
    -------
    str | None
        The User-Agent string (truncated to 255 chars if needed), or None if unavailable.
    """
    try:
        if getattr(frappe, "request", None) and hasattr(frappe.request, "headers"):
            ua = frappe.request.headers.get("User-Agent")
            if ua:
                return str(ua)[:255]
    except Exception:
        pass
    return None


def get_employer_user_for_user(user: str) -> str | None:
    """Find the Employer User DocType record name associated with a Frappe user ID.

    Parameters
    ----------
    user : str
        Frappe user ID / email (e.g. "user@company.com").

    Returns
    -------
    str | None
        Name of the matching Employer User document, or None if no record exists.
    """
    if not user or user == "Guest":
        return None

    # First attempt: match by 'user' link field
    emp_user = frappe.db.get_value(DOCTYPE_EMPLOYER_USER, {"user": user}, "name")
    if emp_user:
        return emp_user

    # Second attempt: match by document name equal to user (autoname)
    if frappe.db.exists(DOCTYPE_EMPLOYER_USER, user):
        return user

    return None


def record_employer_login(user: str, ip_address: str | None = None, user_agent: str | None = None) -> bool:
    """Atomically record login auditing details for an Employer User inside a transaction.

    Parameters
    ----------
    user : str
        Frappe user ID / email.
    ip_address : str | None, optional
        Client IP address. If None, derived automatically.
    user_agent : str | None, optional
        HTTP User-Agent string. If None, derived automatically.

    Returns
    -------
    bool
        True if audit record was updated, False if skipped (Guest or missing Employer User mapping).
    """
    if not user or user == "Guest":
        return False

    emp_user_name = get_employer_user_for_user(user)
    if not emp_user_name:
        # Requirement 6: Ignore Administrator or non-employer users gracefully
        return False

    if ip_address is None:
        ip_address = get_client_ip()

    if user_agent is None:
        user_agent = get_client_user_agent()

    now = now_datetime()

    # Requirement 3, 7, 8, 13: Atomic SQL update inside transaction to prevent race conditions during concurrent logins.
    frappe.db.sql(
        """
        UPDATE `tabEmployer User`
        SET `last_login_at` = %s,
            `last_login` = %s,
            `last_login_ip` = %s,
            `last_login_user_agent` = %s,
            `login_count` = COALESCE(`login_count`, 0) + 1,
            `modified` = %s
        WHERE `name` = %s
        """,
        (now, now, ip_address, user_agent, now, emp_user_name),
    )

    return True


def on_login_handler(login_manager=None, *args, **kwargs) -> None:
    """Frappe ``on_login`` hook entrypoint.

    Parameters
    ----------
    login_manager : LoginManager, optional
        The Frappe LoginManager instance passed by the hook runner.
    """
    try:
        user = None
        if login_manager and getattr(login_manager, "user", None):
            user = login_manager.user
        if not user:
            user = getattr(frappe.session, "user", None)

        if not user or user == "Guest":
            return

        record_employer_login(user=user)
    except Exception as exc:
        # Authentication should never fail because of an auditing error
        frappe.logger().error(f"Login audit error for user '{user}': {exc}")
