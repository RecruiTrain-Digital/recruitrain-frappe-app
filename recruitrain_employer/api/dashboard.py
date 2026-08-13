# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.api.dashboard
=====================================

Dashboard & Analytics API Endpoints (Compatibility Module).

Thin controller delegating exclusively to ``AnalyticsService``.
"""

from __future__ import annotations

import frappe

from recruitrain_employer.services.analytics_service import AnalyticsService
from recruitrain_employer.utils.constants import DEFAULT_PAGE, DEFAULT_PAGE_SIZE
from recruitrain_employer.utils.exceptions import ATSException
from recruitrain_employer.utils.permissions import employer_required
from recruitrain_employer.utils.response import (
    error_response,
    paginated_response,
    success_response,
)


def _handle_ats_exception(exc: Exception) -> dict:
    """Translate an ATSException or generic Exception into standard response envelope."""
    if isinstance(exc, ATSException):
        http_code = (
            400 if exc.code == "VALIDATION_ERROR"
            else 403 if exc.code == "PERMISSION_DENIED"
            else 404 if exc.code == "NOT_FOUND"
            else 409 if exc.code == "CONFLICT"
            else 400
        )
        return error_response(
            code=exc.code,
            message=exc.message,
            details=exc.details,
            http_status_code=http_code,
        )

    return error_response(
        code="INTERNAL_SERVER_ERROR",
        message="An internal server error occurred while processing dashboard request.",
        details={"error": str(exc)},
        http_status_code=500,
    )


@frappe.whitelist()
@employer_required
def get_overview(company: str | None = None) -> dict:
    """Return top-level KPI metrics for the employer's dashboard."""
    try:
        company = company or frappe.form_dict.get("company")
        service = AnalyticsService()
        data = service.get_overview(company=company)
        return success_response(data=data)
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def get_pipeline_summary(company: str | None = None, job_opening: str | None = None) -> dict:
    """Return application counts grouped by pipeline stage overall and per job."""
    try:
        company = company or frappe.form_dict.get("company")
        job_opening = job_opening or frappe.form_dict.get("job_opening")
        service = AnalyticsService()
        data = service.get_funnel(company=company, job_opening=job_opening)
        return success_response(data=data)
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def get_hiring_funnel(
    company: str | None = None,
    job_opening: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict:
    """Return funnel conversion rates across the hiring pipeline."""
    try:
        company = company or frappe.form_dict.get("company")
        job_opening = job_opening or frappe.form_dict.get("job_opening")
        from_date = from_date or frappe.form_dict.get("from_date")
        to_date = to_date or frappe.form_dict.get("to_date")
        service = AnalyticsService()
        data = service.get_funnel(
            company=company,
            job_opening=job_opening,
            from_date=from_date,
            to_date=to_date,
        )
        return success_response(data=data)
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def get_applications_over_time(
    company: str | None = None,
    job_opening: str | None = None,
    granularity: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict:
    """Return application submission counts grouped by daily/weekly/monthly periods."""
    try:
        company = company or frappe.form_dict.get("company")
        job_opening = job_opening or frappe.form_dict.get("job_opening")
        granularity = granularity or frappe.form_dict.get("granularity", "monthly")
        from_date = from_date or frappe.form_dict.get("from_date")
        to_date = to_date or frappe.form_dict.get("to_date")
        service = AnalyticsService()
        data = service.get_trends(
            company=company,
            job_opening=job_opening,
            granularity=granularity,
            from_date=from_date,
            to_date=to_date,
        )
        return success_response(data=data)
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def get_time_to_hire(
    company: str | None = None,
    job_opening: str | None = None,
    department: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict:
    """Calculate average time-to-hire statistics."""
    try:
        company = company or frappe.form_dict.get("company")
        job_opening = job_opening or frappe.form_dict.get("job_opening")
        department = department or frappe.form_dict.get("department")
        from_date = from_date or frappe.form_dict.get("from_date")
        to_date = to_date or frappe.form_dict.get("to_date")
        service = AnalyticsService()
        data = service.get_time_to_hire(
            company=company,
            job_opening=job_opening,
            department=department,
            from_date=from_date,
            to_date=to_date,
        )
        return success_response(data=data)
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def get_recent_activity(
    company: str | None = None,
    entity: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
) -> dict:
    """Return the most recent Activity Log entries across entity types."""
    try:
        company = company or frappe.form_dict.get("company")
        entity = entity or frappe.form_dict.get("entity")
        page = page or int(frappe.form_dict.get("page", DEFAULT_PAGE))
        page_size = page_size or int(frappe.form_dict.get("page_size", DEFAULT_PAGE_SIZE))
        service = AnalyticsService()
        res = service.get_recent_activity(
            company=company,
            entity=entity,
            page=page,
            page_size=page_size,
        )
        return paginated_response(
            data=res["data"],
            page=res["page"],
            page_size=res["page_size"],
            total=res["total"],
        )
    except Exception as exc:
        return _handle_ats_exception(exc)
