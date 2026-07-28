# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.validators.offer_validator
=================================================

Input Validation for Offer DocType Payloads.

Validates create and update payloads for Offer records before they
are processed by ``OfferService``.

All validation functions raise ``ATSValidationError`` on failure.
"""

from __future__ import annotations

from recruitrain_employer.utils.constants import (
    OFFER_REQUIRED_FIELDS,
    OFFER_STATUS_DRAFT,
    SUPPORTED_CURRENCIES,
)
from recruitrain_employer.utils.exceptions import ATSValidationError


# ---------------------------------------------------------------------------
# Create Validation
# ---------------------------------------------------------------------------


def validate_create(data: dict) -> None:
    """Validate an Offer create payload.

    Parameters
    ----------
    data : dict
        Raw input data from the API request.

    Raises
    ------
    ATSValidationError
        If required fields are missing or values are invalid.

    Checks Performed
    ----------------
    - Required fields present: application, position, salary, currency, start_date
    - salary is a positive number
    - currency is in SUPPORTED_CURRENCIES
    - expiry_date (if provided) is after today
    - start_date is after today
    - The referenced Job Application exists and is in an offerable state

    TODO: Implement required field presence check against OFFER_REQUIRED_FIELDS
    TODO: Validate salary > 0
    TODO: Validate currency in SUPPORTED_CURRENCIES
    TODO: Validate start_date > today using frappe.utils.getdate()
    TODO: Validate expiry_date > today if provided
    TODO: Check application status allows offer creation
    """
    pass


# ---------------------------------------------------------------------------
# Update Validation
# ---------------------------------------------------------------------------


def validate_update(data: dict, current_doc: dict) -> None:
    """Validate an Offer update payload.

    Parameters
    ----------
    data : dict
        Partial Offer fields from the API request.
    current_doc : dict
        The existing Offer document (for status-based rules).

    Raises
    ------
    ATSValidationError
        If the update violates business rules.

    Checks Performed
    ----------------
    - Current status is OFFER_STATUS_DRAFT (only Draft offers can be edited)
    - Salary is positive (if provided)
    - Currency is in SUPPORTED_CURRENCIES (if provided)
    - Dates are valid (if provided)

    TODO: Check current_doc["status"] == OFFER_STATUS_DRAFT
    TODO: Validate salary and currency if present in data
    TODO: Validate date fields if present in data
    """
    pass


# ---------------------------------------------------------------------------
# Candidate Response Validation
# ---------------------------------------------------------------------------


def validate_candidate_response(response: str) -> None:
    """Validate a candidate's offer response value.

    Parameters
    ----------
    response : str
        The candidate's response: must be ``"Accepted"`` or ``"Rejected"``.

    Raises
    ------
    ATSValidationError
        If the response is not one of the allowed values.

    TODO: Check response in ("Accepted", "Rejected")
    """
    pass
