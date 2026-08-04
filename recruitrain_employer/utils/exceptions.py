# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.utils.exceptions
========================================

Custom Exception Hierarchy for the RecruiTrain Employer ATS.

All service methods and validators raise exceptions from this module so that
the API layer can catch them and translate them into a consistent HTTP error
response using ``recruitrain_employer.utils.response.error_response()``.

Exception Hierarchy
-------------------
::

    ATSException                    (base for all ATS exceptions)
    ├── ATSValidationError          (invalid input / business rule violation)
    ├── ATSNotFoundError            (requested resource does not exist)
    ├── ATSAuthenticationError      (invalid credentials / session)
    ├── ATSPermissionError          (authorisation failure)
    ├── ATSConflictError            (duplicate / state conflict)
    └── ATSServiceError             (unexpected upstream / internal error)

Usage
-----
::

    from recruitrain_employer.utils.exceptions import ATSValidationError

    def validate_salary(salary: float) -> None:
        if salary <= 0:
            raise ATSValidationError(
                "Salary must be a positive number.",
                field="salary"
            )
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Base Exception
# ---------------------------------------------------------------------------


class ATSException(Exception):
    """Base exception for all RecruiTrain ATS domain errors.

    Parameters
    ----------
    message : str
        Human-readable error description.
    code : str, optional
        Machine-readable error code (defaults to the class-level ``code``
        attribute if defined).
    details : Any, optional
        Additional structured context (e.g. field names, conflicting values).
    """

    #: Default machine-readable error code — subclasses should override.
    code: str = "ATS_ERROR"

    def __init__(self, message: str, code: str | None = None, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.__class__.code
        self.details = details

    def to_dict(self) -> dict:
        """Serialise the exception to a dict for use in error_response().

        Returns
        -------
        dict
            ``{ "code": ..., "message": ..., "details": ... }``
        """
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


# ---------------------------------------------------------------------------
# Validation Errors
# ---------------------------------------------------------------------------


class ATSValidationError(ATSException):
    """Raised when input data fails validation rules.

    Use this for:
    - Missing required fields
    - Invalid field formats (email, URL, date)
    - Business rule violations (e.g. salary_min > salary_max)

    Parameters
    ----------
    message : str
        Human-readable validation error description.
    field : str, optional
        The specific field that failed validation.
    details : Any, optional
        Additional context (e.g. a dict of ``{field: [error_messages]}``)
    """

    code = "VALIDATION_ERROR"

    def __init__(self, message: str, field: str | None = None, details: Any = None) -> None:
        super().__init__(message, details=details)
        self.field = field
        if field and not details:
            self.details = {"field": field}


# ---------------------------------------------------------------------------
# Not Found Errors
# ---------------------------------------------------------------------------


class ATSNotFoundError(ATSException):
    """Raised when a requested resource does not exist in the database.

    Use this for:
    - ``frappe.get_doc()`` calls where the document is not found
    - Any lookup by name/ID that returns no results

    Parameters
    ----------
    message : str
        Human-readable description (e.g. ``"Job Opening JOB-0001 not found"``).
    doctype : str, optional
        The DocType that was searched.
    name : str, optional
        The name/ID that was not found.
    details : Any, optional
        Additional context.
    """

    code = "NOT_FOUND"

    def __init__(self, message: str, doctype: str | None = None, name: str | None = None, details: Any = None) -> None:
        super().__init__(message, details=details)
        self.doctype = doctype
        self.name = name
        if doctype and name and not details:
            self.details = {"doctype": doctype, "name": name}


class ATSCompanyNotFoundError(ATSException):
    """Raised when no active company is associated with the authenticated employer user.

    Parameters
    ----------
    message : str
        Human-readable description.
    details : Any, optional
        Additional context.
    """

    code = "COMPANY_NOT_FOUND"

    def __init__(
        self,
        message: str = "No company associated with current authenticated employer user.",
        details: Any = None,
    ) -> None:
        super().__init__(message, code="COMPANY_NOT_FOUND", details=details)


# ---------------------------------------------------------------------------
# Authentication Errors
# ---------------------------------------------------------------------------


class ATSAuthenticationError(ATSException):
    """Raised when an authentication or session operation fails.

    Use this for:
    - Invalid login credentials
    - Expired or invalid tokens (reset token, offer response token)
    - Missing or invalid session when accessing authenticated endpoints

    Parameters
    ----------
    message : str
        Human-readable error description.
    details : Any, optional
        Additional context (avoid including sensitive credential data).
    """

    code = "AUTHENTICATION_ERROR"


# ---------------------------------------------------------------------------
# Permission / Authorization Errors
# ---------------------------------------------------------------------------


class ATSPermissionError(ATSException):
    """Raised when an authenticated user is not authorised to perform an action.

    Use this for:
    - Role-based access violations (e.g. Recruiter attempting an Admin action)
    - Company-scoping violations (user accessing another company's data)
    - Record ownership violations

    Parameters
    ----------
    message : str
        Human-readable permission error description.
    required_role : str, optional
        The role that would have been needed to perform the action.
    details : Any, optional
        Additional context.
    """

    code = "PERMISSION_DENIED"

    def __init__(self, message: str = "You do not have permission to perform this action.", required_role: str | None = None, details: Any = None) -> None:
        super().__init__(message, details=details)
        self.required_role = required_role
        if required_role and not details:
            self.details = {"required_role": required_role}


# ---------------------------------------------------------------------------
# Conflict Errors
# ---------------------------------------------------------------------------


class ATSConflictError(ATSException):
    """Raised when an operation conflicts with the current state of a resource.

    Use this for:
    - Duplicate application detection (same candidate + job)
    - Attempting to publish an already-open job
    - Submitting feedback when feedback already exists for an interviewer

    Parameters
    ----------
    message : str
        Human-readable conflict description.
    details : Any, optional
        Additional context.
    """

    code = "CONFLICT"


# ---------------------------------------------------------------------------
# Service / Internal Errors
# ---------------------------------------------------------------------------


class ATSServiceError(ATSException):
    """Raised for unexpected internal errors or upstream service failures.

    Use this for:
    - Unexpected exceptions caught in service methods
    - External service integration failures (email, PDF generation)
    - Database errors that cannot be classified more specifically

    Parameters
    ----------
    message : str
        Human-readable error description (avoid exposing internal details to
        API consumers — log the full traceback separately).
    details : Any, optional
        Internal context for logging purposes.
    """

    code = "INTERNAL_ERROR"
