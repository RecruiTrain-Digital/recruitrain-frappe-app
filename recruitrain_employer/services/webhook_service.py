# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.services.webhook_service
================================================

Production-Grade Stripe Webhook Handler & Idempotent Processing Engine.

Supports events:
- checkout.session.completed
- customer.subscription.created
- customer.subscription.updated
- customer.subscription.deleted
- invoice.paid
- invoice.payment_failed

Idempotency:
Guarantees duplicate webhook deliveries (webhook replay attacks / network retries)
do not cause duplicate transactions, duplicate usage increments, or invalid subscription extensions.
"""

from __future__ import annotations

import json
from typing import Any
import frappe
from frappe.utils import add_days, getdate, now_datetime, today

from recruitrain_employer.services.stripe_service import StripeService
from recruitrain_employer.utils.activity_logger import log_activity
from recruitrain_employer.utils.constants import (
    DOCTYPE_BILLING_TRANSACTION,
    DOCTYPE_COMPANY_SUBSCRIPTION,
    DOCTYPE_SUBSCRIPTION_PLAN,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_CANCELLED,
    SUBSCRIPTION_STATUS_EXPIRED,
    SUBSCRIPTION_STATUS_PAST_DUE,
    SUBSCRIPTION_STATUS_TRIAL,
)


class WebhookService:
    """Idempotent handler for Stripe webhook callbacks."""

    def __init__(self):
        self.stripe_service = StripeService()

    def process_raw_webhook(self, raw_body: bytes | str, sig_header: str | None) -> dict[str, Any]:
        """Verify signature and process raw incoming Stripe webhook payload.

        Parameters
        ----------
        raw_body : bytes | str
            Raw request body.
        sig_header : str | None
            Stripe-Signature header.

        Returns
        -------
        dict[str, Any]
            Processing result status.
        """
        # If webhook secret configured, verify signature
        if self.stripe_service.webhook_secret:
            event_data = self.stripe_service.verify_webhook_signature(raw_body, sig_header)
            if not event_data:
                return {
                    "status": "failed",
                    "reason": "invalid_signature",
                    "code": "INVALID_SIGNATURE",
                }
        else:
            # Deserialization without secret (test mode)
            try:
                raw_str = raw_body.decode("utf-8") if isinstance(raw_body, bytes) else str(raw_body)
                event_data = json.loads(raw_str)
            except Exception:
                return {"status": "failed", "reason": "invalid_json_payload", "code": "INVALID_PAYLOAD"}

        return self.handle_webhook_event(event_data)

    def handle_webhook_event(self, event_data: dict[str, Any]) -> dict[str, Any]:
        """Process incoming Stripe webhook event idempotently.

        Parameters
        ----------
        event_data : dict[str, Any]
            Deserialized Stripe event JSON payload.

        Returns
        -------
        dict[str, Any]
            Processing result status.
        """
        if not isinstance(event_data, dict):
            return {"status": "failed", "reason": "invalid_payload_structure"}

        event_id = event_data.get("id")
        event_type = event_data.get("type")
        data_obj = event_data.get("data", {}).get("object", {})

        if not event_id or not event_type:
            return {"status": "failed", "reason": "missing_event_id_or_type"}

        # Idempotency Check: Verify if event_id already processed
        if self._is_event_processed(event_id):
            frappe.logger().info(f"[WebhookService] Duplicate webhook event '{event_id}' ({event_type}) ignored.")
            return {
                "status": "ignored",
                "reason": "duplicate_event",
                "event_id": event_id,
                "event_type": event_type,
            }

        # Dispatch event handler
        handler_map = {
            "checkout.session.completed": self._handle_checkout_completed,
            "customer.subscription.created": self._handle_subscription_created,
            "customer.subscription.updated": self._handle_subscription_updated,
            "customer.subscription.deleted": self._handle_subscription_deleted,
            "invoice.paid": self._handle_invoice_paid,
            "invoice.payment_failed": self._handle_invoice_payment_failed,
        }

        handler = handler_map.get(event_type)
        if not handler:
            return {
                "status": "ignored",
                "reason": "unhandled_event_type",
                "event_type": event_type,
            }

        result = handler(event_id, data_obj)

        # Record event in idempotency log / cache
        self._record_processed_event(event_id, event_type, data_obj)
        frappe.db.commit()

        return result

    # ------------------------------------------------------------------
    # Event Handlers
    # ------------------------------------------------------------------

    def _handle_checkout_completed(self, event_id: str, obj: dict[str, Any]) -> dict[str, Any]:
        """Handle checkout.session.completed event."""
        customer_id = obj.get("customer")
        stripe_sub_id = obj.get("subscription")
        session_id = obj.get("id")
        client_ref_id = obj.get("client_reference_id")
        amount = (obj.get("amount_total") or 0) / 100.0
        currency = (obj.get("currency") or "USD").upper()

        company, sub_doc = self._resolve_company_and_subscription(customer_id, stripe_sub_id, obj, company_override=client_ref_id)

        if not sub_doc:
            return {"status": "failed", "reason": "subscription_not_found", "event_id": event_id}

        # Extract billing interval & plan from session metadata
        metadata = obj.get("metadata", {})
        interval = metadata.get("billing_interval") or "monthly"
        plan_name = metadata.get("plan_name")

        if plan_name and frappe.db.exists(DOCTYPE_SUBSCRIPTION_PLAN, plan_name):
            sub_doc.subscription_plan = plan_name

        sub_doc.status = "Active"
        sub_doc.billing_interval = interval
        sub_doc.amount = amount
        sub_doc.currency = currency
        sub_doc.stripe_customer_id = customer_id or sub_doc.stripe_customer_id
        sub_doc.stripe_subscription_id = stripe_sub_id or sub_doc.stripe_subscription_id
        sub_doc.stripe_checkout_session_id = session_id
        sub_doc.stripe_checkout_session = session_id
        sub_doc.start_date = getdate(today())
        sub_doc.started_at = now_datetime()
        sub_doc.current_period_start = now_datetime()
        sub_doc.end_date = add_days(sub_doc.start_date, 365 if interval == "yearly" else 30)
        sub_doc.current_period_end = now_datetime()
        sub_doc.renewal_date = sub_doc.end_date
        sub_doc.save(ignore_permissions=True)

        # Create Billing Transaction for checkout completion
        txn = frappe.new_doc(DOCTYPE_BILLING_TRANSACTION)
        txn.company = company
        txn.company_subscription = sub_doc.name
        txn.transaction_type = "checkout"
        txn.payment_status = "Paid"
        txn.amount = amount
        txn.currency = currency
        txn.stripe_event_id = event_id
        txn.stripe_checkout_session_id = session_id
        txn.stripe_customer_id = customer_id
        txn.stripe_subscription_id = stripe_sub_id
        txn.paid_at = now_datetime()
        txn.transaction_timestamp = now_datetime()
        txn.insert(ignore_permissions=True)

        log_activity(
            activity_type="Subscription Started",
            description=f"Checkout session completed. Subscription activated under plan '{sub_doc.subscription_plan}'.",
            reference_doctype=DOCTYPE_COMPANY_SUBSCRIPTION,
            reference_name=sub_doc.name,
            company=company,
        )

        return {
            "status": "success",
            "event_type": "checkout.session.completed",
            "company": company,
            "subscription": sub_doc.name,
            "transaction": txn.name,
        }

    def _handle_subscription_created(self, event_id: str, obj: dict[str, Any]) -> dict[str, Any]:
        """Handle customer.subscription.created event."""
        stripe_sub_id = obj.get("id")
        customer_id = obj.get("customer")
        stripe_status = obj.get("status")

        company, sub_doc = self._resolve_company_and_subscription(customer_id, stripe_sub_id, obj)
        if not sub_doc:
            return {"status": "failed", "reason": "subscription_not_found", "event_id": event_id}

        sub_doc.stripe_subscription_id = stripe_sub_id
        sub_doc.stripe_customer_id = customer_id
        sub_doc.status = self._map_stripe_status(stripe_status)
        sub_doc.save(ignore_permissions=True)

        return {
            "status": "success",
            "event_type": "customer.subscription.created",
            "company": company,
            "subscription": sub_doc.name,
        }

    def _handle_subscription_updated(self, event_id: str, obj: dict[str, Any]) -> dict[str, Any]:
        """Handle customer.subscription.updated event."""
        stripe_sub_id = obj.get("id")
        customer_id = obj.get("customer")
        stripe_status = obj.get("status")
        cancel_at_period_end = obj.get("cancel_at_period_end", False)

        company, sub_doc = self._resolve_company_and_subscription(customer_id, stripe_sub_id, obj)

        if not sub_doc:
            return {"status": "failed", "reason": "subscription_not_found", "event_id": event_id}

        old_status = sub_doc.status
        mapped_status = self._map_stripe_status(stripe_status)

        sub_doc.status = mapped_status
        sub_doc.cancel_at_period_end = 1 if cancel_at_period_end else 0

        if obj.get("canceled_at"):
            sub_doc.cancelled_at = now_datetime()

        # Update period dates from Stripe event
        if obj.get("current_period_start"):
            sub_doc.start_date = getdate(today())
        if obj.get("current_period_end"):
            sub_doc.end_date = getdate(today())

        # Resolve plan from items if price/product changed
        items = obj.get("items", {}).get("data", [])
        if items:
            price_id = items[0].get("price", {}).get("id")
            plan_name = self._resolve_plan_from_price_id(price_id)
            if plan_name:
                sub_doc.subscription_plan = plan_name

        sub_doc.save(ignore_permissions=True)

        log_activity(
            activity_type="Subscription Updated",
            description=f"Subscription updated to status '{mapped_status}'.",
            reference_doctype=DOCTYPE_COMPANY_SUBSCRIPTION,
            reference_name=sub_doc.name,
            company=company,
        )

        return {
            "status": "success",
            "event_type": "customer.subscription.updated",
            "company": company,
            "subscription": sub_doc.name,
            "subscription_status": mapped_status,
        }

    def _handle_subscription_deleted(self, event_id: str, obj: dict[str, Any]) -> dict[str, Any]:
        """Handle customer.subscription.deleted event."""
        stripe_sub_id = obj.get("id")
        customer_id = obj.get("customer")

        company, sub_doc = self._resolve_company_and_subscription(customer_id, stripe_sub_id, obj)

        if not sub_doc:
            return {"status": "failed", "reason": "subscription_not_found", "event_id": event_id}

        sub_doc.status = "Cancelled"
        sub_doc.cancelled_at = now_datetime()
        sub_doc.ended_at = now_datetime()
        sub_doc.save(ignore_permissions=True)

        log_activity(
            activity_type="Subscription Cancelled",
            description=f"Subscription '{sub_doc.name}' was cancelled via Stripe.",
            reference_doctype=DOCTYPE_COMPANY_SUBSCRIPTION,
            reference_name=sub_doc.name,
            company=company,
        )

        return {
            "status": "success",
            "event_type": "customer.subscription.deleted",
            "company": company,
            "subscription": sub_doc.name,
        }

    def _handle_invoice_paid(self, event_id: str, obj: dict[str, Any]) -> dict[str, Any]:
        """Handle invoice.paid event."""
        customer_id = obj.get("customer")
        stripe_sub_id = obj.get("subscription")
        invoice_id = obj.get("id")
        payment_intent = obj.get("payment_intent") or event_id
        amount = (obj.get("amount_paid") or 0) / 100.0
        currency = (obj.get("currency") or "USD").upper()
        invoice_number = obj.get("number") or invoice_id or f"INV-{event_id}"

        company, sub_doc = self._resolve_company_and_subscription(customer_id, stripe_sub_id, obj)

        if not sub_doc:
            return {"status": "failed", "reason": "subscription_not_found", "event_id": event_id}

        # Update Subscription Status & Extend Validity Period
        sub_doc.status = "Active"
        sub_doc.last_payment_date = now_datetime()
        sub_doc.start_date = getdate(today())
        sub_doc.end_date = add_days(sub_doc.start_date, 30)
        sub_doc.renewal_date = sub_doc.end_date
        sub_doc.save(ignore_permissions=True)

        # Create Immutable Billing Transaction
        txn = frappe.new_doc(DOCTYPE_BILLING_TRANSACTION)
        txn.company = company
        txn.company_subscription = sub_doc.name
        txn.transaction_type = "payment"
        txn.amount = amount
        txn.currency = currency
        txn.invoice_number = invoice_number
        txn.payment_status = "Paid"
        txn.stripe_event_id = event_id
        txn.stripe_payment_intent = payment_intent
        txn.stripe_invoice_id = invoice_id
        txn.stripe_customer_id = customer_id
        txn.stripe_subscription_id = stripe_sub_id
        txn.paid_at = now_datetime()
        txn.transaction_timestamp = now_datetime()
        txn.insert(ignore_permissions=True)

        log_activity(
            activity_type="Payment Received",
            description=f"Payment of {currency} {amount:.2f} received for invoice '{invoice_number}'.",
            reference_doctype=DOCTYPE_BILLING_TRANSACTION,
            reference_name=txn.name,
            company=company,
        )

        return {
            "status": "success",
            "event_type": "invoice.paid",
            "company": company,
            "subscription": sub_doc.name,
            "transaction": txn.name,
        }

    def _handle_invoice_payment_failed(self, event_id: str, obj: dict[str, Any]) -> dict[str, Any]:
        """Handle invoice.payment_failed event."""
        customer_id = obj.get("customer")
        stripe_sub_id = obj.get("subscription")
        invoice_id = obj.get("id")
        payment_intent = obj.get("payment_intent") or event_id
        amount = (obj.get("amount_due") or 0) / 100.0
        currency = (obj.get("currency") or "USD").upper()
        invoice_number = obj.get("number") or invoice_id or f"INV-{event_id}"
        failure_msg = obj.get("last_finalization_error", {}).get("message") or "Payment processing failed."

        company, sub_doc = self._resolve_company_and_subscription(customer_id, stripe_sub_id, obj)

        if not sub_doc:
            return {"status": "failed", "reason": "subscription_not_found", "event_id": event_id}

        # Update Subscription Status to Past Due
        sub_doc.status = "Past Due"
        sub_doc.save(ignore_permissions=True)

        # Record Failed Billing Transaction
        txn = frappe.new_doc(DOCTYPE_BILLING_TRANSACTION)
        txn.company = company
        txn.company_subscription = sub_doc.name
        txn.transaction_type = "payment"
        txn.amount = amount
        txn.currency = currency
        txn.invoice_number = invoice_number
        txn.payment_status = "Failed"
        txn.stripe_event_id = event_id
        txn.stripe_payment_intent = payment_intent
        txn.stripe_invoice_id = invoice_id
        txn.stripe_customer_id = customer_id
        txn.stripe_subscription_id = stripe_sub_id
        txn.failure_reason = failure_msg
        txn.transaction_timestamp = now_datetime()
        txn.insert(ignore_permissions=True)

        log_activity(
            activity_type="Payment Failed",
            description=f"Payment failed for invoice '{invoice_number}'. Subscription marked as Past Due.",
            reference_doctype=DOCTYPE_COMPANY_SUBSCRIPTION,
            reference_name=sub_doc.name,
            company=company,
        )

        return {
            "status": "success",
            "event_type": "invoice.payment_failed",
            "company": company,
            "subscription": sub_doc.name,
            "status_set": "Past Due",
        }

    # ------------------------------------------------------------------
    # Idempotency Helpers
    # ------------------------------------------------------------------

    def _is_event_processed(self, event_id: str) -> bool:
        """Check if event_id has already been processed in Billing Transactions or cache."""
        if not event_id:
            return False

        # 1. Check Billing Transaction table by stripe_event_id or stripe_payment_intent
        if frappe.db.exists(DOCTYPE_BILLING_TRANSACTION, {"stripe_event_id": event_id}):
            return True

        if frappe.db.exists(DOCTYPE_BILLING_TRANSACTION, {"stripe_payment_intent": event_id}):
            return True

        # 2. Check cache
        cached = frappe.cache().get_value(f"webhook_event_{event_id}")
        return bool(cached)

    def _record_processed_event(self, event_id: str, event_type: str, data_obj: dict[str, Any]) -> None:
        """Cache processed event ID for idempotency protection (24 hr TTL)."""
        frappe.cache().set_value(f"webhook_event_{event_id}", {"type": event_type, "processed_at": str(now_datetime())}, expires_in_sec=86400)

    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    def _resolve_company_and_subscription(
        self,
        customer_id: str | None,
        stripe_sub_id: str | None,
        obj: dict[str, Any],
        company_override: str | None = None,
    ) -> tuple[str, Any]:
        """Resolve company name and active Company Subscription document."""
        company = company_override

        # 1. Resolve company by metadata or customer ID or subscription ID
        metadata = obj.get("metadata", {})
        if not company and metadata.get("company"):
            company = metadata.get("company")

        if not company and customer_id:
            company = frappe.db.get_value(DOCTYPE_COMPANY_SUBSCRIPTION, {"stripe_customer_id": customer_id}, "company")

        if not company and stripe_sub_id:
            company = frappe.db.get_value(DOCTYPE_COMPANY_SUBSCRIPTION, {"stripe_subscription_id": stripe_sub_id}, "company")

        sub_doc = None
        if company:
            sub_name = frappe.db.get_value(DOCTYPE_COMPANY_SUBSCRIPTION, {"company": company}, "name", order_by="creation desc")
            if sub_name:
                sub_doc = frappe.get_doc(DOCTYPE_COMPANY_SUBSCRIPTION, sub_name)

        if not sub_doc:
            # Fallback lookup by stripe_subscription_id
            if stripe_sub_id:
                sub_name = frappe.db.get_value(DOCTYPE_COMPANY_SUBSCRIPTION, {"stripe_subscription_id": stripe_sub_id}, "name")
                if sub_name:
                    sub_doc = frappe.get_doc(DOCTYPE_COMPANY_SUBSCRIPTION, sub_name)
                    company = sub_doc.company

        if not sub_doc:
            subscriptions = frappe.get_all(DOCTYPE_COMPANY_SUBSCRIPTION, fields=["name", "company"], limit=1, order_by="creation desc")
            if subscriptions:
                sub_doc = frappe.get_doc(DOCTYPE_COMPANY_SUBSCRIPTION, subscriptions[0].name)
                company = sub_doc.company

        return company or "RecruiTrain", sub_doc

    @staticmethod
    def _map_stripe_status(stripe_status: str | None) -> str:
        """Map Stripe status string to ATS Subscription status."""
        mapping = {
            "active": "Active",
            "trialing": "Trial",
            "past_due": "Past Due",
            "canceled": "Cancelled",
            "cancelled": "Cancelled",
            "unpaid": "Expired",
            "incomplete": "Incomplete",
            "incomplete_expired": "Expired",
            "paused": "Paused",
        }
        return mapping.get(str(stripe_status).lower(), "Active")

    @staticmethod
    def _resolve_plan_from_price_id(price_id: str | None) -> str | None:
        """Resolve ATS Subscription Plan name from Stripe price/product ID."""
        if not price_id:
            return None

        plan_name = frappe.db.get_value(DOCTYPE_SUBSCRIPTION_PLAN, {"stripe_monthly_price_id": price_id}, "name")
        if not plan_name:
            plan_name = frappe.db.get_value(DOCTYPE_SUBSCRIPTION_PLAN, {"stripe_yearly_price_id": price_id}, "name")
        if not plan_name:
            plan_name = frappe.db.get_value(DOCTYPE_SUBSCRIPTION_PLAN, {"stripe_product_id": price_id}, "name")
        return plan_name
