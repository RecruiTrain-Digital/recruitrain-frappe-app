# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.tests.test_billing_phase30
=================================================

Comprehensive Phase 30 Test Suite (BILL-01 through BILL-22) for RecruitTrain Billing & Subscription Engine.

Validates:
- Plan retrieval, active subscription retrieval, usage retrieval
- Server-side checkout session creation and price protection
- Stripe webhook signature verification and event handling
- Webhook idempotency protection (duplicate event rejection)
- Cancellation & resumption server-side synchronization
- Company isolation & unauthenticated access controls
"""

from __future__ import annotations

import json
from unittest.mock import patch
import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, now_datetime, today

from recruitrain_employer.api.billing import (
    cancel_subscription,
    create_checkout_session,
    get_billing_summary,
    get_billing_transactions,
    get_current_subscription,
    get_subscription_plans,
    get_subscription_usage,
    resume_subscription,
    stripe_webhook,
)
from recruitrain_employer.services.stripe_service import StripeService
from recruitrain_employer.services.subscription_service import SubscriptionService
from recruitrain_employer.services.webhook_service import WebhookService
from recruitrain_employer.utils.constants import (
    DOCTYPE_BILLING_TRANSACTION,
    DOCTYPE_COMPANY_SUBSCRIPTION,
    DOCTYPE_SUBSCRIPTION_PLAN,
    DOCTYPE_SUBSCRIPTION_USAGE,
)


class TestBillingPhase30(FrappeTestCase):
    """Phase 30 Billing & Subscription Automated Test Suite (BILL-01 to BILL-22)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        cls._create_test_entities()

    @classmethod
    def _create_test_entities(cls):
        """Provision Companies, Plans, Subscriptions, and Users for testing."""
        frappe.db.sql("DELETE FROM `tabBilling Transaction` WHERE company LIKE 'Phase30 Company%'")
        frappe.db.commit()

        # Clear Redis event cache for test webhook event IDs
        test_eids = [
            "evt_checkout_completed_30_11",
            "evt_inv_paid_30_12",
            "evt_inv_failed_30_13",
            "evt_sub_updated_30_14",
            "evt_sub_deleted_30_15",
            "evt_idempotent_test_30_16",
            "evt_dedup_txn_30_17",
        ]
        for eid in test_eids:
            frappe.cache().delete_value(f"webhook_event_{eid}")

        # 1. Companies
        for cname in ["Phase30 Company Alpha", "Phase30 Company Beta"]:
            if not frappe.db.exists("Company", cname):
                comp = frappe.new_doc("Company")
                comp.company_name = cname
                comp.industry = "Technology"
                comp.email = f"{cname.lower().replace(' ', '_')}@testcompany.com"
                comp.phone = "+14155552671"
                comp.address_line_1 = "100 Enterprise Way"
                comp.default_currency = "USD"
                comp.status = "Active"
                comp.insert(ignore_permissions=True)
            else:
                frappe.db.set_value("Company", cname, {"status": "Active", "industry": "Technology"})

        # 2. Plans
        cls.plan_starter_name = "Phase30 Starter"
        if not frappe.db.exists(DOCTYPE_SUBSCRIPTION_PLAN, cls.plan_starter_name):
            plan = frappe.new_doc(DOCTYPE_SUBSCRIPTION_PLAN)
            plan.plan_name = cls.plan_starter_name
            plan.plan_code = "phase30_starter"
            plan.description = "Phase 30 Starter Plan"
            plan.monthly_price = 49.0
            plan.yearly_price = 490.0
            plan.currency = "USD"
            plan.trial_days = 14
            plan.is_active = 1
            plan.display_order = 1
            plan.max_active_jobs = 5
            plan.max_recruiters = 2
            plan.max_candidates = 500
            plan.storage_gb = 5.0
            plan.monthly_email_limit = 1000
            plan.monthly_sms_limit = 200
            plan.ai_credits = 100
            plan.stripe_product_id = "prod_phase30_starter"
            plan.stripe_monthly_price_id = "price_phase30_starter_monthly"
            plan.stripe_yearly_price_id = "price_phase30_starter_yearly"
            plan.insert(ignore_permissions=True)

        cls.plan_pro_name = "Phase30 Pro"
        if not frappe.db.exists(DOCTYPE_SUBSCRIPTION_PLAN, cls.plan_pro_name):
            plan = frappe.new_doc(DOCTYPE_SUBSCRIPTION_PLAN)
            plan.plan_name = cls.plan_pro_name
            plan.plan_code = "phase30_pro"
            plan.description = "Phase 30 Pro Plan"
            plan.monthly_price = 199.0
            plan.yearly_price = 1990.0
            plan.currency = "USD"
            plan.trial_days = 14
            plan.is_active = 1
            plan.display_order = 2
            plan.max_active_jobs = 25
            plan.max_recruiters = 10
            plan.max_candidates = 5000
            plan.storage_gb = 50.0
            plan.monthly_email_limit = 10000
            plan.monthly_sms_limit = 1000
            plan.ai_credits = 500
            plan.stripe_product_id = "prod_phase30_pro"
            plan.stripe_monthly_price_id = "price_phase30_pro_monthly"
            plan.stripe_yearly_price_id = "price_phase30_pro_yearly"
            plan.insert(ignore_permissions=True)

        # 3. Employer Users
        cls.user_alpha = "employer_phase30_alpha@test.com"
        if not frappe.db.exists("User", cls.user_alpha):
            u = frappe.new_doc("User")
            u.email = cls.user_alpha
            u.first_name = "Phase30 Alpha"
            u.send_welcome_email = 0
            u.insert(ignore_permissions=True)

        emp_alpha_name = frappe.db.get_value("Employer User", {"user": cls.user_alpha}, "name")
        if not emp_alpha_name:
            emp = frappe.new_doc("Employer User")
            emp.user = cls.user_alpha
            emp.company = "Phase30 Company Alpha"
            emp.role = "Administrator"
            emp.status = "Active"
            emp.insert(ignore_permissions=True)
        else:
            frappe.db.set_value("Employer User", emp_alpha_name, {"company": "Phase30 Company Alpha", "status": "Active", "role": "Administrator"})

        cls.user_beta = "employer_phase30_beta@test.com"
        if not frappe.db.exists("User", cls.user_beta):
            u = frappe.new_doc("User")
            u.email = cls.user_beta
            u.first_name = "Phase30 Beta"
            u.send_welcome_email = 0
            u.insert(ignore_permissions=True)

        emp_beta_name = frappe.db.get_value("Employer User", {"user": cls.user_beta}, "name")
        if not emp_beta_name:
            emp = frappe.new_doc("Employer User")
            emp.user = cls.user_beta
            emp.company = "Phase30 Company Beta"
            emp.role = "Administrator"
            emp.status = "Active"
            emp.insert(ignore_permissions=True)
        else:
            frappe.db.set_value("Employer User", emp_beta_name, {"company": "Phase30 Company Beta", "status": "Active", "role": "Administrator"})

        # 4. Company Subscriptions
        cls.sub_alpha_name = frappe.db.get_value(DOCTYPE_COMPANY_SUBSCRIPTION, {"company": "Phase30 Company Alpha"}, "name")
        if not cls.sub_alpha_name:
            sub = frappe.new_doc(DOCTYPE_COMPANY_SUBSCRIPTION)
            sub.company = "Phase30 Company Alpha"
            sub.subscription_plan = cls.plan_starter_name
            sub.status = "Active"
            sub.start_date = getdate(today())
            sub.end_date = add_days(sub.start_date, 30)
            sub.billing_cycle = "Monthly"
            sub.billing_interval = "monthly"
            sub.amount = 49.0
            sub.currency = "USD"
            sub.stripe_customer_id = "cus_phase30_alpha"
            sub.stripe_subscription_id = "sub_phase30_alpha"
            sub.insert(ignore_permissions=True)
            cls.sub_alpha_name = sub.name

        cls.sub_beta_name = frappe.db.get_value(DOCTYPE_COMPANY_SUBSCRIPTION, {"company": "Phase30 Company Beta"}, "name")
        if not cls.sub_beta_name:
            sub = frappe.new_doc(DOCTYPE_COMPANY_SUBSCRIPTION)
            sub.company = "Phase30 Company Beta"
            sub.subscription_plan = cls.plan_pro_name
            sub.status = "Active"
            sub.start_date = getdate(today())
            sub.end_date = add_days(sub.start_date, 30)
            sub.billing_cycle = "Monthly"
            sub.billing_interval = "monthly"
            sub.amount = 199.0
            sub.currency = "USD"
            sub.stripe_customer_id = "cus_phase30_beta"
            sub.stripe_subscription_id = "sub_phase30_beta"
            sub.insert(ignore_permissions=True)
            cls.sub_beta_name = sub.name

        frappe.db.commit()

    def setUp(self):
        super().setUp()
        frappe.set_user(self.user_alpha)
        frappe.flags.employer_company = "Phase30 Company Alpha"

    def tearDown(self):
        frappe.flags.employer_company = None
        frappe.set_user("Administrator")
        super().tearDown()

    # ------------------------------------------------------------------
    # TESTS
    # ------------------------------------------------------------------

    def test_bill_01_plan_retrieval(self):
        """BILL-01: Verify plan retrieval endpoint returns active plans with limits and features."""
        print("\n[BILL-01] Testing Subscription Plan Retrieval...")
        res = get_subscription_plans()
        self.assertTrue(res.get("success"))
        data = res.get("data", [])
        self.assertGreaterEqual(len(data), 1)

        names = [p.get("name") or p.get("plan_name") for p in data]
        self.assertIn(self.plan_starter_name, names)
        print("  -> Available plans successfully retrieved!")

    def test_bill_02_active_subscription_retrieval(self):
        """BILL-02: Verify active subscription retrieval for authenticated user."""
        print("\n[BILL-02] Testing Active Subscription Retrieval...")
        res = get_current_subscription()
        self.assertTrue(res.get("success"))
        sub = res.get("data", {}).get("subscription", {})
        self.assertEqual(sub.get("company"), "Phase30 Company Alpha")
        self.assertEqual(sub.get("subscription_plan"), self.plan_starter_name)
        print("  -> Active subscription returned with correct company context!")

    def test_bill_03_company_isolation(self):
        """BILL-03: Verify company billing data isolation between tenants."""
        print("\n[BILL-03] Testing Tenant Company Isolation...")
        # Alpha User
        frappe.set_user(self.user_alpha)
        frappe.flags.employer_company = "Phase30 Company Alpha"
        res_alpha = get_current_subscription()
        comp_alpha = res_alpha.get("data", {}).get("subscription", {}).get("company")
        self.assertEqual(comp_alpha, "Phase30 Company Alpha")

        # Beta User
        frappe.set_user(self.user_beta)
        frappe.flags.employer_company = "Phase30 Company Beta"
        res_beta = get_current_subscription()
        comp_beta = res_beta.get("data", {}).get("subscription", {}).get("company")
        self.assertEqual(comp_beta, "Phase30 Company Beta")
        print("  -> Tenant isolation verified! Users only view their own company's subscription.")

    def test_bill_04_invalid_plan_rejected(self):
        """BILL-04: Checkout session request with non-existent plan is rejected with 404."""
        print("\n[BILL-04] Testing Invalid Plan Handling in Checkout...")
        frappe.form_dict = {"plan_id": "NonExistentPlan12345", "billing_interval": "monthly"}
        frappe.request = None
        res = create_checkout_session()
        self.assertFalse(res.get("success"))
        self.assertEqual(res.get("error", {}).get("code"), "PLAN_NOT_FOUND")
        print("  -> Invalid plan ID correctly rejected with PLAN_NOT_FOUND error!")

    def test_bill_05_invalid_billing_interval_rejected(self):
        """BILL-05: Checkout session request with invalid billing interval is rejected with 400."""
        print("\n[BILL-05] Testing Invalid Billing Interval in Checkout...")
        frappe.form_dict = {"plan_id": self.plan_starter_name, "billing_interval": "weekly"}
        frappe.request = None
        res = create_checkout_session()
        self.assertFalse(res.get("success"))
        self.assertEqual(res.get("error", {}).get("code"), "INVALID_INTERVAL")
        print("  -> Invalid billing interval correctly rejected with INVALID_INTERVAL error!")

    def test_bill_06_frontend_amount_cannot_override_plan_price(self):
        """BILL-06: Verify server-side pricing ignores client-supplied amount parameters."""
        print("\n[BILL-06] Testing Server-Side Price Protection...")
        frappe.form_dict = {
            "plan_id": self.plan_starter_name,
            "billing_interval": "monthly",
            "amount": 0.01,  # Attempt malicious price override
            "price": 1.00,
        }
        frappe.request = None
        res = create_checkout_session()
        self.assertTrue(res.get("success"))
        data = res.get("data", {})
        # Price must match database plan monthly_price (49.00)
        self.assertEqual(data.get("amount"), 49.0)
        print("  -> Client-supplied price malicious override ignored! Derived strictly from database.")

    def test_bill_07_checkout_session_creation(self):
        """BILL-07: Verify creation of Stripe checkout session returning URL and session ID."""
        print("\n[BILL-07] Testing Checkout Session Creation...")
        frappe.form_dict = {"plan_id": self.plan_pro_name, "billing_interval": "yearly"}
        frappe.request = None
        res = create_checkout_session()
        self.assertTrue(res.get("success"))
        data = res.get("data", {})
        self.assertIn("session_id", data)
        self.assertIn("checkout_url", data)
        self.assertIn("publishable_key", data)
        self.assertEqual(data.get("plan_name"), self.plan_pro_name)
        print("  -> Stripe Checkout Session created successfully with valid URL envelope!")

    def test_bill_08_stripe_customer_association(self):
        """BILL-08: Verify Stripe customer ID resolution and association."""
        print("\n[BILL-08] Testing Stripe Customer Association...")
        stripe_svc = StripeService()
        cust_id = stripe_svc.create_or_get_customer("Phase30 Company Alpha")
        self.assertTrue(cust_id.startswith("cus_"))
        print("  -> Customer ID correctly resolved/associated for company!")

    def test_bill_09_webhook_signature_verification(self):
        """BILL-09: Verify Webhook signature verification engine."""
        print("\n[BILL-09] Testing Webhook Signature Verification...")
        stripe_svc = StripeService()
        payload = json.dumps({"id": "evt_sig_test_09", "type": "checkout.session.completed", "data": {}})
        parsed = stripe_svc.verify_webhook_signature(payload, sig_header=None)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.get("id"), "evt_sig_test_09")
        print("  -> Signature verification layer operational!")

    def test_bill_10_invalid_webhook_signature_rejected(self):
        """BILL-10: Webhook with invalid signature returns failed response when secret is set."""
        print("\n[BILL-10] Testing Webhook Invalid Signature Rejection...")
        stripe_svc = StripeService()
        stripe_svc.webhook_secret = "whsec_test_secret_key_12345"
        res = stripe_svc.verify_webhook_signature("raw_payload", sig_header="t=123,v1=invalid_hash")
        self.assertIsNone(res)
        print("  -> Webhook with invalid signature correctly rejected!")

    def test_bill_11_checkout_session_completed_event(self):
        """BILL-11: Verify checkout.session.completed event activates subscription and records transaction."""
        print("\n[BILL-11] Testing checkout.session.completed Event Handling...")
        event_id = "evt_checkout_completed_30_11"
        event_payload = {
            "id": event_id,
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_30_11",
                    "customer": "cus_phase30_alpha",
                    "subscription": "sub_phase30_alpha",
                    "client_reference_id": "Phase30 Company Alpha",
                    "amount_total": 4900,
                    "currency": "usd",
                    "metadata": {"company": "Phase30 Company Alpha", "plan_name": self.plan_starter_name, "billing_interval": "monthly"},
                }
            },
        }
        svc = WebhookService()
        res = svc.handle_webhook_event(event_payload)
        self.assertEqual(res.get("status"), "success")

        # Verify Database Record Updated
        sub = frappe.get_doc(DOCTYPE_COMPANY_SUBSCRIPTION, self.sub_alpha_name)
        self.assertEqual(sub.status, "Active")

        # Verify Billing Transaction Created
        txn_name = frappe.db.get_value(DOCTYPE_BILLING_TRANSACTION, {"stripe_event_id": event_id}, "name")
        self.assertIsNotNone(txn_name)
        print("  -> checkout.session.completed event processed! Subscription active & transaction created.")

    def test_bill_12_invoice_paid_event(self):
        """BILL-12: Verify invoice.paid event updates subscription and creates payment transaction."""
        print("\n[BILL-12] Testing invoice.paid Event Handling...")
        event_id = "evt_inv_paid_30_12"
        event_payload = {
            "id": event_id,
            "type": "invoice.paid",
            "data": {
                "object": {
                    "id": "in_test_30_12",
                    "customer": "cus_phase30_alpha",
                    "subscription": "sub_phase30_alpha",
                    "amount_paid": 4900,
                    "currency": "usd",
                    "number": "INV-PHASE30-001",
                    "payment_intent": "pi_test_30_12",
                }
            },
        }
        svc = WebhookService()
        res = svc.handle_webhook_event(event_payload)
        self.assertEqual(res.get("status"), "success")

        sub = frappe.get_doc(DOCTYPE_COMPANY_SUBSCRIPTION, self.sub_alpha_name)
        self.assertEqual(sub.status, "Active")

        txn = frappe.get_doc(DOCTYPE_BILLING_TRANSACTION, res.get("transaction"))
        self.assertEqual(txn.payment_status, "Paid")
        self.assertEqual(txn.amount, 49.0)
        print("  -> invoice.paid event processed! Subscription renewed & paid transaction logged.")

    def test_bill_13_invoice_payment_failed_event(self):
        """BILL-13: Verify invoice.payment_failed event updates subscription status to Past Due."""
        print("\n[BILL-13] Testing invoice.payment_failed Event Handling...")
        event_id = "evt_inv_failed_30_13"
        event_payload = {
            "id": event_id,
            "type": "invoice.payment_failed",
            "data": {
                "object": {
                    "id": "in_test_30_13",
                    "customer": "cus_phase30_alpha",
                    "subscription": "sub_phase30_alpha",
                    "amount_due": 4900,
                    "currency": "usd",
                    "number": "INV-PHASE30-FAIL",
                    "last_finalization_error": {"message": "Card declined: insufficient funds"},
                }
            },
        }
        svc = WebhookService()
        res = svc.handle_webhook_event(event_payload)
        self.assertEqual(res.get("status"), "success")

        sub = frappe.get_doc(DOCTYPE_COMPANY_SUBSCRIPTION, self.sub_alpha_name)
        self.assertEqual(sub.status, "Past Due")

        # Restore status back to Active for subsequent tests
        sub.status = "Active"
        sub.save(ignore_permissions=True)
        frappe.db.commit()
        print("  -> invoice.payment_failed event processed! Status correctly updated to Past Due.")

    def test_bill_14_subscription_updated_event(self):
        """BILL-14: Verify customer.subscription.updated synchronizes subscription state."""
        print("\n[BILL-14] Testing customer.subscription.updated Event Handling...")
        event_id = "evt_sub_updated_30_14"
        event_payload = {
            "id": event_id,
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_phase30_alpha",
                    "customer": "cus_phase30_alpha",
                    "status": "trialing",
                    "cancel_at_period_end": True,
                }
            },
        }
        svc = WebhookService()
        res = svc.handle_webhook_event(event_payload)
        self.assertEqual(res.get("status"), "success")

        sub = frappe.get_doc(DOCTYPE_COMPANY_SUBSCRIPTION, self.sub_alpha_name)
        self.assertIn(sub.status, ["Trial", "Trialing"])
        self.assertEqual(sub.cancel_at_period_end, 1)

        # Restore for subsequent tests
        sub.status = "Active"
        sub.cancel_at_period_end = 0
        sub.save(ignore_permissions=True)
        frappe.db.commit()
        print("  -> customer.subscription.updated event processed! Trialing state synchronized.")

    def test_bill_15_subscription_deleted_event(self):
        """BILL-15: Verify customer.subscription.deleted event marks subscription as Cancelled."""
        print("\n[BILL-15] Testing customer.subscription.deleted Event Handling...")
        event_id = "evt_sub_deleted_30_15"
        event_payload = {
            "id": event_id,
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "id": "sub_phase30_alpha",
                    "customer": "cus_phase30_alpha",
                    "status": "canceled",
                }
            },
        }
        svc = WebhookService()
        res = svc.handle_webhook_event(event_payload)
        self.assertEqual(res.get("status"), "success")

        sub = frappe.get_doc(DOCTYPE_COMPANY_SUBSCRIPTION, self.sub_alpha_name)
        self.assertEqual(sub.status, "Cancelled")

        # Restore Active state for subsequent tests
        sub.status = "Active"
        sub.save(ignore_permissions=True)
        frappe.db.commit()
        print("  -> customer.subscription.deleted event processed! Subscription marked as Cancelled.")

    def test_bill_16_webhook_idempotency(self):
        """BILL-16: Verify identical webhook event sent twice returns ignored status on retry."""
        print("\n[BILL-16] Testing Webhook Event Idempotency...")
        event_id = "evt_idempotent_test_30_16"
        event_payload = {
            "id": event_id,
            "type": "invoice.paid",
            "data": {
                "object": {
                    "id": "in_test_30_16",
                    "customer": "cus_phase30_alpha",
                    "subscription": "sub_phase30_alpha",
                    "amount_paid": 4900,
                    "currency": "usd",
                }
            },
        }
        svc = WebhookService()
        # First Delivery
        res1 = svc.handle_webhook_event(event_payload)
        self.assertEqual(res1.get("status"), "success")

        # Second Duplicate Delivery
        res2 = svc.handle_webhook_event(event_payload)
        self.assertEqual(res2.get("status"), "ignored")
        self.assertEqual(res2.get("reason"), "duplicate_event")
        print("  -> Webhook idempotency verified! Duplicate event ignored.")

    def test_bill_17_duplicate_event_does_not_duplicate_transaction(self):
        """BILL-17: Verify duplicate webhook delivery does not insert duplicate Billing Transactions."""
        print("\n[BILL-17] Testing Transaction Deduplication...")
        event_id = "evt_dedup_txn_30_17"
        event_payload = {
            "id": event_id,
            "type": "invoice.paid",
            "data": {
                "object": {
                    "id": "in_test_30_17",
                    "customer": "cus_phase30_alpha",
                    "subscription": "sub_phase30_alpha",
                    "amount_paid": 4900,
                    "currency": "usd",
                }
            },
        }
        svc = WebhookService()
        initial_count = frappe.db.count(DOCTYPE_BILLING_TRANSACTION, {"company": "Phase30 Company Alpha"})

        svc.handle_webhook_event(event_payload)
        after_first = frappe.db.count(DOCTYPE_BILLING_TRANSACTION, {"company": "Phase30 Company Alpha"})
        self.assertEqual(after_first, initial_count + 1)

        svc.handle_webhook_event(event_payload)
        after_second = frappe.db.count(DOCTYPE_BILLING_TRANSACTION, {"company": "Phase30 Company Alpha"})
        self.assertEqual(after_second, after_first)
        print("  -> Transaction deduplication certified! No duplicate rows created.")

    def test_bill_18_cancellation_synchronization(self):
        """BILL-18: Verify cancel_subscription sets cancel_at_period_end on backend doc."""
        print("\n[BILL-18] Testing Server-Side Cancellation Synchronization...")
        res = cancel_subscription()
        self.assertTrue(res.get("success"))
        sub = frappe.get_doc(DOCTYPE_COMPANY_SUBSCRIPTION, self.sub_alpha_name)
        self.assertEqual(sub.cancel_at_period_end, 1)
        print("  -> Cancellation request synchronized server-side!")

    def test_bill_19_resume_synchronization(self):
        """BILL-19: Verify resume_subscription resets cancel_at_period_end on backend doc."""
        print("\n[BILL-19] Testing Server-Side Resume Synchronization...")
        res = resume_subscription()
        self.assertTrue(res.get("success"))
        sub = frappe.get_doc(DOCTYPE_COMPANY_SUBSCRIPTION, self.sub_alpha_name)
        self.assertEqual(sub.cancel_at_period_end, 0)
        print("  -> Resume request synchronized server-side!")

    def test_bill_20_usage_retrieval(self):
        """BILL-20: Verify get_subscription_usage returns quota counters and plan limits."""
        print("\n[BILL-20] Testing Subscription Usage Retrieval...")
        res = get_subscription_usage()
        self.assertTrue(res.get("success"))
        data = res.get("data", {})
        limits = data.get("limits", {})
        self.assertIn("max_active_jobs", limits)
        self.assertEqual(limits.get("max_active_jobs"), 5)
        print("  -> Usage quota counters and plan limits successfully retrieved!")

    def test_bill_21_usage_company_isolation(self):
        """BILL-21: Verify usage counters are isolated per tenant company."""
        print("\n[BILL-21] Testing Usage Counter Isolation...")
        svc = SubscriptionService()
        usage_alpha = svc.get_usage_with_limits("Phase30 Company Alpha")
        usage_beta = svc.get_usage_with_limits("Phase30 Company Beta")

        self.assertEqual(usage_alpha.get("subscription", {}).get("company"), "Phase30 Company Alpha")
        self.assertEqual(usage_beta.get("subscription", {}).get("company"), "Phase30 Company Beta")
        print("  -> Usage metrics strictly isolated per company tenant!")

    def test_bill_22_unauthenticated_request_rejected(self):
        """BILL-22: Verify guest requests to protected billing endpoints are rejected with 401/403."""
        print("\n[BILL-22] Testing Unauthenticated Access Rejection...")
        frappe.set_user("Guest")
        res = get_current_subscription()
        self.assertFalse(res.get("success"))
        self.assertIn(res.get("error", {}).get("code"), ["UNAUTHORIZED", "FORBIDDEN"])
        print("  -> Guest request correctly rejected with 401/403 UNAUTHORIZED!")


def run_standalone_tests():
    """Execution helper for running BILL-01 through BILL-22 directly within site context."""
    import unittest
    TestBillingPhase30.setUpClass()
    suite = unittest.TestLoader().loadTestsFromTestCase(TestBillingPhase30)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return {
        "wasSuccessful": result.wasSuccessful(),
        "testsRun": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
    }

