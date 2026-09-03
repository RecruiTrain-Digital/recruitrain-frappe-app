# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.api.billing
==================================

Authoritative Backend REST API Endpoints for Billing, Subscriptions, Checkout, and Webhook Processing.
"""

from __future__ import annotations

import frappe
from recruitrain_employer.services.subscription_service import SubscriptionService
from recruitrain_employer.services.stripe_service import StripeService
from recruitrain_employer.services.webhook_service import WebhookService
from recruitrain_employer.utils.permissions import employer_required, get_current_company
from recruitrain_employer.utils.exceptions import ATSException, ATSValidationError, ATSNotFoundError
from recruitrain_employer.utils.response import error_response, success_response


def _get_company_context() -> str:
    """Helper to extract active company for current request context using canonical permission layer."""
    company = getattr(frappe.flags, "employer_company", None)
    if company:
        return company
    return get_current_company()


@frappe.whitelist()
@employer_required
def get_subscription_plans():
    """Return all active subscription plans available for subscription or upgrade."""
    try:
        svc = SubscriptionService()
        plans = svc.get_available_plans()
        return success_response(data=plans, message="Subscription plans retrieved successfully.")
    except ATSException as e:
        return error_response(code=e.code, message=e.message, details=e.details)
    except Exception as e:
        frappe.log_error(f"Error in get_subscription_plans: {str(e)}")
        return error_response(code="INTERNAL_ERROR", message=str(e), http_status_code=500)


@frappe.whitelist()
@employer_required
def get_current_subscription():
    """Return current subscription state and entitlements for the authenticated company."""
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
def get_subscription_usage():
    """Return current resource consumption counters and plan limits for authenticated company."""
    try:
        company = _get_company_context()
        svc = SubscriptionService()
        usage = svc.get_usage_with_limits(company)
        return success_response(data=usage, message="Subscription usage retrieved successfully.")
    except ATSException as e:
        return error_response(code=e.code, message=e.message, details=e.details)
    except Exception as e:
        frappe.log_error(f"Error in get_subscription_usage: {str(e)}")
        return error_response(code="INTERNAL_ERROR", message=str(e), http_status_code=500)


@frappe.whitelist()
@employer_required
def get_billing_transactions():
    """Return billing transactions and invoice history for the authenticated company."""
    try:
        company = _get_company_context()
        svc = SubscriptionService()
        txns = svc.get_invoices(company)
        return success_response(data=txns, message="Billing transactions retrieved successfully.")
    except ATSException as e:
        return error_response(code=e.code, message=e.message, details=e.details)
    except Exception as e:
        frappe.log_error(f"Error in get_billing_transactions: {str(e)}")
        return error_response(code="INTERNAL_ERROR", message=str(e), http_status_code=500)


@frappe.whitelist()
@employer_required
def get_billing_summary():
    """Return consolidated billing overview for authenticated company."""
    try:
        company = _get_company_context()
        svc = SubscriptionService()
        summary = svc.get_billing_overview(company)
        return success_response(data=summary, message="Billing summary retrieved successfully.")
    except ATSException as e:
        return error_response(code=e.code, message=e.message, details=e.details)
    except Exception as e:
        frappe.log_error(f"Error in get_billing_summary: {str(e)}")
        return error_response(code="INTERNAL_ERROR", message=str(e), http_status_code=500)


@frappe.whitelist()
@employer_required
def create_checkout_session():
    """Create a Stripe Checkout Session for plan upgrade or subscription purchase.

    Server-side authoritative pricing strictly derived from Subscription_Plan_Recruitrain record.
    Company is strictly resolved from authenticated session.
    """
    try:
        params = frappe.request.get_json() if frappe.request and frappe.request.get_json() else frappe.form_dict
        if not isinstance(params, dict):
            params = {}

        plan_id = params.get("plan_id") or params.get("plan_name") or params.get("plan")
        billing_interval = (params.get("billing_interval") or params.get("interval") or "monthly").lower()

        if not plan_id:
            return error_response(code="VALIDATION_ERROR", message="Parameter 'plan_id' is required.", http_status_code=400)

        if billing_interval not in ("monthly", "yearly"):
            return error_response(code="INVALID_INTERVAL", message="Parameter 'billing_interval' must be 'monthly' or 'yearly'.", http_status_code=400)

        company = _get_company_context()

        # Resolve plan doc from MariaDB
        from recruitrain_employer.utils.constants import DOCTYPE_SUBSCRIPTION_PLAN
        plan_name = None
        if plan_id:
            if frappe.db.exists(DOCTYPE_SUBSCRIPTION_PLAN, plan_id):
                plan_name = plan_id
            else:
                try:
                    plan_name = frappe.db.get_value(DOCTYPE_SUBSCRIPTION_PLAN, {"plan_code": plan_id}, "name")
                except Exception:
                    plan_name = None
                if not plan_name:
                    try:
                        plan_name = frappe.db.get_value(DOCTYPE_SUBSCRIPTION_PLAN, {"plan_name": plan_id}, "name")
                    except Exception:
                        plan_name = None

        if not plan_name:
            return error_response(code="PLAN_NOT_FOUND", message=f"Subscription plan '{plan_id}' does not exist.", http_status_code=404)

        plan_doc = frappe.get_doc(DOCTYPE_SUBSCRIPTION_PLAN, plan_name)
        if getattr(plan_doc, "is_active", 1) == 0:
            return error_response(code="PLAN_INACTIVE", message=f"Subscription plan '{plan_doc.plan_name}' is inactive.", http_status_code=400)

        success_url = params.get("success_url")
        cancel_url = params.get("cancel_url")

        stripe_svc = StripeService()
        session_info = stripe_svc.create_checkout_session(
            company=company,
            plan_doc=plan_doc,
            billing_interval=billing_interval,
            success_url=success_url,
            cancel_url=cancel_url,
        )

        return success_response(data=session_info, message="Checkout session created successfully.")

    except ATSException as e:
        return error_response(code=e.code, message=e.message, details=e.details)
    except Exception as e:
        frappe.log_error(f"Error in create_checkout_session: {str(e)}")
        return error_response(code="INTERNAL_ERROR", message=str(e), http_status_code=500)


@frappe.whitelist()
@employer_required
def cancel_subscription():
    """Cancel subscription for authenticated company."""
    try:
        params = frappe.request.get_json() if frappe.request and frappe.request.get_json() else frappe.form_dict
        at_period_end = True
        if isinstance(params, dict) and "at_period_end" in params:
            at_period_end = bool(params.get("at_period_end"))

        company = _get_company_context()
        svc = SubscriptionService()
        result = svc.cancel_subscription(company, at_period_end=at_period_end)
        return success_response(data=result, message="Subscription cancellation requested.")
    except ATSException as e:
        return error_response(code=e.code, message=e.message, details=e.details)
    except Exception as e:
        frappe.log_error(f"Error in cancel_subscription: {str(e)}")
        return error_response(code="INTERNAL_ERROR", message=str(e), http_status_code=500)


@frappe.whitelist()
@employer_required
def resume_subscription():
    """Resume a pending cancelled subscription for authenticated company."""
    try:
        company = _get_company_context()
        svc = SubscriptionService()
        result = svc.resume_subscription(company)
        return success_response(data=result, message="Subscription resumed successfully.")
    except ATSException as e:
        return error_response(code=e.code, message=e.message, details=e.details)
    except Exception as e:
        frappe.log_error(f"Error in resume_subscription: {str(e)}")
        return error_response(code="INTERNAL_ERROR", message=str(e), http_status_code=500)


@frappe.whitelist(allow_guest=True)
def stripe_webhook():
    """Receive and process verified Stripe Webhook event notifications."""
    try:
        raw_body = b""
        sig_header = None

        if hasattr(frappe, "request") and frappe.request:
            raw_body = frappe.request.get_data()
            sig_header = frappe.request.headers.get("Stripe-Signature")
        else:
            payload = frappe.form_dict or {}
            import json
            raw_body = json.dumps(payload).encode("utf-8")

        svc = WebhookService()
        result = svc.process_raw_webhook(raw_body, sig_header)

        status_code = result.get("status")
        if status_code == "ignored":
            return success_response(data=result, message=f"Webhook event ignored ({result.get('reason')}).")

        if status_code == "failed":
            http_code = 400 if result.get("code") == "INVALID_SIGNATURE" else 422
            return error_response(code=result.get("code", "WEBHOOK_FAILED"), message=f"Webhook processing failed: {result.get('reason')}", http_status_code=http_code)

        return success_response(data=result, message="Webhook event processed successfully.")

    except Exception as e:
        frappe.log_error(f"Error in stripe_webhook: {str(e)}")
        return error_response(code="INTERNAL_ERROR", message=str(e), http_status_code=500)
