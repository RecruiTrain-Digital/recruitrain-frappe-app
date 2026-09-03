# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.api.billing_webhook
=========================================

REST API Endpoint for Stripe Webhook Callback Notifications.
Delegates to recruitrain_employer.api.billing.stripe_webhook.
"""

from __future__ import annotations

import frappe
from recruitrain_employer.api.billing import stripe_webhook as _billing_stripe_webhook


@frappe.whitelist(allow_guest=True)
def stripe_webhook():
    """Receive and process Stripe Webhook Event notifications."""
    return _billing_stripe_webhook()
