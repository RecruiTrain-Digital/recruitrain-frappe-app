# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.api.subscription
========================================

REST API Endpoints for Subscription, Usage, and Plan Entitlements.
"""

from __future__ import annotations

import frappe
from recruitrain_employer.services.subscription_service import SubscriptionService
from recruitrain_employer.utils.permissions import employer_required
from recruitrain_employer.utils.exceptions import ATSException
from recruitrain_employer.utils.response import error_response, success_response


def _get_company_context() -> str:
    """Helper to extract active company for current request context using canonical permission layer."""
    company = getattr(frappe.flags, "employer_company", None)
    if company:
        return company
    from recruitrain_employer.utils.permissions import get_current_company
    return get_current_company()


@frappe.whitelist()
@employer_required
def get_current_subscription():
    """Return the active subscription details for the authenticated company."""
    try:
        company = _get_company_context()
        svc = SubscriptionService()
        sub = svc.get_usage_with_limits(company)
        return success_response(data=sub, message="Current subscription retrieved successfully.")
    except ATSException as e:
        return error_response(code=e.code, message=e.message, details=e.details)
    except Exception as e:
        frappe.log_error(f"Error in get_current_subscription: {str(e)}")
        return error_response(code="INTERNAL_ERROR", message=str(e), http_status_code=500)


@frappe.whitelist()
@employer_required
def get_usage():
    """Return usage counters and plan limits for the authenticated company."""
    try:
        company = _get_company_context()
        svc = SubscriptionService()
        usage = svc.get_usage_with_limits(company)
        return success_response(data=usage, message="Subscription usage retrieved successfully.")
    except ATSException as e:
        return error_response(code=e.code, message=e.message, details=e.details)
    except Exception as e:
        frappe.log_error(f"Error in get_usage: {str(e)}")
        return error_response(code="INTERNAL_ERROR", message=str(e), http_status_code=500)


@frappe.whitelist()
@employer_required
def get_available_plans():
    """Return all active subscription plans available for subscription or upgrade."""
    try:
        svc = SubscriptionService()
        plans = svc.get_available_plans()
        return success_response(data=plans, message="Available subscription plans retrieved successfully.")
    except ATSException as e:
        return error_response(code=e.code, message=e.message, details=e.details)
    except Exception as e:
        frappe.log_error(f"Error in get_available_plans: {str(e)}")
        return error_response(code="INTERNAL_ERROR", message=str(e), http_status_code=500)


@frappe.whitelist()
@employer_required
def upgrade_preview():
    """Preview limits, price diff, and downgrade warnings for upgrading/switching plans."""
    try:
        params = frappe.request.get_json() if frappe.request and frappe.request.get_json() else frappe.form_dict
        new_plan_name = params.get("new_plan_name") or params.get("plan_name") or params.get("target_plan")

        if not new_plan_name:
            return error_response(code="VALIDATION_ERROR", message="Parameter 'new_plan_name' is required.")

        company = _get_company_context()
        svc = SubscriptionService()
        preview = svc.preview_upgrade(company, new_plan_name)
        return success_response(data=preview, message="Upgrade preview generated successfully.")
    except ATSException as e:
        return error_response(code=e.code, message=e.message, details=e.details)
    except Exception as e:
        frappe.log_error(f"Error in upgrade_preview: {str(e)}")
        return error_response(code="INTERNAL_ERROR", message=str(e), http_status_code=500)


@frappe.whitelist()
@employer_required
def get_billing_overview():
    """Return consolidated billing overview for the authenticated company."""
    try:
        company = _get_company_context()
        svc = SubscriptionService()
        overview = svc.get_billing_overview(company)
        return success_response(data=overview, message="Billing overview retrieved successfully.")
    except ATSException as e:
        return error_response(code=e.code, message=e.message, details=e.details)
    except Exception as e:
        frappe.log_error(f"Error in get_billing_overview: {str(e)}")
        return error_response(code="INTERNAL_ERROR", message=str(e), http_status_code=500)


@frappe.whitelist()
@employer_required
def get_invoices():
    """Return billing invoices for the authenticated company."""
    try:
        company = _get_company_context()
        svc = SubscriptionService()
        invoices = svc.get_invoices(company)
        return success_response(data=invoices, message="Invoices retrieved successfully.")
    except ATSException as e:
        return error_response(code=e.code, message=e.message, details=e.details)
    except Exception as e:
        frappe.log_error(f"Error in get_invoices: {str(e)}")
        return error_response(code="INTERNAL_ERROR", message=str(e), http_status_code=500)


@frappe.whitelist()
@employer_required
def get_payment_history():
    """Return payment transaction history for the authenticated company."""
    try:
        company = _get_company_context()
        svc = SubscriptionService()
        history = svc.get_payment_history(company)
        return success_response(data=history, message="Payment history retrieved successfully.")
    except ATSException as e:
        return error_response(code=e.code, message=e.message, details=e.details)
    except Exception as e:
        frappe.log_error(f"Error in get_payment_history: {str(e)}")
        return error_response(code="INTERNAL_ERROR", message=str(e), http_status_code=500)

