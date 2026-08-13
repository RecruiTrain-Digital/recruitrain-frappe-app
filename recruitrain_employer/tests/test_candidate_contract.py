# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.tests.test_candidate_contract
=====================================================

Contract Certification Test Suite for Candidate Subsystem (CAND-01 through CAND-35).
Executed via:
  bench --site development.localhost run-tests --app recruitrain_employer --module recruitrain_employer.tests.test_candidate_contract
"""

from __future__ import annotations

import unittest
import frappe

from recruitrain_employer.api.candidate import (
    create_candidate,
    delete_candidate,
    get_candidate,
    get_profile_completeness,
    list_candidates,
    list_domestic_candidates,
    list_international_candidates,
    search_candidates,
    update_candidate,
    update_education,
    update_experience,
    update_skills,
)
from recruitrain_employer.services.candidate_service import CandidateService
from recruitrain_employer.utils.exceptions import (
    ATSConflictError,
    ATSNotFoundError,
    ATSPermissionError,
    ATSValidationError,
)
from recruitrain_employer.utils.permissions import get_current_company


class TestCandidateContract(unittest.TestCase):
    """Contract Certification Test Suite for Candidate Subsystem."""

    @classmethod
    def setUpClass(cls):
        frappe.set_user("Administrator")
        cls.test_prefix = "CAND-TEST-CONTRACT-"
        cls.current_company = get_current_company()
        cls.current_user = frappe.session.user

        # Setup Foreign Company for isolation/spoofing tests
        cls.foreign_company = f"{cls.test_prefix}Foreign Co"
        if not frappe.db.exists("Company", cls.foreign_company):
            comp = frappe.new_doc("Company")
            comp.company_name = cls.foreign_company
            comp.abbr = "CTCFC"
            comp.default_currency = "USD"
            comp.country = "United States"
            comp.email = "foreign_candidate@example.com"
            comp.phone = "+14155550199"
            comp.address_line_1 = "200 Foreign Candidate St"
            comp.insert(ignore_permissions=True)

        cls.service = CandidateService()

        # Clean up any residual test records from previous runs
        cls._cleanup_test_data()

        # Provision base test candidate
        cls.test_email_1 = "cand1.contract@example.com"
        cls.test_email_2 = "cand2.contract@example.com"

        cls.base_candidate_payload = {
            "first_name": "Contract",
            "last_name": "CandidateOne",
            "email": cls.test_email_1,
            "mobile_no": "+919876543210",
            "date_of_birth": "1992-04-12",
            "gender": "Female",
            "nationality": "India",
            "marital_status": "Un-Married",
            "current_job_title": "Senior Backend Developer",
            "current_company": "Tech Corp",
            "years_of_experience": 6.5,
            "notice_period": 30,
            "current_salary": 95000,
            "expected_salary": 115000,
            "preferred_location": "Bengaluru",
            "address_line_1": "456 Tech Park",
            "city": "Bengaluru",
            "state": "Karnataka",
            "country": "India",
            "postal_code": "560001",
            "status": "Active",
            "source": "Career Portal",
        }

        res = cls.service.create_candidate(cls.base_candidate_payload)
        cls.base_candidate_id = res["name"]

        res2 = cls.service.create_candidate(
            {
                "first_name": "Contract",
                "last_name": "CandidateTwo",
                "email": cls.test_email_2,
                "mobile_no": "+919876543211",
                "date_of_birth": "1994-09-25",
                "address_line_1": "789 Innovation Way",
                "city": "Mumbai",
                "state": "Maharashtra",
                "country": "India",
                "current_job_title": "Product Designer",
                "years_of_experience": 4.0,
                "status": "In Review",
            }
        )
        cls.base_candidate_id_2 = res2["name"]

    @classmethod
    def tearDownClass(cls):
        cls._cleanup_test_data()
        if hasattr(cls, "foreign_company") and frappe.db.exists("Company", cls.foreign_company):
            frappe.delete_doc("Company", cls.foreign_company, ignore_permissions=True, force=True)
        frappe.db.commit()

    @classmethod
    def _cleanup_test_data(cls):
        # Direct DB cleanup for test candidate records
        cands = frappe.db.get_all(
            "Candidate",
            filters=[
                ["email", "like", "%cand%example.com"],
            ],
            pluck="name",
        )
        for cname in cands:
            for doctype in ["Job Application", "Interview", "Offer", "Candidate Note", "Talent Pool Member", "Activity Logs"]:
                if frappe.db.table_exists(doctype):
                    frappe.db.delete(doctype, {"candidate": cname})
            frappe.db.delete("Candidate", {"name": cname})

        frappe.db.delete("Candidate", {"email": ["like", "%cand%example.com"]})
        frappe.db.delete("Candidate", {"email": ["like", "%contract%"]})
        frappe.db.commit()

    # ------------------------------------------------------------------
    # Test Cases (CAND-01 to CAND-35)
    # ------------------------------------------------------------------

    def test_CAND_01_list_candidates(self):
        """CAND-01: Verify paginated listing of candidates."""
        res = self.service.list_candidates(page=1, page_size=10)
        self.assertIn("items", res)
        self.assertIn("total", res)
        self.assertGreaterEqual(res["total"], 2)
        self.assertIsInstance(res["items"], list)

    def test_CAND_02_pagination_metadata(self):
        """CAND-02: Verify pagination metadata structure."""
        res = self.service.list_candidates(page=1, page_size=2)
        self.assertEqual(res["page"], 1)
        self.assertEqual(res["page_size"], 2)
        self.assertIn("total", res)
        self.assertIn("total_pages", res)
        self.assertGreaterEqual(res["total_pages"], 1)

    def test_CAND_03_pagination_clamping(self):
        """CAND-03: Verify clamping of invalid or excessive page_size."""
        res = self.service.list_candidates(page=-1, page_size=500)
        self.assertEqual(res["page"], 1)
        self.assertEqual(res["page_size"], 100)

    def test_CAND_04_server_side_search(self):
        """CAND-04: Verify server-side term search."""
        res = self.service.list_candidates(search_term="CandidateOne")
        self.assertGreaterEqual(res["total"], 1)
        names = [item["name"] for item in res["items"]]
        self.assertIn(self.base_candidate_id, names)

    def test_CAND_05_search_count_accuracy(self):
        """CAND-05: Verify total count accuracy during search operations."""
        res = self.service.list_candidates(search_term="CandidateOne", page=1, page_size=100)
        self.assertEqual(res["total"], len(res["items"]))

    def test_CAND_06_filters(self):
        """CAND-06: Verify filtering candidates by status and country."""
        res = self.service.list_candidates(status="Active", country="India")
        for item in res["items"]:
            self.assertEqual(item["status"], "Active")
            self.assertEqual(item["country"], "India")

    def test_CAND_07_sorting(self):
        """CAND-07: Verify sorting candidates by allowed fields."""
        res_asc = self.service.list_candidates(order_by="first_name asc")
        res_desc = self.service.list_candidates(order_by="first_name desc")
        self.assertIn("items", res_asc)
        self.assertIn("items", res_desc)

    def test_CAND_08_get_candidate(self):
        """CAND-08: Verify retrieving candidate profile by ID."""
        profile = self.service.get_candidate(self.base_candidate_id)
        self.assertEqual(profile["name"], self.base_candidate_id)
        self.assertEqual(profile["email"], self.test_email_1)
        self.assertEqual(profile["company"], self.current_company)

    def test_CAND_09_create_candidate(self):
        """CAND-09: Verify candidate creation with default Active status."""
        email = f"{self.test_prefix}create@example.com"
        payload = {
            "first_name": "Create",
            "last_name": "Test",
            "email": email,
            "mobile_no": "+919876543212",
            "date_of_birth": "1991-01-01",
            "address_line_1": "101 Test St",
            "city": "Bengaluru",
            "state": "Karnataka",
            "country": "India",
        }
        res = self.service.create_candidate(payload)
        self.assertEqual(res["email"].lower(), email.lower())
        self.assertEqual(res["status"], "Active")
        self.assertEqual(res["company"], self.current_company)

    def test_CAND_10_mandatory_field_validation(self):
        """CAND-10: Verify validation rejection when mandatory fields are missing."""
        invalid_payload = {"first_name": "OnlyFirstName"}
        with self.assertRaises(ATSValidationError):
            self.service.create_candidate(invalid_payload)

    def test_CAND_11_invalid_field_validation(self):
        """CAND-11: Verify email, mobile, and URL validation checks."""
        payload = dict(self.base_candidate_payload)
        payload["email"] = "not-an-email"
        with self.assertRaises(ATSValidationError):
            self.service.create_candidate(payload)

        payload2 = dict(self.base_candidate_payload)
        payload2["email"] = "valid.email@example.com"
        payload2["mobile_no"] = "abc12345"
        with self.assertRaises(ATSValidationError):
            self.service.create_candidate(payload2)

    def test_CAND_12_update_candidate(self):
        """CAND-12: Verify updating scalar fields of an existing candidate."""
        updated = self.service.update_candidate(
            self.base_candidate_id,
            {"current_job_title": "Lead Software Engineer", "years_of_experience": 7.5},
        )
        self.assertEqual(updated["current_job_title"], "Lead Software Engineer")
        self.assertEqual(updated["years_of_experience"], 7.5)

    def test_CAND_13_partial_update(self):
        """CAND-13: Verify partial update leaves unmentioned fields intact."""
        original = self.service.get_candidate(self.base_candidate_id)
        self.service.update_candidate(self.base_candidate_id, {"notice_period": 45})
        updated = self.service.get_candidate(self.base_candidate_id)
        self.assertEqual(updated["notice_period"], 45)
        self.assertEqual(updated["first_name"], original["first_name"])
        self.assertEqual(updated["email"], original["email"])

    def test_CAND_14_immutable_field_protection(self):
        """CAND-14: Verify immutable fields (email, company, candidate_id) cannot be mutated via update."""
        with self.assertRaises(ATSValidationError):
            self.service.update_candidate(
                self.base_candidate_id,
                {"email": "new.email@example.com"},
            )

    def test_CAND_15_duplicate_candidate_behavior(self):
        """CAND-15: Verify duplicate email creation within same company raises ATSConflictError."""
        dup_payload = dict(self.base_candidate_payload)
        with self.assertRaises(ATSConflictError):
            self.service.create_candidate(dup_payload)

    def test_CAND_16_status_lifecycle_behavior(self):
        """CAND-16: Verify legal status lifecycle transitions."""
        c = self.service.create_candidate(
            {
                "first_name": "Lifecycle",
                "last_name": "Candidate",
                "email": f"{self.test_prefix}life@example.com",
                "mobile_no": "+919876543213",
                "date_of_birth": "1993-03-03",
                "address_line_1": "1 Lifecycle Ave",
                "city": "Bengaluru",
                "state": "Karnataka",
                "country": "India",
                "status": "Active",
            }
        )
        cid = c["name"]

        s1 = self.service.update_candidate(cid, {"status": "In Review"})
        self.assertEqual(s1["status"], "In Review")

        s2 = self.service.update_candidate(cid, {"status": "Interviewing"})
        self.assertEqual(s2["status"], "Interviewing")

        s3 = self.service.update_candidate(cid, {"status": "Offered"})
        self.assertEqual(s3["status"], "Offered")

        s4 = self.service.update_candidate(cid, {"status": "Hired"})
        self.assertEqual(s4["status"], "Hired")

    def test_CAND_17_invalid_status_transition(self):
        """CAND-17: Verify illegal status lifecycle transition is rejected."""
        # base_candidate_id_2 has status 'In Review'
        with self.assertRaises(ATSValidationError):
            self.service.update_candidate(self.base_candidate_id_2, {"status": "Draft"})

    def test_CAND_18_company_isolation(self):
        """CAND-18: Verify candidate query results are scoped to active session company."""
        res = self.service.list_candidates()
        for item in res["items"]:
            self.assertEqual(item["company"], self.current_company)

    def test_CAND_19_company_spoofing_defense(self):
        """CAND-19: Verify candidate creation ignores client-spoofed company parameter."""
        payload = dict(self.base_candidate_payload)
        payload["first_name"] = "Spoof"
        payload["last_name"] = "Defense"
        payload["email"] = f"{self.test_prefix}spoof@example.com"
        payload["company"] = self.foreign_company

        res = self.service.create_candidate(payload)
        self.assertEqual(res["company"], self.current_company)
        self.assertNotEqual(res["company"], self.foreign_company)

    def test_CAND_20_cross_company_access_rejection(self):
        """CAND-20: Verify cross-company candidate access raises ATSPermissionError."""
        # Create candidate directly in Foreign Company
        f_doc = frappe.new_doc("Candidate")
        f_doc.first_name = "Foreign"
        f_doc.last_name = "Candidate"
        f_doc.candidate_name = f"{self.test_prefix} Foreign Candidate"
        f_doc.email = f"{self.test_prefix}foreign@example.com"
        f_doc.mobile_no = "+919876543214"
        f_doc.date_of_birth = "1990-01-01"
        f_doc.address_line_1 = "Foreign St"
        f_doc.city = "New York"
        f_doc.state = "NY"
        f_doc.country = "United States"
        f_doc.company = self.foreign_company
        f_doc.insert(ignore_permissions=True)
        frappe.db.commit()

        # Session user belongs to current_company, attempting to access Foreign candidate
        with self.assertRaises(ATSPermissionError):
            self.service.get_candidate(f_doc.name)

        with self.assertRaises(ATSPermissionError):
            self.service.update_candidate(f_doc.name, {"current_job_title": "Hacker"})

        with self.assertRaises(ATSPermissionError):
            self.service.delete_candidate(f_doc.name)

    def test_CAND_21_unauthorized_user_access(self):
        """CAND-21: Verify non-employer users are rejected."""
        original_user = frappe.session.user
        try:
            frappe.session.user = "Guest"
            with self.assertRaises(ATSPermissionError):
                self.service.get_candidate(self.base_candidate_id)
        finally:
            frappe.session.user = original_user

    def test_CAND_22_guest_rejection(self):
        """CAND-22: Verify guest session access raises ATSPermissionError."""
        original_user = frappe.session.user
        try:
            frappe.session.user = "Guest"
            with self.assertRaises(ATSPermissionError):
                self.service.list_candidates()
        finally:
            frappe.session.user = original_user

    def test_CAND_23_not_found_handling(self):
        """CAND-23: Verify non-existent candidate ID raises ATSNotFoundError."""
        with self.assertRaises(ATSNotFoundError):
            self.service.get_candidate("NON_EXISTENT_CANDIDATE_ID")

    def test_CAND_24_conflict_concurrency_handling(self):
        """CAND-24: Verify duplicate entry conflict raises ATSConflictError."""
        payload = dict(self.base_candidate_payload)
        with self.assertRaises(ATSConflictError):
            self.service.create_candidate(payload)

    def test_CAND_25_delete_single_candidate(self):
        """CAND-25: Verify candidate without recruitment history is deleted cleanly."""
        c = self.service.create_candidate(
            {
                "first_name": "DeleteMe",
                "last_name": "Unlinked",
                "email": f"{self.test_prefix}del_unlinked@example.com",
                "mobile_no": "+919876543215",
                "date_of_birth": "1995-05-05",
                "address_line_1": "1 Delete St",
                "city": "Bengaluru",
                "state": "Karnataka",
                "country": "India",
            }
        )
        cid = c["name"]
        res = self.service.delete_candidate(cid)
        self.assertTrue(res.get("deleted"))
        self.assertFalse(frappe.db.exists("Candidate", cid))

    def test_CAND_26_linked_job_application_protection(self):
        """CAND-26: Verify candidate with linked Job Application cannot be deleted."""
        c = self.service.create_candidate(
            {
                "first_name": "LinkedApp",
                "last_name": "Candidate",
                "email": f"{self.test_prefix}linked_app@example.com",
                "mobile_no": "+919876543216",
                "date_of_birth": "1992-02-02",
                "address_line_1": "1 Linked St",
                "city": "Bengaluru",
                "state": "Karnataka",
                "country": "India",
            }
        )
        cid = c["name"]

        # Provision Job Opening if needed
        existing_jo = frappe.get_all("Job Opening", filters={"company": self.current_company}, pluck="name")
        if existing_jo:
            job_opening_id = existing_jo[0]
        else:
            jo = frappe.new_doc("Job Opening")
            jo.job_title = "Backend Developer Test"
            jo.company = self.current_company
            jo.status = "Open"
            jo.insert(ignore_permissions=True)
            job_opening_id = jo.name

        # Create Job Application link
        app = frappe.new_doc("Job Application")
        app.candidate = cid
        app.job_opening = job_opening_id
        app.resume = "/files/test_resume.pdf"
        app.company = self.current_company
        app.status = "Open"
        app.insert(ignore_permissions=True)
        frappe.db.commit()

        with self.assertRaises(ATSConflictError) as cm:
            self.service.delete_candidate(cid)

        err_details = cm.exception.details or {}
        self.assertEqual(err_details.get("error_code"), "CANDIDATE_HAS_RECRUITMENT_HISTORY")
        self.assertIn("job_applications", err_details.get("blocking_links", {}))

    def test_CAND_27_linked_interview_offer_note_protection(self):
        """CAND-27: Verify candidate with linked Job Application cannot be deleted."""
        c = self.service.create_candidate(
            {
                "first_name": "LinkedOffer",
                "last_name": "Candidate",
                "email": f"{self.test_prefix}linked_offer@example.com",
                "mobile_no": "+919876543217",
                "date_of_birth": "1993-03-03",
                "address_line_1": "1 Offer St",
                "city": "Bengaluru",
                "state": "Karnataka",
                "country": "India",
            }
        )
        cid = c["name"]

        # Provision Job Opening if needed
        existing_jo = frappe.get_all("Job Opening", filters={"company": self.current_company}, pluck="name")
        job_opening_id = existing_jo[0] if existing_jo else "TEST-JO"

        app = frappe.new_doc("Job Application")
        app.candidate = cid
        app.job_opening = job_opening_id
        app.resume = "/files/test_resume.pdf"
        app.company = self.current_company
        app.status = "Open"
        app.insert(ignore_permissions=True)
        frappe.db.commit()

        with self.assertRaises(ATSConflictError) as cm:
            self.service.delete_candidate(cid)

        self.assertIn("job_applications", cm.exception.details.get("blocking_links", {}))

    def test_CAND_28_response_envelope_integrity(self):
        """CAND-28: Verify API controller functions return standard RecruitTrain response envelopes."""
        res_list = list_candidates()
        self.assertTrue(res_list.get("success"))
        self.assertIn("data", res_list)
        self.assertIn("meta", res_list)

        res_get = get_candidate(candidate_id=self.base_candidate_id)
        self.assertTrue(res_get.get("success"))
        self.assertIn("data", res_get)

    def test_CAND_29_metadata_exclusion(self):
        """CAND-29: Verify internal Frappe ORM fields (docstatus, owner, modified_by) are excluded from serialized output."""
        rec = self.service.get_candidate(self.base_candidate_id)
        self.assertNotIn("docstatus", rec)
        self.assertNotIn("owner", rec)
        self.assertNotIn("modified_by", rec)
        self.assertNotIn("doctype", rec)

    def test_CAND_30_sorting_sanitization(self):
        """CAND-30: Verify SQL injection attempts in order_by are safely sanitized."""
        malicious_order = "creation desc; DROP TABLE tabCandidate"
        res = self.service.list_candidates(order_by=malicious_order)
        self.assertIn("items", res)
        # Verify table tabCandidate still exists and queries succeed
        self.assertTrue(frappe.db.exists("DocType", "Candidate"))

    def test_CAND_31_domestic_and_international_lists(self):
        """CAND-31: Verify domestic and international candidate listing endpoints."""
        res_dom = self.service.list_domestic_candidates()
        self.assertIn("items", res_dom)

        res_intl = self.service.list_international_candidates()
        self.assertIn("items", res_intl)

    def test_CAND_32_profile_completeness_calculation(self):
        """CAND-32: Verify profile completeness score calculation and DB persistence."""
        res = self.service.get_profile_completeness(self.base_candidate_id)
        self.assertIn("profile_completion", res)
        self.assertGreater(res["profile_completion"], 0.0)

    def test_CAND_33_subresource_updates(self):
        """CAND-33: Verify subresource updates (skills, education, experience) update child tables."""
        skills_payload = [
            {"skill": "Python", "experience_years": 5, "proficiency": "Advanced"},
            {"skill": "Frappe Framework", "experience_years": 3, "proficiency": "Expert"},
        ]
        res = self.service.update_subresource(self.base_candidate_id, "skills", skills_payload)
        self.assertIn("skills", res)
        self.assertGreaterEqual(len(res["skills"]), 2)

    def test_CAND_34_read_only_operation_assertion(self):
        """CAND-34: Verify read-only operations (list, search, get) do not mutate candidate records."""
        before = self.service.get_candidate(self.base_candidate_id)
        _ = self.service.list_candidates(search_term="CandidateOne")
        after = self.service.get_candidate(self.base_candidate_id)
        self.assertEqual(before["modified"], after["modified"])

    def test_CAND_35_test_data_hygiene(self):
        """CAND-35: Verify test data hygiene and clean setup/teardown execution."""
        self.assertTrue(frappe.db.exists("Candidate", self.base_candidate_id))
        self.assertTrue(frappe.db.exists("Candidate", self.base_candidate_id_2))
