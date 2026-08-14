# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.tests.test_billing_phase23
=================================================

Phase 23 Real Data Audit and Contract Test Suite for RecruitTrain ATS Billing Module.

Tests:
- TEST 01: Authenticated billing access
- TEST 02: Correct company resolved from session
- TEST 03: Billing data comes from real database
- TEST 04: Subscription data parity
- TEST 05: Plan data parity
- TEST 06: Usage data parity
- TEST 07: Invoice data parity
- TEST 08: Payment data parity
- TEST 09: Company isolation
- TEST 10: Cross-company access blocked
- TEST 11: No secrets or payment credentials exposed
- TEST 12: Standard ATS response envelope ({ success, data, message, error, meta })
- TEST 13: Repeated request consistency
- TEST 14: No mock/demo values returned by backend
"""

import sys
import unittest
import frappe
from frappe.utils import add_days, getdate, today

from recruitrain_employer.api.subscription import (
    get_available_plans,
    get_billing_overview,
    get_current_subscription,
    get_invoices,
    get_payment_history,
    get_usage,
    upgrade_preview,
)
from recruitrain_employer.services.subscription_service import SubscriptionService
from recruitrain_employer.utils.constants import (
    DOCTYPE_BILLING_TRANSACTION,
    DOCTYPE_COMPANY_SUBSCRIPTION,
    DOCTYPE_SUBSCRIPTION_PLAN,
    DOCTYPE_SUBSCRIPTION_USAGE,
    SUBSCRIPTION_STATUS_ACTIVE,
)
from recruitrain_employer.utils.exceptions import ATSCompanyNotFoundError, ATSPermissionError
from recruitrain_employer.utils.permissions import get_current_company, get_current_employer_user


class TestBillingPhase23(unittest.TestCase):
    """Phase 23 Billing Audit & Contract Verification Test Suite."""

    @classmethod
    def setUpClass(cls):
        """Initialize Frappe, reload DocTypes, and seed two isolated test companies."""
        frappe.init(site="development.localhost", sites_path="./sites")
        frappe.connect()
        frappe.clear_cache()
        frappe.reload_doctype("Company Subscription")
        frappe.reload_doctype("Subscription_Plan_Recruitrain")
        frappe.reload_doctype("Subscription Usage")
        frappe.reload_doctype("Billing Transaction")

        cls.service = SubscriptionService()

        # Seed Primary Test Company A
        cls.company_a = "Phase23 Company Alpha"
        cls.user_a_email = "employer_alpha_p23@test.com"
        cls._create_test_company(cls.company_a, cls.user_a_email)

        # Seed Secondary Test Company B (for Isolation & Cross-Tenant testing)
        cls.company_b = "Phase23 Company Beta"
        cls.user_b_email = "employer_beta_p23@test.com"
        cls._create_test_company(cls.company_b, cls.user_b_email)

        # Seed Base Subscription Plan
        cls.plan_name = "Phase23 Starter Plan"
        cls._create_test_plan(cls.plan_name, price=199.0)

    @classmethod
    def _create_test_company(cls, company_name: str, user_email: str):
        """Helper to create test Company, User, and Employer User records."""
        if not frappe.db.exists("Company", company_name):
            comp = frappe.new_doc("Company")
            comp.company_name = company_name
            comp.status = "Active"
            comp.email = user_email
            comp.phone = "+14155552671"
            comp.address_line_1 = "100 Test Way"
            comp.insert(ignore_permissions=True)

        if not frappe.db.exists("User", user_email):
            user = frappe.new_doc("User")
            user.email = user_email
            user.first_name = company_name
            user.enabled = 1
            user.insert(ignore_permissions=True)

        if not frappe.db.exists("Employer User", {"user": user_email}):
            emp_user = frappe.new_doc("Employer User")
            emp_user.user = user_email
            emp_user.company = company_name
            emp_user.role = "Administrator"
            emp_user.status = "Active"
            emp_user.insert(ignore_permissions=True)

        frappe.db.commit()

    @classmethod
    def _create_test_plan(cls, plan_name: str, price: float):
        """Helper to create test Subscription Plan."""
        if not frappe.db.exists(DOCTYPE_SUBSCRIPTION_PLAN, plan_name):
            plan = frappe.new_doc(DOCTYPE_SUBSCRIPTION_PLAN)
            plan.plan_name = plan_name
            plan.description = f"Phase 23 Test Plan: {plan_name}"
            plan.monthly_price = price
            plan.yearly_price = price * 10
            plan.currency = "USD"
            plan.trial_days = 14
            plan.is_active = 1
            plan.max_active_jobs = 10
            plan.max_recruiters = 3
            plan.max_candidates = 500
            plan.storage_gb = 5.0
            plan.stripe_product_id = f"prod_p23_{plan_name.lower().replace(' ', '_')}"
            plan.insert(ignore_permissions=True)
            frappe.db.commit()

    def setUp(self):
        """Set session context to Company Alpha before each test."""
        frappe.session.user = self.user_a_email
        frappe.flags.employer_company = self.company_a
        frappe.clear_cache()

    def tearDown(self):
        """Clean up test flags after each test."""
        frappe.flags.employer_company = None

    # ------------------------------------------------------------------
    # Test Cases
    # ------------------------------------------------------------------

    def test_01_authenticated_billing_access(self):
        """TEST 01: Verify authenticated billing access works and guest access is rejected."""
        print("\n[PHASE 23 TEST 01] Authenticated Billing Access...")
        # 1. Guest request must be blocked
        frappe.session.user = "Guest"
        frappe.flags.employer_company = None
        
        res = get_current_subscription()
        self.assertFalse(res.get("success", False))
        err_code = res.get("error", {}).get("code") if isinstance(res.get("error"), dict) else res.get("code")
        self.assertIn(err_code, ["UNAUTHORIZED", "PERMISSION_DENIED"])
        print("  -> Guest request correctly rejected with 401/403 UNAUTHORIZED!")

        # 2. Authenticated user request succeeds
        frappe.session.user = self.user_a_email
        frappe.flags.employer_company = self.company_a
        res_auth = get_current_subscription()
        self.assertTrue(res_auth.get("success"))
        print("  -> Authenticated request succeeded!")

    def test_02_correct_company_resolved_from_session(self):
        """TEST 02: Verify company is resolved from authenticated Employer User session."""
        print("\n[PHASE 23 TEST 02] Company Resolution from Session...")
        frappe.session.user = self.user_a_email
        frappe.flags.employer_company = None  # Ensure no test flag override

        resolved_company = get_current_company()
        self.assertEqual(resolved_company, self.company_a)

        emp_user = get_current_employer_user()
        self.assertEqual(emp_user.get("company"), self.company_a)
        print(f"  -> Session user '{self.user_a_email}' correctly resolved company '{resolved_company}'!")

    def test_03_billing_data_comes_from_real_database(self):
        """TEST 03: Verify billing data is fetched from live MariaDB tables."""
        print("\n[PHASE 23 TEST 03] Billing Data Real Database Sourcing...")
        # Create a specific subscription in MariaDB
        sub = self.service.get_active_subscription(self.company_a)
        sub.subscription_plan = self.plan_name
        sub.status = SUBSCRIPTION_STATUS_ACTIVE
        sub.save(ignore_permissions=True)
        frappe.db.commit()

        # Call API
        res = get_current_subscription()
        self.assertTrue(res.get("success"))
        data = res.get("data", {})

        # Verify values match database record directly
        db_sub = frappe.get_doc(DOCTYPE_COMPANY_SUBSCRIPTION, sub.name)
        self.assertEqual(data["subscription"]["name"], db_sub.name)
        self.assertEqual(data["subscription"]["status"], db_sub.status)
        self.assertEqual(data["company"], db_sub.company)
        print("  -> API response strictly matches live MariaDB record values!")

    def test_04_subscription_data_parity(self):
        """TEST 04: Verify subscription fields parity between MariaDB and API response."""
        print("\n[PHASE 23 TEST 04] Subscription Data Parity...")
        res = get_current_subscription()
        sub_data = res["data"]["subscription"]

        db_sub_name = frappe.db.get_value(DOCTYPE_COMPANY_SUBSCRIPTION, {"company": self.company_a}, "name")
        db_sub = frappe.get_doc(DOCTYPE_COMPANY_SUBSCRIPTION, db_sub_name)

        self.assertEqual(sub_data["status"], db_sub.status)
        self.assertEqual(sub_data["plan"], db_sub.subscription_plan)
        self.assertEqual(sub_data["billing_cycle"], db_sub.billing_cycle)
        self.assertEqual(sub_data["start_date"], str(db_sub.start_date))
        print("  -> Subscription status, plan, billing cycle, and start_date parity certified!")

    def test_05_plan_data_parity(self):
        """TEST 05: Verify plan details parity against tabSubscription_Plan_Recruitrain."""
        print("\n[PHASE 23 TEST 05] Plan Data Parity...")
        res = get_available_plans()
        plans = res.get("data", [])

        db_plans = frappe.get_all(DOCTYPE_SUBSCRIPTION_PLAN, filters={"is_active": 1}, fields=["name", "monthly_price", "currency"])
        self.assertTrue(len(plans) >= len(db_plans))

        matched_plan = next((p for p in plans if p["name"] == self.plan_name), None)
        self.assertIsNotNone(matched_plan)
        self.assertEqual(matched_plan["monthly_price"], 199.0)
        self.assertEqual(matched_plan["currency"], "USD")
        print("  -> Available plans API response matches database rows for active plans!")

    def test_06_usage_data_parity(self):
        """TEST 06: Verify usage data parity against tabSubscription Usage and direct DB counts."""
        print("\n[PHASE 23 TEST 06] Usage Data Parity...")
        usage_doc = self.service.recalculate_usage(self.company_a)
        res = get_usage()
        quotas = res["data"]["quotas"]

        self.assertEqual(quotas["active_jobs"]["used"], usage_doc.current_active_jobs)
        self.assertEqual(quotas["recruiters"]["used"], usage_doc.current_recruiters)
        self.assertEqual(quotas["candidates"]["used"], usage_doc.current_candidates)
        print("  -> Usage quota numbers match live database entity counts!")

    def test_07_invoice_data_parity(self):
        """TEST 07: Verify invoice records parity against tabBilling Transaction."""
        print("\n[PHASE 23 TEST 07] Invoice Data Parity...")
        # Clear existing transactions for company A
        frappe.db.sql("DELETE FROM `tabBilling Transaction` WHERE `company` = %s", (self.company_a,))
        frappe.db.commit()

        sub = self.service.get_active_subscription(self.company_a)

        # Create test transaction in MariaDB
        txn = frappe.new_doc(DOCTYPE_BILLING_TRANSACTION)
        txn.company = self.company_a
        txn.company_subscription = sub.name
        txn.amount = 199.0
        txn.currency = "USD"
        txn.invoice_number = "INV-P23-001"
        txn.payment_status = "Paid"
        txn.insert(ignore_permissions=True)
        frappe.db.commit()

        # Call get_invoices API
        res = get_invoices()
        invoices = res.get("data", [])
        self.assertTrue(len(invoices) > 0)
        self.assertEqual(invoices[0]["invoice_number"], "INV-P23-001")
        self.assertEqual(invoices[0]["amount"], 199.0)
        self.assertEqual(invoices[0]["payment_status"], "Paid")
        print("  -> Invoice API data matches MariaDB Billing Transaction record!")

    def test_08_payment_data_parity(self):
        """TEST 08: Verify payment history parity against tabBilling Transaction."""
        print("\n[PHASE 23 TEST 08] Payment Data Parity...")
        res = get_payment_history()
        history = res.get("data", [])
        self.assertTrue(len(history) > 0)
        self.assertEqual(history[0]["invoice_number"], "INV-P23-001")
        self.assertEqual(history[0]["payment_status"], "Paid")
        print("  -> Payment history matches MariaDB transaction record!")

    def test_09_company_isolation(self):
        """TEST 09: Verify Company A only receives Company A's billing data."""
        print("\n[PHASE 23 TEST 09] Company Isolation...")
        # Query Company A billing overview
        frappe.session.user = self.user_a_email
        frappe.flags.employer_company = self.company_a
        res_a = get_billing_overview()
        self.assertEqual(res_a["data"]["company"], self.company_a)

        # Query Company B billing overview
        frappe.session.user = self.user_b_email
        frappe.flags.employer_company = self.company_b
        res_b = get_billing_overview()
        self.assertEqual(res_b["data"]["company"], self.company_b)

        self.assertNotEqual(res_a["data"]["company"], res_b["data"]["company"])
        print("  -> Tenant isolation verified! Each user only sees their own company billing data.")

    def test_10_cross_company_access_blocked(self):
        """TEST 10: Verify cross-company parameters cannot bypass tenant isolation."""
        print("\n[PHASE 23 TEST 10] Cross-Company Access Blocked...")
        frappe.session.user = self.user_a_email
        frappe.flags.employer_company = None  # Force session resolution

        # Request billing data with parameters attempting to reference Company B
        frappe.form_dict["company"] = self.company_b
        frappe.form_dict["company_id"] = self.company_b

        res = get_billing_overview()
        # Must return Company A data, ignoring untrusted query params
        self.assertEqual(res["data"]["company"], self.company_a)
        self.assertNotEqual(res["data"]["company"], self.company_b)
        print("  -> Client-passed company parameters safely ignored! Strict session company enforced.")

    def test_11_no_secrets_or_payment_credentials_exposed(self):
        """TEST 11: Verify responses contain no API keys, secret tokens, or CVV/card numbers."""
        print("\n[PHASE 23 TEST 11] Security Audit - No Secrets/Credentials Exposed...")
        res = get_billing_overview()
        res_str = str(res).lower()

        forbidden_keys = ["secret", "api_key", "cvv", "card_number", "private_key", "password"]
        for key in forbidden_keys:
            self.assertNotIn(key, res_str)

        print("  -> Security verified! No secret keys or card numbers exposed in API envelope.")

    def test_12_standard_ats_response_envelope(self):
        """TEST 12: Verify standard ATS response envelope formatting."""
        print("\n[PHASE 23 TEST 12] Standard ATS Response Envelope...")
        res = get_current_subscription()
        self.assertIn("success", res)
        self.assertIn("data", res)
        self.assertIn("message", res)
        self.assertIn("error", res)
        self.assertIn("meta", res)
        self.assertTrue(res["success"])
        print("  -> Standard ATS response envelope compliant!")

    def test_13_repeated_request_consistency(self):
        """TEST 13: Verify repeated requests produce consistent, non-mutating responses."""
        print("\n[PHASE 23 TEST 13] Repeated Request Consistency...")
        res1 = get_current_subscription()
        res2 = get_current_subscription()

        self.assertEqual(res1["data"]["subscription"]["name"], res2["data"]["subscription"]["name"])
        self.assertEqual(res1["data"]["subscription"]["status"], res2["data"]["subscription"]["status"])
        self.assertEqual(res1["data"]["company"], res2["data"]["company"])
        print("  -> Repeated request consistency confirmed!")

    def test_14_no_mock_or_demo_values_returned(self):
        """TEST 14: Verify backend returns empty records when no invoices exist, not fake data."""
        print("\n[PHASE 23 TEST 14] No Mock/Demo Values Returned...")
        # Create fresh test company with no transactions
        clean_company = "Phase23 Clean Tenant Co"
        clean_user = "clean_p23@test.com"
        self._create_test_company(clean_company, clean_user)

        frappe.session.user = clean_user
        frappe.flags.employer_company = clean_company

        res = get_invoices()
        invoices = res.get("data", [])
        # Must return empty list [], NOT fake hardcoded mock invoice arrays
        self.assertEqual(invoices, [])
        print("  -> Verified backend returns empty array [] for tenant without invoices, NO fake demo invoices returned!")


def run_phase23_tests():
    """Execution wrapper for Phase 23 test runner."""
    print("==========================================================================")
    print("  RecruitTrain ATS Phase 23 - Billing Backend Audit & Real-Data Contract  ")
    print("==========================================================================")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestBillingPhase23)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if result.wasSuccessful():
        print("\n--------------------------------------------------------------------------")
        print(" ALL 14 PHASE 23 BILLING AUDIT TESTS PASSED SUCCESSFULLY! (EXIT CODE 0)")
        print("--------------------------------------------------------------------------")
        sys.exit(0)
    else:
        print("\n--------------------------------------------------------------------------")
        print(" PHASE 23 BILLING AUDIT TESTS FAILED")
        print("--------------------------------------------------------------------------")
        sys.exit(1)


if __name__ == "__main__":
    run_phase23_tests()
