# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.validators
================================

Input Validation Layer for the RecruiTrain Employer ATS.

This package provides dedicated validator modules for each major DocType
domain.  Validators are pure Python functions (or lightweight classes) that
validate raw input data dictionaries **before** they are passed to service
methods or saved to the database.

Package Layout
--------------
- candidate_validator.py    Validates Candidate profile create/update payloads
- company_validator.py      Validates Company create/update payloads
- job_validator.py          Validates Job Opening create/update payloads
- application_validator.py  Validates Job Application create payloads
- interview_validator.py    Validates Interview schedule and feedback payloads
- offer_validator.py        Validates Offer create/update payloads
- notification_validator.py Validates Notification create and preference payloads
- settings_validator.py     Validates all Employer Settings groups (general, branding,
                            notification, security, recruitment, integration, audit)

Design Principles
-----------------
1. All validators MUST raise ``ATSValidationError`` (from
   ``recruitrain_employer.utils.exceptions``) on failure — never raw
   ``frappe.exceptions.ValidationError`` — so the API error handler can
   produce a consistent response format.
2. Validators SHOULD be called at the **beginning** of each service method,
   before any database interaction.
3. Validators MUST NOT perform database reads unless absolutely necessary
   (uniqueness checks are acceptable; complex joins are not).
4. Validators SHOULD be unit-testable without a running Frappe instance.
"""
