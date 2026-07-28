# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.utils
============================

Shared Utility Modules for the RecruiTrain Employer ATS.

This package provides cross-cutting concerns that are used throughout the
application: standardised HTTP response builders, permission helpers,
application-wide constants, and custom exception classes.

Package Layout
--------------
- response.py      Helper functions to build uniform API response dicts
- permissions.py   Role and ownership-based permission check utilities
- constants.py     Application-wide constant values (DocType names, statuses, etc.)
- exceptions.py    Custom exception hierarchy for the ATS domain

Usage
-----
Import utilities directly from their respective submodules::

    from recruitrain_employer.utils.response import success_response, error_response
    from recruitrain_employer.utils.exceptions import ATSValidationError
    from recruitrain_employer.utils.constants import DOCTYPE_JOB_OPENING
    from recruitrain_employer.utils.permissions import require_employer_role
"""
