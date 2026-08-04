# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.services.application_service
===================================================

.. deprecated:: 1.0
   Use ``recruitrain_employer.services.job_application_service.JobApplicationService`` instead.

This module is maintained for backward compatibility.
"""

from __future__ import annotations

import warnings
from recruitrain_employer.services.job_application_service import JobApplicationService

warnings.warn(
    "recruitrain_employer.services.application_service is deprecated. Use JobApplicationService instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export JobApplicationService as ApplicationService for legacy consumers
ApplicationService = JobApplicationService
