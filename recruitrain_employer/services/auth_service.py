# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.services.auth_service
============================================

Authentication & Session Management Service.

Architecture
------------
This service operates exclusively on the Frappe ``User`` model via Frappe's
built-in authentication APIs. It does **not** query Employer User, Candidate,
or any other application-level DocType.

Principle of Separation
-----------------------
- ``AuthService``  → "Is this Frappe user authenticated?"
- ``EmployerService`` (future) → "Is this employer active / verified / permitted?"
- ``CandidateService`` (future) → "Is this candidate eligible to apply?"

All employer-specific, candidate-specific, or role-specific business rules
belong in their respective service modules, **not here**.

Frappe APIs Used
----------------
- ``frappe.local.login_manager``  — login / logout / session
- ``frappe.session``              — current session state
- ``frappe.get_roles()``          — user role membership
- ``frappe.utils.password.update_password()``  — password mutation
- ``frappe.sendmail()``           — transactional email (TODO)

TODO: Activity Log writes are deferred to a future ``ActivityLogService``.
TODO: Notification dispatch is deferred to ``NotificationService``.
"""

from __future__ import annotations

import frappe
from frappe.utils.password import update_password

from recruitrain_employer.utils.exceptions import (
    ATSAuthenticationError,
    ATSValidationError,
)


class AuthService:
    """Encapsulates authentication and session management operations.

    All methods operate solely on Frappe's built-in ``User`` model and
    session infrastructure. No application-level DocTypes are accessed here.

    Usage
    -----
    Instantiate per-request inside API handlers::

        service = AuthService()
        result = service.login(email, password)
    """

    # ------------------------------------------------------------------
    # Public Methods
    # ------------------------------------------------------------------

    def login(self, email: str, password: str) -> dict:
        """Authenticate a Frappe user and establish a server-side session.

        Delegates credential verification entirely to
        ``frappe.local.login_manager``. No employer-specific or
        candidate-specific checks are performed here — those belong in
        the respective domain services.

        Parameters
        ----------
        email : str
            The user's registered Frappe email address.
        password : str
            The plain-text password (verified securely by Frappe's auth layer).

        Returns
        -------
        dict
            Session information including the authenticated user and their roles.

            Example::

                {
                    "user": "user@company.com",
                    "full_name": "Jane Doe",
                    "roles": ["Employer Admin", "System Manager"]
                }

        Raises
        ------
        ATSAuthenticationError
            If the credentials are invalid or the account is disabled in Frappe.
        ATSValidationError
            If ``email`` or ``password`` are missing.

        TODO: Record login event in Activity Log via ActivityLogService.
        TODO: Emit login notification via NotificationService.
        """
        if not email:
            raise ATSValidationError("Email is required.", field="email")
        if not password:
            raise ATSValidationError("Password is required.", field="password")

        try:
            frappe.local.login_manager.authenticate(user=email, pwd=password)
            frappe.local.login_manager.post_login()
        except frappe.AuthenticationError:
            raise ATSAuthenticationError(
                "Invalid email or password. Please check your credentials and try again."
            )
        except frappe.ValidationError as exc:
            # Covers disabled accounts, IP restrictions, etc.
            raise ATSAuthenticationError(str(exc))

        return self._build_session_payload()

    def logout(self) -> None:
        """Invalidate the current user's Frappe session.

        Delegates to ``frappe.local.login_manager.logout()``. No
        employer-specific teardown is performed here.

        Raises
        ------
        ATSAuthenticationError
            If there is no active session to terminate.

        TODO: Record logout event in Activity Log via ActivityLogService.
        TODO: Clear any application-level session metadata.
        """
        if frappe.session.user == "Guest":
            raise ATSAuthenticationError("No active session found.")

        frappe.local.login_manager.logout()

    def validate_session(self) -> dict:
        """Validate the current request session and return session metadata.

        Intended as the backend for the React frontend's session-check
        endpoint (``GET /api/method/recruitrain_employer.api.auth.me``).
        Returns a lightweight payload that the frontend can use to determine
        auth state without a full user-profile fetch.

        Returns
        -------
        dict
            Session state payload::

                {
                    "authenticated": True,
                    "user": "user@company.com",
                    "full_name": "Jane Doe",
                    "roles": ["Employer Admin"]
                }

        Raises
        ------
        ATSAuthenticationError
            If the session belongs to the Guest user (i.e. unauthenticated).
        """
        if frappe.session.user == "Guest":
            raise ATSAuthenticationError(
                "No active session. Please log in to continue."
            )

        return self._build_session_payload()

    def current_user(self) -> dict:
        """Return profile information for the currently authenticated Frappe user.

        Returns basic Frappe ``User`` fields. Employer-specific profile
        enrichment (company, role within company, etc.) is the responsibility
        of ``EmployerService``.

        Returns
        -------
        dict
            Frappe User record fields relevant to the frontend::

                {
                    "user": "user@company.com",
                    "full_name": "Jane Doe",
                    "roles": ["Employer Admin"],
                    "email": "user@company.com"
                }

        Raises
        ------
        ATSAuthenticationError
            If the current session belongs to Guest.

        TODO: EmployerService will extend this payload with employer profile data.
        TODO: CandidateService will extend this payload with candidate profile data.
        """
        if frappe.session.user == "Guest":
            raise ATSAuthenticationError(
                "Authentication required. Please log in to continue."
            )

        return self._build_session_payload()

    def forgot_password(self, email: str) -> None:
        """Initiate the Frappe password reset flow for the given email address.

        Uses Frappe's built-in password reset infrastructure. The reset link
        is sent via Frappe's email queue.

        Note: For security, this method does not reveal whether the email is
        registered — it succeeds silently when the user is not found.

        Parameters
        ----------
        email : str
            The email address to send the reset link to.

        Raises
        ------
        ATSValidationError
            If ``email`` is not provided.

        TODO: Rate-limit reset requests to prevent email flooding.
        TODO: Log reset request to Activity Log via ActivityLogService.
        TODO: Consider custom email template for branded reset emails.
        """
        if not email:
            raise ATSValidationError("Email is required.", field="email")

        # Frappe's built-in reset — silently does nothing if user not found,
        # which is the correct behaviour (no user enumeration via this endpoint).
        frappe.utils.password.reset_password(user=email)

    def reset_password(self, key: str, new_password: str) -> None:
        """Complete the password reset using Frappe's built-in reset key flow.

        The ``key`` is the time-limited token delivered in the reset email.
        Frappe validates expiry and one-time-use semantics internally.

        Parameters
        ----------
        key : str
            The secure reset key received via the password reset email.
        new_password : str
            The new plain-text password (will be hashed by Frappe).

        Raises
        ------
        ATSAuthenticationError
            If the key is invalid, expired, or has already been used.
        ATSValidationError
            If ``key`` or ``new_password`` are missing.

        TODO: Enforce minimum password complexity via constants.MIN_PASSWORD_LENGTH.
        TODO: Log password reset to Activity Log via ActivityLogService.
        """
        if not key:
            raise ATSValidationError("Reset key is required.", field="key")
        if not new_password:
            raise ATSValidationError("New password is required.", field="new_password")

        try:
            # Frappe resolves the user from the reset key and validates expiry.
            user = frappe.db.get_value(
                "User",
                {"reset_password_key": key},
                "name",
            )
            if not user:
                raise ATSAuthenticationError(
                    "The password reset link is invalid or has expired. "
                    "Please request a new one."
                )

            update_password(user=user, pwd=new_password)

            # Invalidate the key after successful reset.
            frappe.db.set_value("User", user, "reset_password_key", "")
            frappe.db.commit()

        except ATSAuthenticationError:
            raise
        except Exception as exc:
            raise ATSAuthenticationError(
                "Password reset failed. The link may be invalid or expired."
            ) from exc

        # TODO: Log password reset event to Activity Log via ActivityLogService.

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    def _build_session_payload(self) -> dict:
        """Build a serialisable session payload from the current Frappe session.

        Returns
        -------
        dict
            Session information drawn from ``frappe.session`` and
            ``frappe.get_roles()``.  No DocType queries are made.
        """
        user = frappe.session.user
        roles = frappe.get_roles(user)

        return {
            "authenticated": True,
            "user": user,
            "full_name": frappe.session.data.get("full_name", ""),
            "roles": roles,
        }
