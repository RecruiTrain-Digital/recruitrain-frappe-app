# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.api.dashboard
=====================================

Dashboard & Analytics API Endpoints.

Architecture
------------
This module is a **thin controller only**.  The following are strictly
prohibited here:

- ``frappe.get_doc()``
- ``frappe.get_all()``
- ``frappe.get_list()``
- ``frappe.db.*``
- Any direct DocType or ORM access

All business logic and database interactions live in ``DashboardService``.

Endpoint Path Prefix
---------------------
/api/method/recruitrain_employer.api.dashboard.<function_name>
"""

import frappe

from recruitrain_employer.services.dashboard_service import DashboardService
from recruitrain_employer.utils.constants import DEFAULT_PAGE, DEFAULT_PAGE_SIZE
from recruitrain_employer.utils.exceptions import ATSException
from recruitrain_employer.utils.response import (
    error_response,
    paginated_response,
    success_response,
)


def _handle_ats_exception(exc: ATSException) -> dict:
    """Translate an ``ATSException`` into a standardised error response dict.

    Parameters
    ----------
    exc : ATSException
        Any exception from the ATS exception hierarchy.

    Returns
    -------
    dict
        A standardised ``error_response`` dict.
    """
    return error_response(
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


# ---------------------------------------------------------------------------
# Overview Widgets
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_overview(company: str | None = None) -> dict:
    """Return top-level KPI metrics for the employer's dashboard.

    Query / Body Parameters
    -----------------------
    company : str (optional)

    Returns
    -------
    dict
        Standardised success response containing KPI metrics.
    """
    try:
        company = company or frappe.form_dict.get("company")
        service = DashboardService()
        data = service.get_overview(company=company)
        return success_response(data=data)
    except ATSException as exc:
        return _handle_ats_exception(exc)
    except Exception as exc:
        return error_response(code="INTERNAL_ERROR", message=str(exc))


@frappe.whitelist()
def get_pipeline_summary(company: str | None = None, job_opening: str | None = None) -> dict:
    """Return application counts grouped by pipeline stage overall and per job.

    Query / Body Parameters
    -----------------------
    company     : str (optional)
    job_opening : str (optional)

    Returns
    -------
    dict
        Standardised success response with pipeline stage distribution.
    """
    try:
        company = company or frappe.form_dict.get("company")
        job_opening = job_opening or frappe.form_dict.get("job_opening")
        service = DashboardService()
        data = service.get_pipeline_summary(company=company, job_opening=job_opening)
        return success_response(data=data)
    except ATSException as exc:
        return _handle_ats_exception(exc)
    except Exception as exc:
        return error_response(code="INTERNAL_ERROR", message=str(exc))


@frappe.whitelist()
def get_hiring_funnel(
    company: str | None = None,
    job_opening: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict:
    """Return funnel conversion rates across the hiring pipeline.

    Query / Body Parameters
    -----------------------
    company     : str (optional)
    job_opening : str (optional)
    from_date   : str (optional; ISO date)
    to_date     : str (optional; ISO date)

    Returns
    -------
    dict
        Standardised success response with hiring funnel data.
    """
    try:
        company = company or frappe.form_dict.get("company")
        job_opening = job_opening or frappe.form_dict.get("job_opening")
        from_date = from_date or frappe.form_dict.get("from_date")
        to_date = to_date or frappe.form_dict.get("to_date")
        service = DashboardService()
        data = service.get_hiring_funnel(
            company=company,
            job_opening=job_opening,
            from_date=from_date,
            to_date=to_date,
        )
        return success_response(data=data)
    except ATSException as exc:
        return _handle_ats_exception(exc)
    except Exception as exc:
        return error_response(code="INTERNAL_ERROR", message=str(exc))


# ---------------------------------------------------------------------------
# Time-Series & Trend Reports
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_applications_over_time(
    company: str | None = None,
    job_opening: str | None = None,
    granularity: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict:
    """Return application submission counts grouped by daily/weekly/monthly periods.

    Query / Body Parameters
    -----------------------
    company     : str (optional)
    job_opening : str (optional)
    granularity : str (optional; daily | weekly | monthly; default monthly)
    from_date   : str (optional; ISO date)
    to_date     : str (optional; ISO date)

    Returns
    -------
    dict
        Standardised success response with time-series data for charting.
    """
    try:
        company = company or frappe.form_dict.get("company")
        job_opening = job_opening or frappe.form_dict.get("job_opening")
        granularity = granularity or frappe.form_dict.get("granularity", "monthly")
        from_date = from_date or frappe.form_dict.get("from_date")
        to_date = to_date or frappe.form_dict.get("to_date")
        service = DashboardService()
        data = service.get_applications_over_time(
            company=company,
            job_opening=job_opening,
            granularity=granularity,
            from_date=from_date,
            to_date=to_date,
        )
        return success_response(data=data)
    except ATSException as exc:
        return _handle_ats_exception(exc)
    except Exception as exc:
        return error_response(code="INTERNAL_ERROR", message=str(exc))


@frappe.whitelist()
def get_time_to_hire(
    company: str | None = None,
    job_opening: str | None = None,
    department: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict:
    """Calculate average time-to-hire statistics.

    Query / Body Parameters
    -----------------------
    company     : str (optional)
    job_opening : str (optional)
    department  : str (optional)
    from_date   : str (optional; ISO date)
    to_date     : str (optional; ISO date)

    Returns
    -------
    dict
        Standardised success response with duration statistics.
    """
    try:
        company = company or frappe.form_dict.get("company")
        job_opening = job_opening or frappe.form_dict.get("job_opening")
        department = department or frappe.form_dict.get("department")
        from_date = from_date or frappe.form_dict.get("from_date")
        to_date = to_date or frappe.form_dict.get("to_date")
        service = DashboardService()
        data = service.get_time_to_hire(
            company=company,
            job_opening=job_opening,
            department=department,
            from_date=from_date,
            to_date=to_date,
        )
        return success_response(data=data)
    except ATSException as exc:
        return _handle_ats_exception(exc)
    except Exception as exc:
        return error_response(code="INTERNAL_ERROR", message=str(exc))


# ---------------------------------------------------------------------------
# Activity Feed
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_recent_activity(
    company: str | None = None,
    entity: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
) -> dict:
    """Return the most recent Activity Log entries across entity types.

    Query / Body Parameters
    -----------------------
    company   : str (optional)
    entity    : str (optional; Candidate | Job Application | Interview | Offer)
    page      : int (default 1)
    page_size : int (default 20)

    Returns
    -------
    dict
        Standardised paginated response with activity entries.
    """
    try:
        company = company or frappe.form_dict.get("company")
        entity = entity or frappe.form_dict.get("entity")
        page = page or int(frappe.form_dict.get("page", DEFAULT_PAGE))
        page_size = page_size or int(frappe.form_dict.get("page_size", DEFAULT_PAGE_SIZE))
        service = DashboardService()
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
    except ATSException as exc:
        return _handle_ats_exception(exc)
    except Exception as exc:
        return error_response(code="INTERNAL_ERROR", message=str(exc))
