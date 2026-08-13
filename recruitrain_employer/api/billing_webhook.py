# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.api.billing_webhook
=========================================

REST API Endpoint for Stripe Webhook Callback Notifications.
"""

from __future__ import annotations

import frappe
from recruitrain_employer.services.webhook_service import WebhookService
from recruitrain_employer.utils.response import error_response, success_response


@frappe.whitelist(allow_guest=True)
def stripe_webhook():
    """Receive and process Stripe Webhook Event notifications.

    Supports:
    - invoice.paid
    - invoice.payment_failed
    - customer.subscription.updated
    - customer.subscription.deleted
    - checkout.session.completed
    """
    try:
        payload = {}
        if hasattr(frappe, "request") and frappe.request:
            try:
                payload = frappe.request.get_json() or {}
            except Exception:
                payload = frappe.form_dict or {}
        else:
            payload = frappe.form_dict or {}

        if not payload:
            return error_response(code="VALIDATION_ERROR", message="Empty webhook payload received.", http_status_code=400)

        svc = WebhookService()
        result = svc.handle_webhook_event(payload)

        status_code = result.get("status")
        if status_code == "ignored":
            return success_response(data=result, message=f"Webhook event ignored ({result.get('reason')}).")

        if status_code == "failed":
            return error_response(code="WEBHOOK_FAILED", message=f"Webhook processing failed: {result.get('reason')}", http_status_code=422)

        return success_response(data=result, message="Webhook event processed successfully.")

    except Exception as e:
        frappe.log_error(f"Error in stripe_webhook: {str(e)}")
        return error_response(code="INTERNAL_ERROR", message=str(e), http_status_code=500)
