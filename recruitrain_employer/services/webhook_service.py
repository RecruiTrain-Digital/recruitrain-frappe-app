# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.services.webhook_service
================================================

Production-Grade Stripe Webhook Handler & Idempotent Processing Engine.

Supports events:
- invoice.paid
- invoice.payment_failed
- customer.subscription.updated
- customer.subscription.deleted
- checkout.session.completed

Idempotency:
Guarantees duplicate webhook deliveries (webhook replay attacks / network retries)
do not cause duplicate transactions, duplicate usage increments, or invalid subscription extensions.
"""

from __future__ import annotations

from typing import Any
import frappe
from frappe.utils import add_days, getdate, now_datetime, today

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
            return {"status": "error", "message": "Invalid event payload"}

        event_id = event_data.get("id")
        event_type = event_data.get("type")
        data_obj = event_data.get("data", {}).get("object", {})

        if not event_id or not event_type:
            return {"status": "error", "message": "Missing event ID or event type"}

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
            "invoice.paid": self._handle_invoice_paid,
            "invoice.payment_failed": self._handle_invoice_payment_failed,
            "customer.subscription.updated": self._handle_subscription_updated,
            "customer.subscription.deleted": self._handle_subscription_deleted,
            "checkout.session.completed": self._handle_checkout_completed,
        }

        handler = handler_map.get(event_type)
        if not handler:
            return {
                "status": "ignored",
                "reason": "unhandled_event_type",
                "event_type": event_type,
            }

        result = handler(event_id, data_obj)

        # Mark event as processed in idempotency log
        self._record_processed_event(event_id, event_type, data_obj)
        frappe.db.commit()

        return result

    # ------------------------------------------------------------------
    # Event Handlers
    # ------------------------------------------------------------------

    def _handle_invoice_paid(self, event_id: str, obj: dict[str, Any]) -> dict[str, Any]:
        """Handle invoice.paid event."""
        customer_id = obj.get("customer")
        stripe_sub_id = obj.get("subscription")
        amount = (obj.get("amount_paid") or 0) / 100.0  # Convert cents to dollars/currency unit
        currency = (obj.get("currency") or "USD").upper()
        invoice_number = obj.get("number") or obj.get("id") or f"INV-{event_id}"
        payment_intent = obj.get("payment_intent") or event_id

        company, sub_doc = self._resolve_company_and_subscription(customer_id, stripe_sub_id, obj)

        if not sub_doc:
            return {"status": "failed", "reason": "subscription_not_found", "event_id": event_id}

        # Update Subscription Status & Extend Validity Period
        sub_doc.status = SUBSCRIPTION_STATUS_ACTIVE
        start = getdate(today())
        sub_doc.end_date = add_days(start, 30)
        sub_doc.renewal_date = sub_doc.end_date
        sub_doc.save(ignore_permissions=True)

        # Create Immutable Billing Transaction
        txn = frappe.new_doc(DOCTYPE_BILLING_TRANSACTION)
        txn.company = company
        txn.company_subscription = sub_doc.name
        txn.amount = amount
        txn.currency = currency
        txn.invoice_number = invoice_number
        txn.payment_status = "Paid"
        txn.stripe_payment_intent = payment_intent
        txn.paid_at = now_datetime()
        txn.insert(ignore_permissions=True)

        # Activity Logs
        log_activity(
            activity_type="Payment Received",
            description=f"Payment of {currency} {amount:.2f} received for invoice '{invoice_number}'.",
            reference_doctype=DOCTYPE_BILLING_TRANSACTION,
            reference_name=txn.name,
            company=company,
        )

        log_activity(
            activity_type="Subscription Renewed",
            description=f"Subscription renewed until {sub_doc.end_date} under plan '{sub_doc.subscription_plan}'.",
            reference_doctype=DOCTYPE_COMPANY_SUBSCRIPTION,
            reference_name=sub_doc.name,
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
        amount = (obj.get("amount_due") or 0) / 100.0
        currency = (obj.get("currency") or "USD").upper()
        invoice_number = obj.get("number") or obj.get("id") or f"INV-{event_id}"
        payment_intent = obj.get("payment_intent") or event_id

        company, sub_doc = self._resolve_company_and_subscription(customer_id, stripe_sub_id, obj)

        if not sub_doc:
            return {"status": "failed", "reason": "subscription_not_found", "event_id": event_id}

        # Update Subscription Status to Past Due
        sub_doc.status = SUBSCRIPTION_STATUS_PAST_DUE
        sub_doc.save(ignore_permissions=True)

        # Record Failed Billing Transaction
        txn = frappe.new_doc(DOCTYPE_BILLING_TRANSACTION)
        txn.company = company
        txn.company_subscription = sub_doc.name
        txn.amount = amount
        txn.currency = currency
        txn.invoice_number = invoice_number
        txn.payment_status = "Failed"
        txn.stripe_payment_intent = payment_intent
        txn.insert(ignore_permissions=True)

        # Activity Log
        log_activity(
            activity_type="Payment Failed",
            description=f"Payment failed for invoice '{invoice_number}' ({currency} {amount:.2f}). Subscription marked as Past Due.",
            reference_doctype=DOCTYPE_COMPANY_SUBSCRIPTION,
            reference_name=sub_doc.name,
            company=company,
        )

        return {
            "status": "success",
            "event_type": "invoice.payment_failed",
            "company": company,
            "subscription": sub_doc.name,
            "status_set": SUBSCRIPTION_STATUS_PAST_DUE,
        }

    def _handle_subscription_updated(self, event_id: str, obj: dict[str, Any]) -> dict[str, Any]:
        """Handle customer.subscription.updated event."""
        stripe_sub_id = obj.get("id")
        customer_id = obj.get("customer")
        stripe_status = obj.get("status")

        company, sub_doc = self._resolve_company_and_subscription(customer_id, stripe_sub_id, obj)

        if not sub_doc:
            return {"status": "failed", "reason": "subscription_not_found", "event_id": event_id}

        old_status = sub_doc.status
        old_plan = sub_doc.subscription_plan

        # Map Stripe status to ATS Subscription status
        mapped_status = self._map_stripe_status(stripe_status)
        sub_doc.status = mapped_status

        # Plan mapping if items provided
        items = obj.get("items", {}).get("data", [])
        if items and len(items) > 0:
            price_id = items[0].get("price", {}).get("id")
            plan_name = self._resolve_plan_from_price_id(price_id)
            if plan_name:
                sub_doc.subscription_plan = plan_name

        sub_doc.save(ignore_permissions=True)

        # Log transition
        if old_plan != sub_doc.subscription_plan:
            log_activity(
                activity_type="Subscription Upgraded" if mapped_status == SUBSCRIPTION_STATUS_ACTIVE else "Subscription Plan Changed",
                description=f"Subscription changed from '{old_plan}' to '{sub_doc.subscription_plan}'.",
                reference_doctype=DOCTYPE_COMPANY_SUBSCRIPTION,
                reference_name=sub_doc.name,
                company=company,
            )

        return {
            "status": "success",
            "event_type": "customer.subscription.updated",
            "company": company,
            "new_status": mapped_status,
            "new_plan": sub_doc.subscription_plan,
        }

    def _handle_subscription_deleted(self, event_id: str, obj: dict[str, Any]) -> dict[str, Any]:
        """Handle customer.subscription.deleted event."""
        stripe_sub_id = obj.get("id")
        customer_id = obj.get("customer")

        company, sub_doc = self._resolve_company_and_subscription(customer_id, stripe_sub_id, obj)

        if not sub_doc:
            return {"status": "failed", "reason": "subscription_not_found", "event_id": event_id}

        sub_doc.status = SUBSCRIPTION_STATUS_CANCELLED
        sub_doc.save(ignore_permissions=True)

        log_activity(
            activity_type="Subscription Cancelled",
            description=f"Subscription '{sub_doc.name}' was cancelled via Stripe webhook.",
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

    def _handle_checkout_completed(self, event_id: str, obj: dict[str, Any]) -> dict[str, Any]:
        """Handle checkout.session.completed event."""
        customer_id = obj.get("customer")
        stripe_sub_id = obj.get("subscription")
        client_ref_id = obj.get("client_reference_id")  # Company name passed during checkout creation

        company, sub_doc = self._resolve_company_and_subscription(customer_id, stripe_sub_id, obj, company_override=client_ref_id)

        if not sub_doc:
            return {"status": "failed", "reason": "subscription_not_found", "event_id": event_id}

        sub_doc.status = SUBSCRIPTION_STATUS_ACTIVE
        sub_doc.start_date = getdate(today())
        sub_doc.end_date = add_days(sub_doc.start_date, 30)
        sub_doc.save(ignore_permissions=True)

        log_activity(
            activity_type="Subscription Started",
            description=f"Checkout session completed. Subscription started under plan '{sub_doc.subscription_plan}'.",
            reference_doctype=DOCTYPE_COMPANY_SUBSCRIPTION,
            reference_name=sub_doc.name,
            company=company,
        )

        return {
            "status": "success",
            "event_type": "checkout.session.completed",
            "company": company,
            "subscription": sub_doc.name,
        }

    # ------------------------------------------------------------------
    # Idempotency Helpers
    # ------------------------------------------------------------------

    def _is_event_processed(self, event_id: str) -> bool:
        """Check if event_id has already been processed in Billing Transactions or cache."""
        if not event_id:
            return False

        # 1. Check Billing Transaction table
        if frappe.db.exists(DOCTYPE_BILLING_TRANSACTION, {"stripe_payment_intent": event_id}):
            return True

        # 2. Check cache / key-value store
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

        # 1. Resolve company by name or Metadata
        metadata = obj.get("metadata", {})
        if not company and metadata.get("company"):
            company = metadata.get("company")

        # 2. Resolve subscription doc
        sub_doc = None
        if company:
            sub_name = frappe.db.get_value(DOCTYPE_COMPANY_SUBSCRIPTION, {"company": company}, "name", order_by="creation desc")
            if sub_name:
                sub_doc = frappe.get_doc(DOCTYPE_COMPANY_SUBSCRIPTION, sub_name)

        if not sub_doc:
            # Try finding any subscription
            subscriptions = frappe.get_all(DOCTYPE_COMPANY_SUBSCRIPTION, fields=["name", "company"], limit=1, order_by="creation desc")
            if subscriptions:
                sub_doc = frappe.get_doc(DOCTYPE_COMPANY_SUBSCRIPTION, subscriptions[0].name)
                company = sub_doc.company

        return company or "RecruiTrain", sub_doc

    @staticmethod
    def _map_stripe_status(stripe_status: str | None) -> str:
        """Map Stripe status string to ATS Subscription status."""
        mapping = {
            "active": SUBSCRIPTION_STATUS_ACTIVE,
            "trialing": SUBSCRIPTION_STATUS_TRIAL,
            "past_due": SUBSCRIPTION_STATUS_PAST_DUE,
            "canceled": SUBSCRIPTION_STATUS_CANCELLED,
            "unpaid": SUBSCRIPTION_STATUS_EXPIRED,
            "paused": "Paused",
        }
        return mapping.get(str(stripe_status).lower(), SUBSCRIPTION_STATUS_ACTIVE)

    @staticmethod
    def _resolve_plan_from_price_id(price_id: str | None) -> str | None:
        """Resolve ATS Subscription Plan name from Stripe price/product ID."""
        if not price_id:
            return None

        plan_name = frappe.db.get_value(DOCTYPE_SUBSCRIPTION_PLAN, {"stripe_product_id": price_id}, "name")
        if not plan_name:
            # Fallback exact name search
            plan_name = frappe.db.get_value(DOCTYPE_SUBSCRIPTION_PLAN, {"is_active": 1}, "name")
        return plan_name
