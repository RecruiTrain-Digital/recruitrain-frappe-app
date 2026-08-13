# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.services.dashboard_service
=================================================

Dashboard Business Logic Service (Compatibility Wrapper).

Delegates all calculation methods to ``AnalyticsService``.
"""

from __future__ import annotations

from typing import Any

from recruitrain_employer.services.analytics_service import AnalyticsService


class DashboardService(AnalyticsService):
    """Compatibility wrapper inheriting all business logic from AnalyticsService."""
    pass
