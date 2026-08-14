# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.api.analytics
====================================

Analytics & Reporting API Endpoints.

Architecture
------------
Thin controller layer only. Business logic, company scoping, date validation,
and aggregations live exclusively in ``AnalyticsService``.

Endpoint Path Prefix
---------------------
/api/method/recruitrain_employer.api.analytics.<function_name>
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
        message="An internal server error occurred while processing analytics request.",
        details={"error": str(exc)},
        http_status_code=500,
    )


@frappe.whitelist()
@employer_required
def get_analytics(
    company: str | None = None,
    job_opening: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict:
    """Return unified aggregate analytics payload covering all dashboard metrics."""
    try:
        company_val = company or frappe.form_dict.get("company")
        job_val = job_opening or frappe.form_dict.get("job_opening")
        from_val = from_date or frappe.form_dict.get("from_date")
        to_val = to_date or frappe.form_dict.get("to_date")

        service = AnalyticsService()
        data = service.get_analytics(
            company=company_val,
            job_opening=job_val,
            from_date=from_val,
            to_date=to_val,
        )
        return success_response(data=data)
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def get_overview(
    company: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict:
    """Return top-level KPI overview metrics for the employer's company."""
    try:
        company_val = company or frappe.form_dict.get("company")
        from_val = from_date or frappe.form_dict.get("from_date")
        to_val = to_date or frappe.form_dict.get("to_date")

        service = AnalyticsService()
        data = service.get_overview(
            company=company_val,
            from_date=from_val,
            to_date=to_val,
        )
        return success_response(data=data)
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def get_funnel(
    company: str | None = None,
    job_opening: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict:
    """Return recruitment funnel breakdown and stage conversion rates."""
    try:
        company_val = company or frappe.form_dict.get("company")
        job_val = job_opening or frappe.form_dict.get("job_opening")
        from_val = from_date or frappe.form_dict.get("from_date")
        to_val = to_date or frappe.form_dict.get("to_date")

        service = AnalyticsService()
        data = service.get_funnel(
            company=company_val,
            job_opening=job_val,
            from_date=from_val,
            to_date=to_val,
        )
        return success_response(data=data)
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def get_trends(
    company: str | None = None,
    job_opening: str | None = None,
    granularity: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict:
    """Return time-series application trends grouped by daily/weekly/monthly periods."""
    try:
        company_val = company or frappe.form_dict.get("company")
        job_val = job_opening or frappe.form_dict.get("job_opening")
        gran_val = granularity or frappe.form_dict.get("granularity", "monthly")
        from_val = from_date or frappe.form_dict.get("from_date")
        to_val = to_date or frappe.form_dict.get("to_date")

        service = AnalyticsService()
        data = service.get_trends(
            company=company_val,
            job_opening=job_val,
            granularity=gran_val,
            from_date=from_val,
            to_date=to_val,
        )
        return success_response(data=data)
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def get_job_metrics(
    company: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict:
    """Return job opening performance metrics and applications-per-job breakdown."""
    try:
        company_val = company or frappe.form_dict.get("company")
        from_val = from_date or frappe.form_dict.get("from_date")
        to_val = to_date or frappe.form_dict.get("to_date")

        service = AnalyticsService()
        data = service.get_job_metrics(
            company=company_val,
            from_date=from_val,
            to_date=to_val,
        )
        return success_response(data=data)
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def get_application_metrics(
    company: str | None = None,
    job_opening: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict:
    """Return job application metrics grouped by status, stage, source, priority."""
    try:
        company_val = company or frappe.form_dict.get("company")
        job_val = job_opening or frappe.form_dict.get("job_opening")
        from_val = from_date or frappe.form_dict.get("from_date")
        to_val = to_date or frappe.form_dict.get("to_date")

        service = AnalyticsService()
        data = service.get_application_metrics(
            company=company_val,
            job_opening=job_val,
            from_date=from_val,
            to_date=to_val,
        )
        return success_response(data=data)
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def get_interview_metrics(
    company: str | None = None,
    job_opening: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict:
    """Return interview metrics grouped by status, type, and result."""
    try:
        company_val = company or frappe.form_dict.get("company")
        job_val = job_opening or frappe.form_dict.get("job_opening")
        from_val = from_date or frappe.form_dict.get("from_date")
        to_val = to_date or frappe.form_dict.get("to_date")

        service = AnalyticsService()
        data = service.get_interview_metrics(
            company=company_val,
            job_opening=job_val,
            from_date=from_val,
            to_date=to_val,
        )
        return success_response(data=data)
    except Exception as exc:
        return _handle_ats_exception(exc)


@frappe.whitelist()
@employer_required
def get_offer_metrics(
    company: str | None = None,
    job_opening: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict:
    """Return offer status distribution, acceptance rate, and salary totals."""
    try:
        company_val = company or frappe.form_dict.get("company")
        job_val = job_opening or frappe.form_dict.get("job_opening")
        from_val = from_date or frappe.form_dict.get("from_date")
        to_val = to_date or frappe.form_dict.get("to_date")

        service = AnalyticsService()
        data = service.get_offer_metrics(
            company=company_val,
            job_opening=job_val,
            from_date=from_val,
            to_date=to_val,
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
    """Calculate average time-to-hire in days."""
    try:
        company_val = company or frappe.form_dict.get("company")
        job_val = job_opening or frappe.form_dict.get("job_opening")
        dept_val = department or frappe.form_dict.get("department")
        from_val = from_date or frappe.form_dict.get("from_date")
        to_val = to_date or frappe.form_dict.get("to_date")

        service = AnalyticsService()
        data = service.get_time_to_hire(
            company=company_val,
            job_opening=job_val,
            department=dept_val,
            from_date=from_val,
            to_date=to_val,
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
    """Return paginated recent activity feed entries across entity types."""
    try:
        company_val = company or frappe.form_dict.get("company")
        entity_val = entity or frappe.form_dict.get("entity")
        page_val = page or int(frappe.form_dict.get("page", DEFAULT_PAGE))
        size_val = page_size or int(frappe.form_dict.get("page_size", DEFAULT_PAGE_SIZE))

        service = AnalyticsService()
        res = service.get_recent_activity(
            company=company_val,
            entity=entity_val,
            page=page_val,
            page_size=size_val,
        )
        return paginated_response(
            data=res["data"],
            page=res["page"],
            page_size=res["page_size"],
            total=res["total"],
        )
    except Exception as exc:
        return _handle_ats_exception(exc)
