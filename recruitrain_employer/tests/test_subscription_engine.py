# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.tests.test_subscription_engine
=====================================================

Unit Test Suite for Subscription & Entitlement Engine.

Tests:
- Starter Plan quota enforcement (5 active jobs, 6th rejected, archive 1, create 6th success).
- Professional Plan quota enforcement (20 jobs allowed, 21st rejected).
- Unlimited Plan quota bypass (-1 / 0 limit never rejected).
- Automatic usage tracking (increment / decrement).
- Concurrent job creation safety.
- Downgrade safety validation.
- Expired subscription blocking.
- Cancelled subscription blocking.
- Trial expiration blocking.
"""

import sys
import unittest
import frappe
from frappe.utils import add_days, getdate, today

from recruitrain_employer.services.subscription_service import SubscriptionService, check_plan_limit
from recruitrain_employer.utils.constants import (
    DOCTYPE_COMPANY_SUBSCRIPTION,
    DOCTYPE_JOB_OPENING,
    DOCTYPE_SUBSCRIPTION_PLAN,
    DOCTYPE_SUBSCRIPTION_USAGE,
    JOB_STATUS_CLOSED,
    JOB_STATUS_OPEN,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_CANCELLED,
    SUBSCRIPTION_STATUS_EXPIRED,
    SUBSCRIPTION_STATUS_TRIAL,
)
from recruitrain_employer.utils.exceptions import (
    PlanLimitExceededError,
    SubscriptionExpiredError,
)


class TestSubscriptionEngine(unittest.TestCase):
    """Headless Unit Test Suite for Subscription and Entitlement Engine."""

    @classmethod
    def setUpClass(cls):
        """Initialize Frappe environment and seed test company & subscription plans."""
        frappe.init(site="development.localhost", sites_path="./sites")
        frappe.connect()
        frappe.clear_cache()
        frappe.reload_doctype("Company Subscription")
        frappe.reload_doctype("Subscription_Plan_Recruitrain")

        try:
            from recruitrain_employer.services.master_seed_service import ensure_master_records_exist
            ensure_master_records_exist()
        except Exception:
            pass

        cls.test_company = "Test Subscription Enterprise Co"
        cls.service = SubscriptionService()

        # Seed Test Company
        if not frappe.db.exists("Company", cls.test_company):
            comp = frappe.new_doc("Company")
            comp.company_name = cls.test_company
            comp.status = "Active"
            comp.email = "sub_test@enterprise.com"
            comp.phone = "+14155552671"
            comp.address_line_1 = "100 Tech Blvd"
            comp.industry = "Technology"
            comp.insert(ignore_permissions=True)
            frappe.db.commit()

        # Seed Test Subscription Plans
        cls._create_plan("Test Starter Plan", max_jobs=5, max_rec=2, max_cand=200, price=999)
        cls._create_plan("Test Professional Plan", max_jobs=20, max_rec=10, max_cand=5000, price=4999)
        cls._create_plan("Test Unlimited Plan", max_jobs=-1, max_rec=-1, max_cand=-1, price=9999)

    @classmethod
    def _create_plan(cls, plan_name: str, max_jobs: int, max_rec: int, max_cand: int, price: float):
        if frappe.db.exists(DOCTYPE_SUBSCRIPTION_PLAN, plan_name):
            doc = frappe.get_doc(DOCTYPE_SUBSCRIPTION_PLAN, plan_name)
        else:
            doc = frappe.new_doc(DOCTYPE_SUBSCRIPTION_PLAN)
            doc.plan_name = plan_name

        doc.description = f"Unit Test Plan: {plan_name}"
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
        doc.stripe_product_id = f"prod_{plan_name.lower().replace(' ', '_')}"
        doc.save(ignore_permissions=True)
        frappe.db.commit()

    def setUp(self):
        """Reset test company subscriptions, jobs, and usage before each test."""
        # Cleanup existing jobs for test company
        frappe.db.sql("DELETE FROM `tabJob Opening` WHERE `company` = %s", (self.test_company,))
        frappe.db.sql("DELETE FROM `tabCompany Subscription` WHERE `company` = %s", (self.test_company,))
        frappe.db.sql("DELETE FROM `tabSubscription Usage` WHERE `company` = %s", (self.test_company,))
        frappe.db.commit()

        # Set active context to Starter Plan
        self._set_company_subscription("Test Starter Plan", SUBSCRIPTION_STATUS_ACTIVE)

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
        job.job_code = f"JOB-TEST-{frappe.generate_hash(length=8).upper()}"
        job.company = self.test_company
        job.status = status
        job.published = 1 if status == JOB_STATUS_OPEN else 0
        job.number_of_openings = 1
        job.job_summary = "Unit test job description"
        job.responsibilities = "Unit test job responsibilities"
        job.requirements = "Unit test job requirements"
        job.employment_type = "Full Time"
        job.flags.ignore_mandatory = True
        job.insert(ignore_permissions=True)
        frappe.db.commit()
        return job

    # ------------------------------------------------------------------
    # Test Cases
    # ------------------------------------------------------------------

    def test_1_starter_plan_job_limit(self):
        """Test Starter Plan allows 5 jobs, 6th fails with PlanLimitExceededError, archive 1 allows 6th."""
        print("\n[TEST 1] Testing Starter Plan Job Quota (Limit 5)...")
        
        jobs = []
        for i in range(1, 6):
            job = self._create_test_job(f"Starter Job #{i}")
            jobs.append(job)

        usage = self.service.get_usage(self.test_company)
        self.assertEqual(usage.current_active_jobs, 5)
        print("  -> 5 jobs created successfully. Current active count: 5")

        # 6th Job Attempt must raise PlanLimitExceededError
        with self.assertRaises(PlanLimitExceededError) as ctx:
            self._create_test_job("Starter Job #6 - Should Fail")

        self.assertIn("Plan limit exceeded", str(ctx.exception))
        self.assertEqual(ctx.exception.resource, "active_jobs")
        print("  -> 6th job correctly rejected with PlanLimitExceededError!")

        # Close/Archive 1 job
        first_job = jobs[0]
        first_job.status = JOB_STATUS_CLOSED
        first_job.save(ignore_permissions=True)
        frappe.db.commit()

        usage = self.service.get_usage(self.test_company)
        self.assertEqual(usage.current_active_jobs, 4)
        print("  -> 1 job closed. Active count updated to: 4")

        # Now creating 6th job must succeed!
        job6 = self._create_test_job("Starter Job #6 - Retry Success")
        self.assertIsNotNone(job6.name)
        
        usage = self.service.get_usage(self.test_company)
        self.assertEqual(usage.current_active_jobs, 5)
        print("  -> 6th job retry after closing succeeded! Total active count: 5")

    def test_2_professional_plan_job_limit(self):
        """Test Professional Plan allows 20 jobs, 21st fails."""
        print("\n[TEST 2] Testing Professional Plan Job Quota (Limit 20)...")
        self._set_company_subscription("Test Professional Plan", SUBSCRIPTION_STATUS_ACTIVE)

        for i in range(1, 21):
            self._create_test_job(f"Pro Job #{i}")

        usage = self.service.get_usage(self.test_company)
        self.assertEqual(usage.current_active_jobs, 20)
        print("  -> 20 jobs created successfully on Professional Plan!")

        with self.assertRaises(PlanLimitExceededError):
            self._create_test_job("Pro Job #21 - Should Fail")

        print("  -> 21st job attempt correctly rejected!")

    def test_3_unlimited_plan(self):
        """Test Unlimited Plan (-1 limit) never rejects job creation."""
        print("\n[TEST 3] Testing Unlimited Plan Quota...")
        self._set_company_subscription("Test Unlimited Plan", SUBSCRIPTION_STATUS_ACTIVE)

        for i in range(1, 25):
            self._create_test_job(f"Unlimited Job #{i}")

        usage = self.service.get_usage(self.test_company)
        self.assertEqual(usage.current_active_jobs, 24)
        print("  -> 24 jobs created without rejection on Unlimited Plan!")

    def test_4_usage_counters_increment_decrement(self):
        """Test atomic increment and decrement service methods."""
        print("\n[TEST 4] Testing Usage Counters Increment & Decrement...")
        
        self.service.increment_usage(self.test_company, "active_jobs", 3)
        usage = self.service.get_usage(self.test_company)
        self.assertEqual(usage.current_active_jobs, 3)

        self.service.decrement_usage(self.test_company, "active_jobs", 2)
        usage = self.service.get_usage(self.test_company)
        self.assertEqual(usage.current_active_jobs, 1)

        self.service.decrement_usage(self.test_company, "active_jobs", 10)
        usage = self.service.get_usage(self.test_company)
        self.assertEqual(usage.current_active_jobs, 0)
        print("  -> Usage counter increments, decrements, and floor at 0 verified!")

    def test_5_concurrent_job_creation(self):
        """Test sequential quota check safety under high frequency job additions."""
        print("\n[TEST 5] Testing High-Frequency Sequential Quota Safety...")
        
        # Max limit is 5
        count_success = 0
        count_rejected = 0

        for i in range(1, 9):
            try:
                self._create_test_job(f"Concurrent Job {i}")
                count_success += 1
            except PlanLimitExceededError:
                count_rejected += 1

        self.assertEqual(count_success, 5)
        self.assertEqual(count_rejected, 3)
        print(f"  -> Quota safety verified! Successes: {count_success}, Rejected: {count_rejected}")

    def test_6_downgrade_safety(self):
        """Test downgrade preview detects when current usage exceeds target plan limits."""
        print("\n[TEST 6] Testing Downgrade Safety Validation...")
        self._set_company_subscription("Test Professional Plan", SUBSCRIPTION_STATUS_ACTIVE)

        # Create 10 active jobs (Professional allows 20, but Starter allows only 5)
        for i in range(1, 11):
            self._create_test_job(f"Pro Job #{i}")

        preview = self.service.preview_upgrade(self.test_company, "Test Starter Plan")
        self.assertTrue(preview["is_downgrade"])
        self.assertFalse(preview["can_change"])
        self.assertTrue(len(preview["downgrade_violations"]) > 0)
        print(f"  -> Downgrade blocked safely! Violation detected: {preview['downgrade_violations'][0]}")

    def test_7_expired_subscription(self):
        """Test operation blocking when subscription status is Expired."""
        print("\n[TEST 7] Testing Expired Subscription...")
        self._set_company_subscription("Test Starter Plan", SUBSCRIPTION_STATUS_EXPIRED)

        with self.assertRaises(SubscriptionExpiredError) as ctx:
            check_plan_limit(self.test_company, "active_jobs")

        self.assertIn("Subscription is Expired", str(ctx.exception))
        print("  -> Operations blocked correctly for Expired subscription!")

    def test_8_cancelled_subscription(self):
        """Test operation blocking when subscription status is Cancelled."""
        print("\n[TEST 8] Testing Cancelled Subscription...")
        self._set_company_subscription("Test Starter Plan", SUBSCRIPTION_STATUS_CANCELLED)

        with self.assertRaises(SubscriptionExpiredError) as ctx:
            check_plan_limit(self.test_company, "active_jobs")

        self.assertIn("Subscription is Cancelled", str(ctx.exception))
        print("  -> Operations blocked correctly for Cancelled subscription!")

    def test_9_trial_expiration(self):
        """Test trial expiration when current date > trial end date."""
        print("\n[TEST 9] Testing Trial Expiration...")
        past_end_date = add_days(today(), -5)
        self._set_company_subscription("Test Starter Plan", SUBSCRIPTION_STATUS_TRIAL, end_date=past_end_date)

        with self.assertRaises(SubscriptionExpiredError) as ctx:
            check_plan_limit(self.test_company, "active_jobs")

        print("  -> Expired trial correctly blocked with SubscriptionExpiredError!")


def run_subscription_tests():
    """Execution wrapper for headless unit test runner."""
    print("--- Starting RecruitTrain Subscription & Entitlement Engine Test Suite ---")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestSubscriptionEngine)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if result.wasSuccessful():
        print("\n--- ALL SUBSCRIPTION ENGINE TESTS PASSED SUCCESSFULLY! ---")
        sys.exit(0)
    else:
        print("\n--- SUBSCRIPTION ENGINE TESTS FAILED ---")
        sys.exit(1)


if __name__ == "__main__":
    run_subscription_tests()
