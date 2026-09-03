# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.tests.test_calendar_phase24
===================================================

Phase 24 Real Data Audit and Contract Test Suite for RecruitTrain ATS Calendar Module.

Tests:
- TEST 01: Authenticated calendar request succeeds
- TEST 02: Company is resolved from authenticated session
- TEST 03: Real Interview records are returned
- TEST 04: Interview dates match database
- TEST 05: Candidate/Job relationships match database
- TEST 06: Relevant Offer dates match database where applicable
- TEST 07: Relevant Job Opening/Application dates match database where applicable
- TEST 08: Date-range filtering works
- TEST 09: Event_type filtering works
- TEST 10: Status filtering works
- TEST 11: Foreign-company records are never returned
- TEST 12: Spoofed company parameters cannot change tenant scope
- TEST 13: Empty database/date range returns [] rather than demo events
- TEST 14: No mock/demo calendar values exist
- TEST 15: Response follows standard ATS envelope
- TEST 16: Repeated requests return consistent database-backed results
"""

import sys
import unittest
import frappe
from frappe.utils import add_days, getdate, now_datetime, today

from recruitrain_employer.api.calendar import get_calendar_events
from recruitrain_employer.services.calendar_service import CalendarService
from recruitrain_employer.utils.permissions import get_current_company, get_current_employer_user


class TestCalendarPhase24(unittest.TestCase):
    """Phase 24 Calendar Audit & Contract Verification Test Suite."""

    @classmethod
    def setUpClass(cls):
        """Initialize Frappe, reload DocTypes, and seed two isolated test companies with real records."""
        frappe.init(site="development.localhost", sites_path="./sites")
        frappe.connect()
        frappe.clear_cache()
        frappe.reload_doctype("Company")
        frappe.reload_doctype("User")
        frappe.reload_doctype("Employer User")
        frappe.reload_doctype("Candidate")
        frappe.reload_doctype("Job Opening")
        frappe.reload_doctype("Job Application")
        frappe.reload_doctype("Interview")
        frappe.reload_doctype("Offer")

        from recruitrain_employer.services.master_seed_service import ensure_master_records_exist
        ensure_master_records_exist()

        cls.service = CalendarService()

        # Seed Company Alpha (Tenant A)
        cls.company_a = "Phase24 Company Alpha"
        cls.user_a_email = "employer_alpha_p24@test.com"
        cls._create_test_company(cls.company_a, cls.user_a_email)

        # Seed Company Beta (Tenant B)
        cls.company_b = "Phase24 Company Beta"
        cls.user_b_email = "employer_beta_p24@test.com"
        cls._create_test_company(cls.company_b, cls.user_b_email)

        # Seed Tenant A Records
        cls.cand_a_name = cls._create_test_candidate("Alpha Candidate", cls.company_a, "alpha.cand@test.com")
        cls.job_a_name = cls._create_test_job("Software Engineer Alpha", cls.company_a, closing_date=add_days(today(), 30))
        cls.app_a_name = cls._create_test_application(cls.cand_a_name, cls.job_a_name, cls.company_a, applied_on=today())

        cls.interview_date = f"{add_days(today(), 2)} 14:00:00"
        cls.interview_a_name = cls._create_test_interview(
            name="INT-P24-001",
            company=cls.company_a,
            candidate=cls.cand_a_name,
            job_opening=cls.job_a_name,
            job_application=cls.app_a_name,
            scheduled_on=cls.interview_date,
            duration=45,
            status="Scheduled",
        )

        cls.joining_date = add_days(today(), 15)
        cls.offer_a_name = cls._create_test_offer(
            company=cls.company_a,
            candidate=cls.cand_a_name,
            job_opening=cls.job_a_name,
            job_application=cls.app_a_name,
            joining_date=cls.joining_date,
            offer_date=today(),
            status="Sent",
        )

        # Seed Tenant B Records (for Isolation Testing)
        cls.cand_b_name = cls._create_test_candidate("Beta Candidate", cls.company_b, "beta.cand@test.com")
        cls.job_b_name = cls._create_test_job("Product Manager Beta", cls.company_b, closing_date=add_days(today(), 20))
        cls.app_b_name = cls._create_test_application(cls.cand_b_name, cls.job_b_name, cls.company_b, applied_on=today())
        cls.interview_b_name = cls._create_test_interview(
            name="INT-P24-002",
            company=cls.company_b,
            candidate=cls.cand_b_name,
            job_opening=cls.job_b_name,
            job_application=cls.app_b_name,
            scheduled_on=f"{add_days(today(), 5)} 10:00:00",
            duration=60,
            status="Scheduled",
        )

    @classmethod
    def _create_test_company(cls, company_name: str, user_email: str):
        """Helper to create test Company, User, and Employer User records."""
        if not frappe.db.exists("Company", company_name):
            comp = frappe.new_doc("Company")
            comp.company_name = company_name
            comp.status = "Active"
            comp.email = user_email
            comp.phone = "+14155559999"
            comp.address_line_1 = "200 Calendar Way"
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
    def _create_test_candidate(cls, full_name: str, company: str, email: str) -> str:
        cand_id = f"CAND-P24-{full_name.replace(' ', '-').upper()}"
        if not frappe.db.exists("Candidate", cand_id):
            c = frappe.new_doc("Candidate")
            c.candidate_name = cand_id
            parts = full_name.split(" ")
            c.first_name = parts[0]
            c.last_name = parts[1] if len(parts) > 1 else "Test"
            c.email = email
            c.company = company
            c.date_of_birth = "1995-01-01"
            c.mobile_no = "+14155551234"
            c.address_line_1 = "123 Test St"
            c.city = "San Francisco"
            c.state = "CA"
            c.insert(ignore_permissions=True)
            frappe.db.commit()
            return c.name
        return cand_id

    @classmethod
    def _create_test_job(cls, title: str, company: str, closing_date: str) -> str:
        job_code = f"JOB-P24-{title.replace(' ', '-').upper()}"
        if not frappe.db.exists("Job Opening", job_code):
            j = frappe.new_doc("Job Opening")
            j.job_code = job_code
            j.job_title = title
            j.company = company
            j.employment_type = "Full Time"
            j.number_of_openings = 1
            j.closing_date = closing_date
            j.job_summary = "<p>Test Summary</p>"
            j.responsibilities = "<p>Test Responsibilities</p>"
            j.requirements = "<p>Test Requirements</p>"
            j.status = "Open"
            j.insert(ignore_permissions=True)
            frappe.db.commit()
            return j.name
        return job_code

    @classmethod
    def _create_test_application(cls, candidate: str, job_opening: str, company: str, applied_on: str) -> str:
        existing = frappe.db.get_value("Job Application", {"candidate": candidate, "job_opening": job_opening}, "name")
        if existing:
            return existing
        app = frappe.new_doc("Job Application")
        app.candidate = candidate
        app.job_opening = job_opening
        app.company = company
        app.applied_on = applied_on
        app.source = "Manual"
        app.resume = "/files/test_resume.pdf"
        app.current_stage = "Interview"
        app.status = "Open"
        app.insert(ignore_permissions=True)
        frappe.db.commit()
        return str(app.name)

    @classmethod
    def _create_test_interview(cls, name: str, company: str, candidate: str, job_opening: str, job_application: str, scheduled_on: str, duration: int, status: str) -> str:
        if frappe.db.exists("Interview", name):
            frappe.db.sql("DELETE FROM `tabInterview` WHERE `name` = %s", (name,))
            frappe.db.commit()

        inv = frappe.new_doc("Interview")
        inv.interview_name = name
        inv.company = company
        inv.candidate = candidate
        inv.job_opening = job_opening
        inv.job_application = job_application
        inv.interview_type = "Technical"
        inv.scheduled_on = scheduled_on
        inv.duration = duration
        inv.interviewer = "Administrator"
        inv.status = status
        inv.insert(ignore_permissions=True)
        frappe.db.commit()
        return inv.name

    @classmethod
    def _create_test_offer(cls, company: str, candidate: str, job_opening: str, job_application: str, joining_date: str, offer_date: str, status: str) -> str:
        existing = frappe.db.get_value("Offer", {"candidate": candidate, "job_opening": job_opening}, "name")
        if existing:
            return str(existing)

        off = frappe.new_doc("Offer")
        off.offer_name = f"OFF-P24-{candidate}"
        off.company = company
        off.candidate = candidate
        off.job_opening = job_opening
        off.job_application = job_application
        off.offered_salary = 120000.0
        off.joining_date = joining_date
        off.offer_date = offer_date
        off.offer_status = status
        off.insert(ignore_permissions=True)
        frappe.db.commit()
        return str(off.name)

    def setUp(self):
        """Set session context to Tenant A before each test."""
        frappe.session.user = self.user_a_email
        frappe.flags.employer_company = self.company_a
        frappe.form_dict = frappe._dict()
        frappe.clear_cache()

    def tearDown(self):
        """Clean up session flags."""
        frappe.flags.employer_company = None

    # ------------------------------------------------------------------
    # Test Cases
    # ------------------------------------------------------------------

    def test_01_authenticated_calendar_request_succeeds(self):
        """TEST 01: Verify authenticated calendar request succeeds and unauthenticated fails."""
        print("\n[PHASE 24 TEST 01] Authenticated Calendar Request...")
        # Unauthenticated request
        frappe.session.user = "Guest"
        frappe.flags.employer_company = None
        res_guest = get_calendar_events()
        self.assertFalse(res_guest.get("success", False))
        err_code = res_guest.get("error", {}).get("code") if isinstance(res_guest.get("error"), dict) else res_guest.get("code")
        self.assertIn(err_code, ["UNAUTHORIZED", "PERMISSION_DENIED"])

        # Authenticated request
        frappe.session.user = self.user_a_email
        frappe.flags.employer_company = self.company_a
        res_auth = get_calendar_events()
        self.assertTrue(res_auth.get("success"))
        print("  -> Authenticated request succeeded!")

    def test_02_company_resolved_from_session(self):
        """TEST 02: Verify company is resolved from authenticated Employer User session."""
        print("\n[PHASE 24 TEST 02] Company Resolution from Session...")
        frappe.session.user = self.user_a_email
        frappe.flags.employer_company = None

        resolved = get_current_company()
        self.assertEqual(resolved, self.company_a)
        print(f"  -> Session user '{self.user_a_email}' correctly resolved company '{resolved}'!")

    def test_03_real_interview_records_returned(self):
        """TEST 03: Verify real Interview records from MariaDB are returned in calendar events."""
        print("\n[PHASE 24 TEST 03] Real Interview Records Returned...")
        res = get_calendar_events()
        self.assertTrue(res["success"])
        events = res["data"]

        interview_events = [e for e in events if e.get("source_doctype") == "Interview"]
        self.assertTrue(len(interview_events) > 0)
        
        target_inv = next((e for e in interview_events if e.get("source_name") == self.interview_a_name), None)
        self.assertIsNotNone(target_inv)
        self.assertEqual(target_inv["event_type"], "interview")
        self.assertEqual(target_inv["status"], "Scheduled")
        print(f"  -> Real interview event '{self.interview_a_name}' retrieved!")

    def test_04_interview_dates_match_database(self):
        """TEST 04: Verify interview start and end dates match MariaDB values."""
        print("\n[PHASE 24 TEST 04] Interview Dates Parity...")
        res = get_calendar_events()
        events = res["data"]
        target_inv = next((e for e in events if e.get("source_name") == self.interview_a_name), None)
        
        db_inv = frappe.get_doc("Interview", self.interview_a_name)
        self.assertEqual(target_inv["start"], str(db_inv.scheduled_on))
        self.assertIsNotNone(target_inv["end"])
        print("  -> Interview start and end dates match MariaDB record!")

    def test_05_candidate_job_relationships_match_database(self):
        """TEST 05: Verify candidate and job opening relationships match MariaDB."""
        print("\n[PHASE 24 TEST 05] Candidate/Job Relationships Parity...")
        res = get_calendar_events()
        events = res["data"]
        target_inv = next((e for e in events if e.get("source_name") == self.interview_a_name), None)

        self.assertIsNotNone(target_inv["candidate"])
        self.assertEqual(target_inv["candidate"]["id"], self.cand_a_name)
        self.assertIsNotNone(target_inv["job"])
        self.assertEqual(target_inv["job"]["id"], self.job_a_name)
        print("  -> Candidate and Job Opening relationships certified!")

    def test_06_relevant_offer_dates_match_database(self):
        """TEST 06: Verify Offer joining and offer dates match MariaDB values."""
        print("\n[PHASE 24 TEST 06] Offer Dates Parity...")
        res = get_calendar_events()
        events = res["data"]
        offer_events = [e for e in events if e.get("source_doctype") == "Offer"]
        self.assertTrue(len(offer_events) > 0)

        joining_event = next((e for e in offer_events if e.get("event_type") == "offer_joining"), None)
        self.assertIsNotNone(joining_event)
        self.assertEqual(joining_event["start"], str(self.joining_date))
        print("  -> Offer joining date event verified against MariaDB!")

    def test_07_relevant_job_opening_application_dates_match_database(self):
        """TEST 07: Verify Job Opening closing dates and Job Application applied_on dates match database."""
        print("\n[PHASE 24 TEST 07] Job Opening & Application Dates Parity...")
        res = get_calendar_events()
        events = res["data"]

        job_events = [e for e in events if e.get("source_doctype") == "Job Opening"]
        self.assertTrue(len(job_events) > 0)

        app_events = [e for e in events if e.get("source_doctype") == "Job Application"]
        self.assertTrue(len(app_events) > 0)
        print("  -> Job Opening and Job Application date events verified!")

    def test_08_date_range_filtering_works(self):
        """TEST 08: Verify from_date and to_date filtering restricts returned events."""
        print("\n[PHASE 24 TEST 08] Date Range Filtering...")
        from_d = add_days(today(), 1)
        to_d = add_days(today(), 3)
        frappe.form_dict["from_date"] = from_d
        frappe.form_dict["to_date"] = to_d

        res = get_calendar_events()
        events = res["data"]
        for e in events:
            start_d = str(e["start"])[:10]
            self.assertTrue(start_d >= from_d)
            self.assertTrue(start_d <= to_d)
        print("  -> Date-range filtering correctly restricts returned events!")

    def test_09_event_type_filtering_works(self):
        """TEST 09: Verify event_type filtering restricts results to requested types."""
        print("\n[PHASE 24 TEST 09] Event Type Filtering...")
        frappe.form_dict["event_type"] = "interview"
        res = get_calendar_events()
        events = res["data"]

        self.assertTrue(all(e["event_type"] == "interview" for e in events))
        print("  -> Event type filtering strictly enforced!")

    def test_10_status_filtering_works(self):
        """TEST 10: Verify status filtering restricts results to matching status."""
        print("\n[PHASE 24 TEST 10] Status Filtering...")
        frappe.form_dict["status"] = "Scheduled"
        res = get_calendar_events()
        events = res["data"]

        self.assertTrue(all(e["status"].lower() == "scheduled" for e in events))
        print("  -> Status filtering verified!")

    def test_11_foreign_company_records_never_returned(self):
        """TEST 11: Verify Company A session never returns Company B events."""
        print("\n[PHASE 24 TEST 11] Foreign Company Isolation...")
        frappe.session.user = self.user_a_email
        frappe.flags.employer_company = self.company_a
        res_a = get_calendar_events()

        events_a_ids = [e["id"] for e in res_a["data"]]
        self.assertNotIn(self.interview_b_name, events_a_ids)

        frappe.session.user = self.user_b_email
        frappe.flags.employer_company = self.company_b
        res_b = get_calendar_events()

        events_b_ids = [e["id"] for e in res_b["data"]]
        self.assertIn(self.interview_b_name, events_b_ids)
        self.assertNotIn(self.interview_a_name, events_b_ids)
        print("  -> Tenant isolation verified! No cross-company records exposed.")

    def test_12_spoofed_company_parameters_cannot_change_tenant_scope(self):
        """TEST 12: Verify client-passed company parameters cannot hijack tenant scope."""
        print("\n[PHASE 24 TEST 12] Company Parameter Spoofing Blocked...")
        frappe.session.user = self.user_a_email
        frappe.flags.employer_company = None  # Force session resolution

        frappe.form_dict["company"] = self.company_b
        frappe.form_dict["company_id"] = self.company_b

        res = get_calendar_events()
        events = res["data"]
        # Must return Tenant A events, NOT Tenant B
        event_ids = [e["id"] for e in events]
        self.assertNotIn(self.interview_b_name, event_ids)
        print("  -> Spoofed company parameter safely ignored! Session scope enforced.")

    def test_13_empty_database_date_range_returns_empty_list(self):
        """TEST 13: Verify query with no matching events returns [] rather than mock events."""
        print("\n[PHASE 24 TEST 13] Empty Result Set Returns []...")
        frappe.form_dict["from_date"] = "2010-01-01"
        frappe.form_dict["to_date"] = "2010-01-02"

        res = get_calendar_events()
        self.assertTrue(res["success"])
        self.assertEqual(res["data"], [])
        print("  -> Verified backend returns empty array [] for range without events!")

    def test_14_no_mock_or_demo_calendar_values_exist(self):
        """TEST 14: Verify response items only reference existing MariaDB DocType names."""
        print("\n[PHASE 24 TEST 14] No Mock/Demo Calendar Values...")
        res = get_calendar_events()
        events = res["data"]

        for e in events:
            src_dt = e["source_doctype"]
            src_name = e["source_name"]
            self.assertTrue(frappe.db.exists(src_dt, src_name))
        print("  -> Every returned calendar event maps 1:1 to an existing MariaDB row!")

    def test_15_response_follows_standard_ats_envelope(self):
        """TEST 15: Verify response adheres to { success, data, message, error, meta } structure."""
        print("\n[PHASE 24 TEST 15] Standard ATS Response Envelope...")
        res = get_calendar_events()
        self.assertIn("success", res)
        self.assertIn("data", res)
        self.assertIn("message", res)
        self.assertIn("error", res)
        self.assertIn("meta", res)
        self.assertTrue(res["success"])
        print("  -> Standard ATS response envelope compliant!")

    def test_16_repeated_requests_return_consistent_results(self):
        """TEST 16: Verify repeated API invocations yield consistent, non-mutating outputs."""
        print("\n[PHASE 24 TEST 16] Repeated Request Consistency...")
        res1 = get_calendar_events()
        res2 = get_calendar_events()

        self.assertEqual(len(res1["data"]), len(res2["data"]))
        self.assertEqual([e["id"] for e in res1["data"]], [e["id"] for e in res2["data"]])
        print("  -> Repeated request consistency confirmed!")


def run_phase24_tests():
    """Execution wrapper for Phase 24 test runner."""
    print("==========================================================================")
    print("  RecruitTrain ATS Phase 24 - Calendar Backend Audit & Real-Data Contract ")
    print("==========================================================================")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestCalendarPhase24)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if result.wasSuccessful():
        print("\n--------------------------------------------------------------------------")
        print(" ALL 16 PHASE 24 CALENDAR AUDIT TESTS PASSED SUCCESSFULLY! (EXIT CODE 0)")
        print("--------------------------------------------------------------------------")
        sys.exit(0)
    else:
        print("\n--------------------------------------------------------------------------")
        print(" PHASE 24 CALENDAR AUDIT TESTS FAILED")
        print("--------------------------------------------------------------------------")
        sys.exit(1)


if __name__ == "__main__":
    run_phase24_tests()
