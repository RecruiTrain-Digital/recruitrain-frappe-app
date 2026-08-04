# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.validators.application_validator
======================================================

.. deprecated:: 1.0
   Use ``recruitrain_employer.validators.job_application_validator.JobApplicationValidator`` instead.

This module is maintained for backward compatibility.
"""

from __future__ import annotations

import warnings
from recruitrain_employer.validators.job_application_validator import JobApplicationValidator

warnings.warn(
    "recruitrain_employer.validators.application_validator is deprecated. Use JobApplicationValidator instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export JobApplicationValidator as ApplicationValidator for legacy consumers
ApplicationValidator = JobApplicationValidator
