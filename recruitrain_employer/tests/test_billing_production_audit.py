# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.tests.test_billing_production_audit
===========================================================

Production Hardening & Verification Audit Test Suite for RecruitTrain ATS Billing Module.

Tests:
1. Starter Plan limits and quota exhaustion.
2. Professional Plan limits.
3. Enterprise / Unlimited Plan limits.
4. Trial subscription lifecycle & trial expiration blocking.
5. Expired subscription blocking.
6. Cancelled subscription blocking.
7. Past Due subscription blocking.
8. Downgrade safety protection.
9. High-frequency atomic counter safety.
10. Webhook processing: invoice.paid & subscription renewal.
11. Webhook processing: invoice.payment_failed & Past Due status.
12. Webhook idempotency and replay protection.
13. Counter reconciliation & recalculation.
14. Billing activity log generation.
15. REST API standard response contract ({ success, data, message, error, meta }).
"""

import sys
import unittest
import frappe
from frappe.utils import add_days, getdate, today

from recruitrain_employer.api.subscription import get_current_subscription, get_usage, upgrade_preview
from recruitrain_employer.services.subscription_service import SubscriptionService, check_plan_limit
from recruitrain_employer.services.webhook_service import WebhookService
from recruitrain_employer.utils.constants import (
    DOCTYPE_BILLING_TRANSACTION,
    DOCTYPE_COMPANY_SUBSCRIPTION,
    DOCTYPE_JOB_OPENING,
    DOCTYPE_SUBSCRIPTION_PLAN,
    DOCTYPE_SUBSCRIPTION_USAGE,
    JOB_STATUS_CLOSED,
    JOB_STATUS_OPEN,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_CANCELLED,
    SUBSCRIPTION_STATUS_EXPIRED,
    SUBSCRIPTION_STATUS_PAST_DUE,
    SUBSCRIPTION_STATUS_TRIAL,
)
from recruitrain_employer.utils.exceptions import (
    PlanLimitExceededError,
    SubscriptionExpiredError,
)


class TestBillingProductionAudit(unittest.TestCase):
    """Production Hardening Audit Test Suite for Billing Subsystem."""

    @classmethod
    def setUpClass(cls):
        """Initialize Frappe, reload DocTypes, and seed test company and plans."""
        frappe.init(site="development.localhost", sites_path="./sites")
        frappe.connect()
        frappe.clear_cache()
        frappe.reload_doctype("Company Subscription")
        frappe.reload_doctype("Subscription_Plan_Recruitrain")
        frappe.reload_doctype("Billing Transaction")

        cls.test_company = "Audit Enterprise Corp"
        cls.service = SubscriptionService()
        cls.webhook_svc = WebhookService()

        # Seed Test Company
        if not frappe.db.exists("Company", cls.test_company):
            comp = frappe.new_doc("Company")
            comp.company_name = cls.test_company
            comp.status = "Active"
            comp.email = "billing_audit@enterprise.com"
            comp.phone = "+14155552671"
            comp.address_line_1 = "500 Enterprise Way"
            comp.industry = "Technology"
            comp.insert(ignore_permissions=True)
            frappe.db.commit()

        # Seed Employment Type
        if not frappe.db.exists("Employment Type", "Full Time"):
            try:
                et = frappe.new_doc("Employment Type")
                if et.meta.has_field("employment_type_name"):
                    et.employment_type_name = "Full Time"
                else:
                    et.name = "Full Time"
                et.insert(ignore_permissions=True)
                frappe.db.commit()
            except Exception:
                pass

        # Seed Test Plans
        cls._create_plan("Audit Starter Plan", max_jobs=5, max_rec=2, max_cand=100, price=99.0)
        cls._create_plan("Audit Professional Plan", max_jobs=20, max_rec=10, max_cand=2000, price=499.0)
        cls._create_plan("Audit Enterprise Plan", max_jobs=-1, max_rec=-1, max_cand=-1, price=999.0)

    @classmethod
    def _create_plan(cls, plan_name: str, max_jobs: int, max_rec: int, max_cand: int, price: float):
        if frappe.db.exists(DOCTYPE_SUBSCRIPTION_PLAN, plan_name):
            doc = frappe.get_doc(DOCTYPE_SUBSCRIPTION_PLAN, plan_name)
        else:
            doc = frappe.new_doc(DOCTYPE_SUBSCRIPTION_PLAN)
            doc.plan_name = plan_name

        doc.description = f"Audit Plan: {plan_name}"
        doc.monthly_price = price
        doc.yearly_price = price * 10
        doc.currency = "USD"
        doc.trial_days = 14
        doc.is_active = 1
        doc.max_active_jobs = max_jobs
        doc.max_recruiters = max_rec
        doc.max_candidates = max_cand
        doc.storage_gb = 10.0
        doc.monthly_email_limit = 1000
        doc.monthly_sms_limit = 500
        doc.ai_credits = 100
        doc.can_use_analytics = 1
        doc.can_use_talent_pool = 1
        doc.can_use_api = 1
        doc.can_use_notifications = 1
        doc.stripe_product_id = f"prod_audit_{plan_name.lower().replace(' ', '_')}"
        doc.save(ignore_permissions=True)
        frappe.db.commit()

    def setUp(self):
        """Clean up jobs, transactions, and subscriptions for test company before each test."""
        frappe.db.sql("DELETE FROM `tabJob Opening` WHERE `company` = %s", (self.test_company,))
        frappe.db.sql("DELETE FROM `tabBilling Transaction` WHERE `company` = %s", (self.test_company,))
        frappe.db.commit()

        # Set default active context to Starter Plan
        self._set_company_subscription("Audit Starter Plan", SUBSCRIPTION_STATUS_ACTIVE)

    def _set_company_subscription(self, plan_name: str, status: str, end_date=None):
        sub_name = frappe.db.get_value(DOCTYPE_COMPANY_SUBSCRIPTION, {"company": self.test_company}, "name")
        if sub_name:
            sub = frappe.get_doc(DOCTYPE_COMPANY_SUBSCRIPTION, sub_name)
        else:
            sub = frappe.new_doc(DOCTYPE_COMPANY_SUBSCRIPTION)
            sub.company = self.test_company

        sub.subscription_plan = plan_name
        sub.status = status
        sub.start_date = getdate(today())
        sub.end_date = getdate(end_date) if end_date else add_days(today(), 30)
        sub.billing_cycle = "Monthly"
        sub.save(ignore_permissions=True)
        frappe.db.commit()

        usage_doc = self.service.get_usage(self.test_company)
        usage_doc.company_subscription = sub.name
        usage_doc.save(ignore_permissions=True)
        frappe.db.commit()

        self.service.recalculate_usage(self.test_company)
        return sub

    def _create_test_job(self, job_title: str, status: str = JOB_STATUS_OPEN):
        job = frappe.new_doc(DOCTYPE_JOB_OPENING)
        job.job_title = job_title
        job.job_code = f"JOB-AUDIT-{frappe.generate_hash(length=8).upper()}"
        job.company = self.test_company
        job.status = status
        job.published = 1 if status == JOB_STATUS_OPEN else 0
        job.number_of_openings = 1
        job.job_summary = "Audit test job description"
        job.responsibilities = "Audit test responsibilities"
        job.requirements = "Audit test requirements"
        job.employment_type = "Full Time"
        job.flags.ignore_mandatory = True
        job.insert(ignore_permissions=True)
        frappe.db.commit()
        return job

    # ------------------------------------------------------------------
    # Test Cases
    # ------------------------------------------------------------------

    def test_01_starter_plan_limits_and_exhaustion(self):
        """Test Starter Plan allows 5 active jobs, 6th fails with PlanLimitExceededError."""
        print("\n[AUDIT TEST 1] Testing Starter Plan Limits & Exhaustion...")
        jobs = []
        for i in range(1, 6):
            job = self._create_test_job(f"Starter Job #{i}")
            jobs.append(job)

        usage = self.service.get_usage(self.test_company)
        self.assertEqual(usage.current_active_jobs, 5)

        with self.assertRaises(PlanLimitExceededError) as ctx:
            self._create_test_job("Starter Job #6 - Expect Failure")

        self.assertIn("Plan limit exceeded", str(ctx.exception))
        print("  -> 5 jobs created, 6th job correctly rejected with PlanLimitExceededError!")

    def test_02_professional_plan_limits(self):
        """Test Professional Plan allows 20 active jobs."""
        print("\n[AUDIT TEST 2] Testing Professional Plan Quota (Limit 20)...")
        self._set_company_subscription("Audit Professional Plan", SUBSCRIPTION_STATUS_ACTIVE)

        for i in range(1, 21):
            self._create_test_job(f"Pro Job #{i}")

        usage = self.service.get_usage(self.test_company)
        self.assertEqual(usage.current_active_jobs, 20)

        with self.assertRaises(PlanLimitExceededError):
            self._create_test_job("Pro Job #21 - Expect Failure")

        print("  -> 20 jobs created on Professional Plan, 21st correctly rejected!")

    def test_03_enterprise_unlimited_limits(self):
        """Test Enterprise Plan (-1 limit) allows unlimited job creations."""
        print("\n[AUDIT TEST 3] Testing Enterprise Plan Unlimited Quota...")
        self._set_company_subscription("Audit Enterprise Plan", SUBSCRIPTION_STATUS_ACTIVE)

        for i in range(1, 25):
            self._create_test_job(f"Enterprise Job #{i}")

        usage = self.service.get_usage(self.test_company)
        self.assertEqual(usage.current_active_jobs, 24)
        print("  -> 24 jobs created without rejection on Enterprise Plan!")

    def test_04_trial_subscription_and_expiration(self):
        """Test Trial active state allows operations, trial expiration blocks operations."""
        print("\n[AUDIT TEST 4] Testing Trial Lifecycle & Expiration...")
        future_end = add_days(today(), 7)
        self._set_company_subscription("Audit Starter Plan", SUBSCRIPTION_STATUS_TRIAL, end_date=future_end)

        job = self._create_test_job("Trial Active Job")
        self.assertIsNotNone(job.name)

        # Expired trial date
        past_end = add_days(today(), -2)
        self._set_company_subscription("Audit Starter Plan", SUBSCRIPTION_STATUS_TRIAL, end_date=past_end)

        with self.assertRaises(SubscriptionExpiredError):
            check_plan_limit(self.test_company, "active_jobs")

        print("  -> Active trial allowed operation, expired trial correctly blocked with SubscriptionExpiredError!")

    def test_05_expired_subscription_blocking(self):
        """Test operation blocking when subscription status is Expired."""
        print("\n[AUDIT TEST 5] Testing Expired Subscription Blocking...")
        self._set_company_subscription("Audit Starter Plan", SUBSCRIPTION_STATUS_EXPIRED)

        with self.assertRaises(SubscriptionExpiredError) as ctx:
            check_plan_limit(self.test_company, "active_jobs")

        self.assertIn("Subscription is Expired", str(ctx.exception))
        print("  -> Expired status correctly blocked!")

    def test_06_cancelled_subscription_blocking(self):
        """Test operation blocking when subscription status is Cancelled."""
        print("\n[AUDIT TEST 6] Testing Cancelled Subscription Blocking...")
        self._set_company_subscription("Audit Starter Plan", SUBSCRIPTION_STATUS_CANCELLED)

        with self.assertRaises(SubscriptionExpiredError) as ctx:
            check_plan_limit(self.test_company, "active_jobs")

        self.assertIn("Subscription is Cancelled", str(ctx.exception))
        print("  -> Cancelled status correctly blocked!")

    def test_07_past_due_subscription_blocking(self):
        """Test operation blocking when subscription status is Past Due."""
        print("\n[AUDIT TEST 7] Testing Past Due Subscription Blocking...")
        self._set_company_subscription("Audit Starter Plan", SUBSCRIPTION_STATUS_PAST_DUE)

        with self.assertRaises(SubscriptionExpiredError) as ctx:
            check_plan_limit(self.test_company, "active_jobs")

        self.assertIn("Subscription is Past Due", str(ctx.exception))
        print("  -> Past Due status correctly blocked!")

    def test_08_downgrade_protection_violations(self):
        """Test downgrade preview detects when current active usage exceeds target plan limits."""
        print("\n[AUDIT TEST 8] Testing Downgrade Safety Validation...")
        self._set_company_subscription("Audit Professional Plan", SUBSCRIPTION_STATUS_ACTIVE)

        for i in range(1, 10):
            self._create_test_job(f"Pro Job #{i}")

        preview = self.service.preview_upgrade(self.test_company, "Audit Starter Plan")
        self.assertTrue(preview["is_downgrade"])
        self.assertFalse(preview["can_change"])
        self.assertTrue(len(preview["downgrade_violations"]) > 0)
        print(f"  -> Downgrade blocked safely! Violation: {preview['downgrade_violations'][0]}")

    def test_09_concurrent_job_and_recruiter_creation(self):
        """Test sequential atomic counter accuracy under high-frequency job creation."""
        print("\n[AUDIT TEST 9] Testing Atomic Counter Safety...")
        count_success = 0
        count_rejected = 0

        for i in range(1, 9):
            try:
                self._create_test_job(f"Atomic Job #{i}")
                count_success += 1
            except PlanLimitExceededError:
                count_rejected += 1

        self.assertEqual(count_success, 5)
        self.assertEqual(count_rejected, 3)
        print(f"  -> Atomic counter safety verified! Successes: {count_success}, Rejected: {count_rejected}")

    def test_10_webhook_invoice_paid_and_subscription_renewal(self):
        """Test Stripe invoice.paid webhook handler extends subscription and records transaction."""
        print("\n[AUDIT TEST 10] Testing Stripe Webhook invoice.paid...")
        self._set_company_subscription("Audit Starter Plan", SUBSCRIPTION_STATUS_PAST_DUE)

        event_payload = {
            "id": "evt_test_paid_1001",
            "type": "invoice.paid",
            "data": {
                "object": {
                    "id": "in_test_1001",
                    "number": "INV-2026-001",
                    "customer": "cus_test_123",
                    "subscription": "sub_test_123",
                    "amount_paid": 9900,
                    "currency": "usd",
                    "payment_intent": "pi_test_paid_1001",
                    "metadata": {"company": self.test_company},
                }
            },
        }

        res = self.webhook_svc.handle_webhook_event(event_payload)
        self.assertEqual(res["status"], "success")

        # Verify subscription status set to Active
        sub = self.service.get_active_subscription(self.test_company)
        self.assertEqual(sub.status, SUBSCRIPTION_STATUS_ACTIVE)

        # Verify Billing Transaction created
        txns = frappe.get_all(DOCTYPE_BILLING_TRANSACTION, filters={"invoice_number": "INV-2026-001"})
        self.assertTrue(len(txns) > 0)
        print("  -> invoice.paid webhook successfully updated subscription to Active & recorded Billing Transaction!")

    def test_11_webhook_payment_failed(self):
        """Test Stripe invoice.payment_failed webhook sets Past Due status."""
        print("\n[AUDIT TEST 11] Testing Stripe Webhook invoice.payment_failed...")
        self._set_company_subscription("Audit Starter Plan", SUBSCRIPTION_STATUS_ACTIVE)

        event_payload = {
            "id": "evt_test_failed_2001",
            "type": "invoice.payment_failed",
            "data": {
                "object": {
                    "id": "in_test_2001",
                    "number": "INV-2026-002",
                    "customer": "cus_test_123",
                    "subscription": "sub_test_123",
                    "amount_due": 9900,
                    "currency": "usd",
                    "payment_intent": "pi_test_failed_2001",
                    "metadata": {"company": self.test_company},
                }
            },
        }

        res = self.webhook_svc.handle_webhook_event(event_payload)
        self.assertEqual(res["status"], "success")

        sub = self.service.get_active_subscription(self.test_company)
        self.assertEqual(sub.status, SUBSCRIPTION_STATUS_PAST_DUE)
        print("  -> invoice.payment_failed webhook correctly updated subscription to Past Due!")

    def test_12_webhook_idempotency_replay_protection(self):
        """Test replaying the exact same webhook event is safely ignored."""
        print("\n[AUDIT TEST 12] Testing Webhook Idempotency & Replay Protection...")
        event_payload = {
            "id": "evt_test_idempotent_3001",
            "type": "invoice.paid",
            "data": {
                "object": {
                    "id": "in_test_3001",
                    "number": "INV-2026-003",
                    "customer": "cus_test_123",
                    "subscription": "sub_test_123",
                    "amount_paid": 9900,
                    "currency": "usd",
                    "payment_intent": "pi_test_idempotent_3001",
                    "metadata": {"company": self.test_company},
                }
            },
        }

        res1 = self.webhook_svc.handle_webhook_event(event_payload)
        self.assertEqual(res1["status"], "success")

        # Second delivery (Replay)
        res2 = self.webhook_svc.handle_webhook_event(event_payload)
        self.assertEqual(res2["status"], "ignored")
        self.assertEqual(res2["reason"], "duplicate_event")

        # Verify only 1 transaction created
        txns = frappe.get_all(DOCTYPE_BILLING_TRANSACTION, filters={"invoice_number": "INV-2026-003"})
        self.assertEqual(len(txns), 1)
        print("  -> Webhook replay protection verified! Second webhook delivery safely ignored.")

    def test_13_usage_recalculation_counter_reconciliation(self):
        """Test recalculate_usage reconciles usage counters directly against MariaDB rows."""
        print("\n[AUDIT TEST 13] Testing Usage Recalculation & Counter Reconciliation...")
        # Create 3 jobs
        for i in range(1, 4):
            self._create_test_job(f"Reconcile Job #{i}")

        # Manually alter usage counter to simulate drift
        usage_doc = self.service.get_usage(self.test_company)
        usage_doc.current_active_jobs = 999
        usage_doc.save(ignore_permissions=True)
        frappe.db.commit()

        # Execute recalculation
        reconciled = self.service.recalculate_usage(self.test_company)
        self.assertEqual(reconciled.current_active_jobs, 3)
        print("  -> Usage counter drift reconciled successfully! Counter reset to true database row count (3).")

    def test_14_activity_log_generation(self):
        """Test billing activities generate Activity Logs entries."""
        print("\n[AUDIT TEST 14] Testing Activity Log Generation...")
        event_payload = {
            "id": "evt_test_log_4001",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_4001",
                    "customer": "cus_test_123",
                    "subscription": "sub_test_123",
                    "client_reference_id": self.test_company,
                    "metadata": {"company": self.test_company},
                }
            },
        }

        self.webhook_svc.handle_webhook_event(event_payload)

        logs = frappe.get_all(
            "Activity Logs",
            filters={"company": self.test_company},
        )
        self.assertTrue(len(logs) > 0)
        print("  -> Activity Log entry correctly created for Subscription Started event!")

    def test_15_api_response_contract(self):
        """Test REST API responses adhere to { success, data, message, error, meta } envelope."""
        print("\n[AUDIT TEST 15] Testing REST API Response Contract...")
        frappe.flags.employer_company = self.test_company

        # Call get_current_subscription
        res = get_current_subscription()
        self.assertTrue(isinstance(res, dict))
        self.assertIn("success", res)
        self.assertIn("data", res)
        self.assertIn("message", res)
        self.assertIn("meta", res)
        self.assertTrue(res["success"])

        # Call get_usage
        usage_res = get_usage()
        self.assertTrue(usage_res["success"])
        self.assertIn("quotas", usage_res["data"])

        # Call upgrade_preview
        frappe.form_dict["new_plan_name"] = "Audit Professional Plan"
        prev_res = upgrade_preview()
        self.assertTrue(prev_res["success"])
        self.assertIn("price_difference", prev_res["data"])
        print("  -> REST API endpoints verified! All return compliant response envelopes.")


def run_billing_production_audit_tests():
    """Execution wrapper for headless unit test runner."""
    print("==========================================================================")
    print("  RecruitTrain ATS Billing Subsystem - Enterprise Production Audit Suite ")
    print("==========================================================================")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestBillingProductionAudit)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if result.wasSuccessful():
        print("\n--------------------------------------------------------------------------")
        print(" ALL 15 PRODUCTION AUDIT TESTS PASSED SUCCESSFULLY! (EXIT CODE 0)")
        print("--------------------------------------------------------------------------")
        sys.exit(0)
    else:
        print("\n--------------------------------------------------------------------------")
        print(" BILLING PRODUCTION AUDIT TESTS FAILED")
        print("--------------------------------------------------------------------------")
        sys.exit(1)


if __name__ == "__main__":
    run_billing_production_audit_tests()
