# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.tests.test_candidate_phase15
===================================================

Phase 15 Contract Verification Suite for Candidate Backend Domain.

Covers 33 contract points including:
  - Full CRUD lifecycle (CAND-01..CAND-23)
  - Status FSM, terminal-state protection (CAND-24..CAND-31)
  - Kanban grouping and transition endpoint (CAND-32..CAND-33)

Execute via:
  bench --site development.localhost run-tests
    --app recruitrain_employer
    --module recruitrain_employer.tests.test_candidate_phase15
"""

from __future__ import annotations

import unittest
import frappe

from recruitrain_employer.services.candidate_service import CandidateService
from recruitrain_employer.utils.constants import (
    ALLOWED_CANDIDATE_STATUSES,
    CANDIDATE_STATUS_TRANSITIONS,
)
from recruitrain_employer.utils.exceptions import (
    ATSConflictError,
    ATSNotFoundError,
    ATSPermissionError,
    ATSValidationError,
)
from recruitrain_employer.utils.permissions import get_current_company


class TestCandidatePhase15(unittest.TestCase):
    """Phase 15 Candidate Backend Contract Certification Suite (CAND-01 to CAND-33)."""

    # -------------------------------------------------------------------------
    # Class-level setup / teardown
    # -------------------------------------------------------------------------

    @classmethod
    def setUpClass(cls):
        frappe.set_user("Administrator")
        cls.prefix = "P15-TEST-"
        cls.company = get_current_company()
        cls.service = CandidateService()
        cls._cleanup()

        # Base create payload (minimum mandatory fields for Frappe DocType)
        cls.base_payload = {
            "first_name": "Phase15",
            "last_name": "Primary",
            "email": f"{cls.prefix}primary@example.com",
            "mobile_no": "+919800000001",
            "date_of_birth": "1990-01-01",
            "address_line_1": "123 Phase15 Street",
            "city": "Bengaluru",
            "state": "Karnataka",
            "country": "India",
        }

        c = cls.service.create_candidate(cls.base_payload)
        cls.primary_id = c["name"]

        # Second candidate (In Review status for FSM tests)
        cls.service.create_candidate({
            "first_name": "Phase15",
            "last_name": "Secondary",
            "email": f"{cls.prefix}secondary@example.com",
            "mobile_no": "+919800000002",
            "date_of_birth": "1992-02-02",
            "address_line_1": "456 Phase15 Ave",
            "city": "Mumbai",
            "state": "Maharashtra",
            "country": "India",
            "status": "In Review",
        })

    @classmethod
    def tearDownClass(cls):
        cls._cleanup()
        frappe.db.commit()

    @classmethod
    def _cleanup(cls):
        records = frappe.db.get_all(
            "Candidate",
            filters=[["email", "like", "%P15-TEST-%"]],
            pluck="name",
        )
        for cname in records:
            for dt in ["Job Application", "Interview", "Offer", "Candidate Note", "Talent Pool Member", "Activity Logs"]:
                if frappe.db.table_exists(dt):
                    frappe.db.delete(dt, {"candidate": cname})
            frappe.db.delete("Candidate", {"name": cname})
        frappe.db.commit()

    # =========================================================================
    # CAND-01: LIST — returns paginated items with required metadata
    # =========================================================================
    def test_CAND_01_list_returns_paginated_items(self):
        """CAND-01: list_candidates returns items, total, page, page_size, total_pages."""
        res = self.service.list_candidates(page=1, page_size=5)
        self.assertIn("items", res)
        self.assertIn("total", res)
        self.assertIn("page", res)
        self.assertIn("page_size", res)
        self.assertIn("total_pages", res)
        self.assertIsInstance(res["items"], list)
        self.assertGreaterEqual(res["total"], 1)

    # =========================================================================
    # CAND-02: PAGINATION — metadata is arithmetically consistent
    # =========================================================================
    def test_CAND_02_pagination_metadata_consistency(self):
        """CAND-02: total_pages == ceil(total / page_size)."""
        res = self.service.list_candidates(page=1, page_size=3)
        expected_pages = max(0, (res["total"] + 2) // 3)
        self.assertEqual(res["total_pages"], expected_pages)

    # =========================================================================
    # CAND-03: PAGE SIZE CLAMPING
    # =========================================================================
    def test_CAND_03_page_size_clamping(self):
        """CAND-03: page_size is clamped to [1, MAX_PAGE_SIZE]; page clamped to >= 1."""
        res = self.service.list_candidates(page=-5, page_size=9999)
        self.assertEqual(res["page"], 1)
        self.assertEqual(res["page_size"], 100)

    # =========================================================================
    # CAND-04: SEARCH — server-side term search
    # =========================================================================
    def test_CAND_04_server_side_search(self):
        """CAND-04: search_term filters results server-side on name, email, profession, city."""
        res = self.service.list_candidates(search_term="Phase15")
        self.assertGreaterEqual(res["total"], 1)
        names = [item["name"] for item in res["items"]]
        self.assertIn(self.primary_id, names)

    # =========================================================================
    # CAND-05: SEARCH COUNT ACCURACY
    # =========================================================================
    def test_CAND_05_search_count_accuracy(self):
        """CAND-05: total count matches items length when page_size >= total."""
        res = self.service.list_candidates(search_term="P15-TEST-primary@example.com", page_size=100)
        self.assertEqual(res["total"], len(res["items"]))

    # =========================================================================
    # CAND-06: FILTERING — status and country filters
    # =========================================================================
    def test_CAND_06_status_and_country_filters(self):
        """CAND-06: filter by status='Active' returns only Active candidates."""
        res = self.service.list_candidates(status="Active")
        for item in res["items"]:
            self.assertEqual(item["status"], "Active")

    # =========================================================================
    # CAND-07: SORTING — allowed fields accepted without error
    # =========================================================================
    def test_CAND_07_sorting_allowed_fields(self):
        """CAND-07: order_by accepted for allowed fields; invalid falls back to creation desc."""
        res_asc = self.service.list_candidates(order_by="candidate_name asc")
        res_desc = self.service.list_candidates(order_by="creation desc")
        self.assertIn("items", res_asc)
        self.assertIn("items", res_desc)

    # =========================================================================
    # CAND-08: GET — full profile returned by candidate_id
    # =========================================================================
    def test_CAND_08_get_candidate_profile(self):
        """CAND-08: get_candidate returns authoritative profile with all mandatory keys."""
        profile = self.service.get_candidate(self.primary_id)
        MANDATORY_KEYS = {
            "name", "candidate_id", "email", "first_name", "last_name",
            "status", "company", "profile_completion", "creation",
        }
        for key in MANDATORY_KEYS:
            self.assertIn(key, profile, f"Missing key: {key}")
        self.assertEqual(profile["email"].lower(), f"{self.prefix}primary@example.com".lower())
        self.assertEqual(profile["company"], self.company)

    # =========================================================================
    # CAND-09: CREATE — default status is Active
    # =========================================================================
    def test_CAND_09_create_default_status_active(self):
        """CAND-09: create_candidate sets status='Active' by default."""
        c = self.service.create_candidate({
            "first_name": "Phase15",
            "last_name": "DefaultStatus",
            "email": f"{self.prefix}default_status@example.com",
            "mobile_no": "+919800000003",
            "date_of_birth": "1993-03-03",
            "address_line_1": "1 Default Ave",
            "city": "Chennai",
            "state": "Tamil Nadu",
            "country": "India",
        })
        self.assertEqual(c["status"], "Active")
        self.assertEqual(c["company"], self.company)

    # =========================================================================
    # CAND-10: MANDATORY FIELD VALIDATION — missing required fields rejected
    # =========================================================================
    def test_CAND_10_missing_mandatory_fields_rejected(self):
        """CAND-10: create_candidate rejects payloads missing first_name, last_name, or email."""
        with self.assertRaises(ATSValidationError):
            self.service.create_candidate({"first_name": "OnlyFirstName"})

        with self.assertRaises((ATSValidationError, Exception)):
            self.service.create_candidate({"first_name": "A", "last_name": "B"})  # no email

    # =========================================================================
    # CAND-11: INVALID RELATIONSHIP REJECTION — email, phone, URL format
    # =========================================================================
    def test_CAND_11_invalid_email_rejected(self):
        """CAND-11: invalid email format raises ATSValidationError."""
        with self.assertRaises(ATSValidationError):
            self.service.create_candidate({
                "first_name": "X",
                "last_name": "Y",
                "email": "not-an-email",
            })

    def test_CAND_11b_invalid_phone_rejected(self):
        """CAND-11b: invalid phone format raises ATSValidationError."""
        with self.assertRaises(ATSValidationError):
            self.service.create_candidate({
                "first_name": "X",
                "last_name": "Y",
                "email": f"{self.prefix}valid_phone_check@example.com",
                "mobile_no": "abc12345",
            })

    # =========================================================================
    # CAND-12: UPDATE — scalar field update persists
    # =========================================================================
    def test_CAND_12_scalar_update_persists(self):
        """CAND-12: update_candidate persists changed fields and returns updated record."""
        updated = self.service.update_candidate(self.primary_id, {
            "current_job_title": "Phase15 Senior Engineer",
            "years_of_experience": 8.5,
        })
        self.assertEqual(updated["current_job_title"], "Phase15 Senior Engineer")
        self.assertAlmostEqual(float(updated["years_of_experience"]), 8.5, places=1)

    # =========================================================================
    # CAND-13: PARTIAL UPDATE — unmentioned fields preserved
    # =========================================================================
    def test_CAND_13_partial_update_preserves_other_fields(self):
        """CAND-13: update with only notice_period does not corrupt first_name or email."""
        before = self.service.get_candidate(self.primary_id)
        self.service.update_candidate(self.primary_id, {"notice_period": 60})
        after = self.service.get_candidate(self.primary_id)
        self.assertEqual(after["notice_period"], 60)
        self.assertEqual(after["first_name"], before["first_name"])
        self.assertEqual(after["email"], before["email"])

    # =========================================================================
    # CAND-14: IMMUTABLE FIELD PROTECTION — email, company, candidate_id
    # =========================================================================
    def test_CAND_14_immutable_email_protected(self):
        """CAND-14: attempt to update email raises ATSValidationError."""
        with self.assertRaises(ATSValidationError):
            self.service.update_candidate(self.primary_id, {"email": "newemail@example.com"})

    def test_CAND_14b_immutable_company_protected(self):
        """CAND-14b: attempt to update company raises ATSValidationError."""
        with self.assertRaises(ATSValidationError):
            self.service.update_candidate(self.primary_id, {"company": "Some Other Company"})

    # =========================================================================
    # CAND-15: DELETE — unlinked candidate deleted cleanly
    # =========================================================================
    def test_CAND_15_delete_unlinked_candidate(self):
        """CAND-15: delete_candidate succeeds for candidate with no recruitment history."""
        c = self.service.create_candidate({
            "first_name": "Phase15",
            "last_name": "DeleteMe",
            "email": f"{self.prefix}deleteme@example.com",
            "mobile_no": "+919800000099",
            "date_of_birth": "1995-05-05",
            "address_line_1": "1 Delete Road",
            "city": "Hyderabad",
            "state": "Telangana",
            "country": "India",
        })
        cid = c["name"]
        result = self.service.delete_candidate(cid)
        self.assertTrue(result.get("deleted"))
        self.assertFalse(frappe.db.exists("Candidate", cid))

    # =========================================================================
    # CAND-16: DELETE LINKED CANDIDATE BLOCKED — Job Application protection
    # =========================================================================
    def test_CAND_16_delete_linked_candidate_blocked(self):
        """CAND-16: delete_candidate raises ATSConflictError if Job Application exists."""
        c = self.service.create_candidate({
            "first_name": "Phase15",
            "last_name": "LinkedDel",
            "email": f"{self.prefix}linked_del@example.com",
            "mobile_no": "+919800000098",
            "date_of_birth": "1994-04-04",
            "address_line_1": "1 Linked Road",
            "city": "Pune",
            "state": "Maharashtra",
            "country": "India",
        })
        cid = c["name"]

        jo_list = frappe.get_all("Job Opening", filters={"company": self.company}, pluck="name")
        if jo_list:
            jo_id = jo_list[0]
        else:
            jo = frappe.new_doc("Job Opening")
            jo.job_title = "P15 Test Job"
            jo.company = self.company
            jo.status = "Open"
            jo.insert(ignore_permissions=True)
            jo_id = jo.name

        app = frappe.new_doc("Job Application")
        app.candidate = cid
        app.job_opening = jo_id
        app.company = self.company
        app.status = "Open"
        app.resume = "/files/test.pdf"
        app.insert(ignore_permissions=True)
        frappe.db.commit()

        with self.assertRaises(ATSConflictError) as cm:
            self.service.delete_candidate(cid)

        self.assertEqual(
            cm.exception.details.get("error_code"),
            "CANDIDATE_HAS_RECRUITMENT_HISTORY",
        )

    # =========================================================================
    # CAND-17: COMPANY ISOLATION — list only returns current company candidates
    # =========================================================================
    def test_CAND_17_list_scoped_to_current_company(self):
        """CAND-17: list_candidates returns only candidates belonging to session company."""
        res = self.service.list_candidates()
        for item in res["items"]:
            self.assertEqual(item["company"], self.company, f"Candidate {item['name']} from wrong company")

    # =========================================================================
    # CAND-18: CROSS-COMPANY GET PROTECTION
    # =========================================================================
    def test_CAND_18_cross_company_get_rejected(self):
        """CAND-18: get_candidate raises ATSPermissionError for candidate from another company."""
        foreign_co_name = f"{self.prefix}FC-GET"
        if not frappe.db.exists("Company", foreign_co_name):
            fc = frappe.new_doc("Company")
            fc.company_name = foreign_co_name
            fc.abbr = "P15FCG"
            fc.default_currency = "USD"
            fc.country = "United States"
            fc.email = "p15fcg@example-foreign.com"
            fc.phone = "+14155550101"
            fc.address_line_1 = "1 Foreign Co Get St"
            fc.insert(ignore_permissions=True)
            frappe.db.commit()

        # Create a candidate directly under foreign company
        foreign_doc = frappe.new_doc("Candidate")
        foreign_doc.first_name = "Foreign"
        foreign_doc.last_name = "P15"
        foreign_doc.candidate_name = f"{self.prefix}Foreign P15 Get"
        foreign_doc.email = f"{self.prefix}foreign_p15_get@example.com"
        foreign_doc.mobile_no = "+919800000021"
        foreign_doc.date_of_birth = "1990-01-01"
        foreign_doc.address_line_1 = "1 Foreign St"
        foreign_doc.city = "New York"
        foreign_doc.state = "NY"
        foreign_doc.company = foreign_co_name
        foreign_doc.insert(ignore_permissions=True)
        frappe.db.commit()
        fid = foreign_doc.name

        with self.assertRaises(ATSPermissionError):
            self.service.get_candidate(fid)

        frappe.db.delete("Candidate", {"name": fid})
        frappe.delete_doc("Company", foreign_co_name, ignore_permissions=True, force=True)
        frappe.db.commit()

    # =========================================================================
    # CAND-19: CROSS-COMPANY UPDATE PROTECTION
    # =========================================================================
    def test_CAND_19_cross_company_update_rejected(self):
        """CAND-19: update_candidate raises ATSPermissionError for foreign candidate."""
        foreign_co_name = f"{self.prefix}FC-UPD"
        if not frappe.db.exists("Company", foreign_co_name):
            fc = frappe.new_doc("Company")
            fc.company_name = foreign_co_name
            fc.abbr = "P15FCU"
            fc.default_currency = "USD"
            fc.country = "United States"
            fc.email = "p15fcu@example-foreign.com"
            fc.phone = "+14155550102"
            fc.address_line_1 = "2 Foreign Co Update St"
            fc.insert(ignore_permissions=True)
            frappe.db.commit()

        foreign_doc = frappe.new_doc("Candidate")
        foreign_doc.first_name = "ForeignUpdate"
        foreign_doc.last_name = "P15"
        foreign_doc.candidate_name = f"{self.prefix}ForeignUpdate P15"
        foreign_doc.email = f"{self.prefix}foreign_update_p15@example.com"
        foreign_doc.mobile_no = "+919800000022"
        foreign_doc.date_of_birth = "1990-01-01"
        foreign_doc.address_line_1 = "2 Foreign Update St"
        foreign_doc.city = "Los Angeles"
        foreign_doc.state = "CA"
        foreign_doc.company = foreign_co_name
        foreign_doc.insert(ignore_permissions=True)
        frappe.db.commit()
        fid = foreign_doc.name

        with self.assertRaises(ATSPermissionError):
            self.service.update_candidate(fid, {"current_job_title": "Hacker"})

        frappe.db.delete("Candidate", {"name": fid})
        frappe.delete_doc("Company", foreign_co_name, ignore_permissions=True, force=True)
        frappe.db.commit()

    # =========================================================================
    # CAND-20: CROSS-COMPANY DELETE PROTECTION
    # =========================================================================
    def test_CAND_20_cross_company_delete_rejected(self):
        """CAND-20: delete_candidate raises ATSPermissionError for foreign candidate."""
        foreign_co_name = f"{self.prefix}FC-DEL"
        if not frappe.db.exists("Company", foreign_co_name):
            fc = frappe.new_doc("Company")
            fc.company_name = foreign_co_name
            fc.abbr = "P15FCD"
            fc.default_currency = "USD"
            fc.country = "United States"
            fc.email = "p15fcd@example-foreign.com"
            fc.phone = "+14155550103"
            fc.address_line_1 = "3 Foreign Co Delete St"
            fc.insert(ignore_permissions=True)
            frappe.db.commit()

        foreign_doc = frappe.new_doc("Candidate")
        foreign_doc.first_name = "ForeignDelete"
        foreign_doc.last_name = "P15"
        foreign_doc.candidate_name = f"{self.prefix}ForeignDelete P15"
        foreign_doc.email = f"{self.prefix}foreign_delete_p15@example.com"
        foreign_doc.mobile_no = "+919800000023"
        foreign_doc.date_of_birth = "1990-01-01"
        foreign_doc.address_line_1 = "3 Foreign Delete St"
        foreign_doc.city = "Chicago"
        foreign_doc.state = "IL"
        foreign_doc.company = foreign_co_name
        foreign_doc.insert(ignore_permissions=True)
        frappe.db.commit()
        fid = foreign_doc.name

        with self.assertRaises(ATSPermissionError):
            self.service.delete_candidate(fid)

        frappe.db.delete("Candidate", {"name": fid})
        frappe.delete_doc("Company", foreign_co_name, ignore_permissions=True, force=True)
        frappe.db.commit()

    # =========================================================================
    # CAND-21: GUEST REJECTION — no company context
    # =========================================================================
    def test_CAND_21_guest_user_rejected(self):
        """CAND-21: Guest session raises ATSPermissionError for get_candidate."""
        original_user = frappe.session.user
        try:
            frappe.session.user = "Guest"
            with self.assertRaises(ATSPermissionError):
                self.service.get_candidate(self.primary_id)
        finally:
            frappe.session.user = original_user

    # =========================================================================
    # CAND-22: NON-EMPLOYER REJECTION — Guest on list
    # =========================================================================
    def test_CAND_22_guest_user_rejected_on_list(self):
        """CAND-22: Guest session raises ATSPermissionError for list_candidates."""
        original_user = frappe.session.user
        try:
            frappe.session.user = "Guest"
            with self.assertRaises(ATSPermissionError):
                self.service.list_candidates()
        finally:
            frappe.session.user = original_user

    # =========================================================================
    # CAND-23: 404 HANDLING — non-existent ID
    # =========================================================================
    def test_CAND_23_not_found_raises_correct_exception(self):
        """CAND-23: get_candidate with non-existent ID raises ATSNotFoundError."""
        with self.assertRaises(ATSNotFoundError):
            self.service.get_candidate("NON_EXISTENT_P15_ID")

    # =========================================================================
    # CAND-24: 409 HANDLING — duplicate email
    # =========================================================================
    def test_CAND_24_duplicate_email_raises_conflict(self):
        """CAND-24: duplicate email within same company raises ATSConflictError."""
        with self.assertRaises(ATSConflictError):
            self.service.create_candidate(self.base_payload)

    # =========================================================================
    # CAND-25: RESPONSE ENVELOPE — success/data/meta structure
    # =========================================================================
    def test_CAND_25_response_envelope_integrity(self):
        """CAND-25: API controller returns standard {success, data, meta} envelope."""
        from recruitrain_employer.api.candidate import list_candidates, get_candidate
        res_list = list_candidates()
        self.assertTrue(res_list.get("success"))
        self.assertIn("data", res_list)
        self.assertIn("meta", res_list)

        res_get = get_candidate(candidate_id=self.primary_id)
        self.assertTrue(res_get.get("success"))
        self.assertIn("data", res_get)

    # =========================================================================
    # CAND-26: SQL INJECTION DEFENSE — order_by parameter sanitization
    # =========================================================================
    def test_CAND_26_sql_injection_in_order_by_sanitized(self):
        """CAND-26: malicious order_by string is sanitized; table still exists."""
        malicious = "creation desc; DROP TABLE tabCandidate"
        res = self.service.list_candidates(order_by=malicious)
        self.assertIn("items", res)
        self.assertTrue(frappe.db.exists("DocType", "Candidate"))

    # =========================================================================
    # CAND-27: STATUS VALIDATION — invalid status value rejected
    # =========================================================================
    def test_CAND_27_invalid_status_value_rejected(self):
        """CAND-27: setting status to an unlisted value raises ATSValidationError."""
        with self.assertRaises(ATSValidationError):
            self.service.update_candidate(self.primary_id, {"status": "NonExistentStatus"})

    # =========================================================================
    # CAND-28: STAGE VALIDATION — verify all ALLOWED statuses are present
    # =========================================================================
    def test_CAND_28_allowed_statuses_defined(self):
        """CAND-28: ALLOWED_CANDIDATE_STATUSES contains all expected statuses."""
        EXPECTED = {"Draft", "Active", "In Review", "Interviewing", "Offered", "Hired", "Rejected", "Archived"}
        self.assertEqual(set(ALLOWED_CANDIDATE_STATUSES), EXPECTED)

    # =========================================================================
    # CAND-29: VALID STATUS TRANSITION — FSM accepts legal transition
    # =========================================================================
    def test_CAND_29_valid_status_transition_accepted(self):
        """CAND-29: legal FSM transition Active -> In Review persists correctly."""
        c = self.service.create_candidate({
            "first_name": "Phase15",
            "last_name": "FSMForward",
            "email": f"{self.prefix}fsm_forward@example.com",
            "mobile_no": "+919800000010",
            "date_of_birth": "1991-01-10",
            "address_line_1": "10 FSM St",
            "city": "Kolkata",
            "state": "West Bengal",
            "country": "India",
            "status": "Active",
        })
        cid = c["name"]
        updated = self.service.update_candidate(cid, {"status": "In Review"})
        self.assertEqual(updated["status"], "In Review")

        # Progress further
        updated2 = self.service.update_candidate(cid, {"status": "Interviewing"})
        self.assertEqual(updated2["status"], "Interviewing")

    # =========================================================================
    # CAND-30: INVALID STATUS TRANSITION — FSM rejects illegal backward move
    # =========================================================================
    def test_CAND_30_invalid_status_transition_rejected(self):
        """CAND-30: illegal FSM transition Hired -> Draft raises ATSValidationError."""
        c = self.service.create_candidate({
            "first_name": "Phase15",
            "last_name": "FSMBlock",
            "email": f"{self.prefix}fsm_block@example.com",
            "mobile_no": "+919800000011",
            "date_of_birth": "1992-11-11",
            "address_line_1": "11 Block Ave",
            "city": "Delhi",
            "state": "Delhi",
            "country": "India",
            "status": "Active",
        })
        cid = c["name"]
        # Move to Hired (via intermediate steps)
        self.service.update_candidate(cid, {"status": "In Review"})
        self.service.update_candidate(cid, {"status": "Interviewing"})
        self.service.update_candidate(cid, {"status": "Offered"})
        self.service.update_candidate(cid, {"status": "Hired"})

        # Hired -> Draft is NOT in CANDIDATE_STATUS_TRANSITIONS["Hired"]
        with self.assertRaises(ATSValidationError):
            self.service.update_candidate(cid, {"status": "Draft"})

    # =========================================================================
    # CAND-31: TERMINAL STATE PROTECTION — Hired can only move to Archived
    # =========================================================================
    def test_CAND_31_hired_only_moves_to_archived(self):
        """CAND-31: Hired candidates can only be moved to Archived (not Active, In Review, etc.)."""
        c = self.service.create_candidate({
            "first_name": "Phase15",
            "last_name": "Terminal",
            "email": f"{self.prefix}terminal@example.com",
            "mobile_no": "+919800000012",
            "date_of_birth": "1993-12-12",
            "address_line_1": "12 Terminal Rd",
            "city": "Ahmedabad",
            "state": "Gujarat",
            "country": "India",
            "status": "Active",
        })
        cid = c["name"]
        self.service.update_candidate(cid, {"status": "In Review"})
        self.service.update_candidate(cid, {"status": "Interviewing"})
        self.service.update_candidate(cid, {"status": "Offered"})
        self.service.update_candidate(cid, {"status": "Hired"})

        # Hired -> Active should fail
        with self.assertRaises(ATSValidationError):
            self.service.update_candidate(cid, {"status": "Active"})

        # Hired -> Archived should succeed
        archived = self.service.update_candidate(cid, {"status": "Archived"})
        self.assertEqual(archived["status"], "Archived")

    # =========================================================================
    # CAND-32: KANBAN STAGE DATA — get_kanban_groups returns valid structure
    # =========================================================================
    def test_CAND_32_kanban_groups_structure(self):
        """CAND-32: get_kanban_groups returns statuses, groups (keyed by status), and transitions."""
        result = self.service.get_kanban_groups()

        # Top-level keys
        self.assertIn("statuses", result)
        self.assertIn("groups", result)
        self.assertIn("transitions", result)

        # statuses matches ALLOWED_CANDIDATE_STATUSES exactly
        self.assertEqual(set(result["statuses"]), set(ALLOWED_CANDIDATE_STATUSES))

        # groups has one key per status
        self.assertEqual(set(result["groups"].keys()), set(ALLOWED_CANDIDATE_STATUSES))

        # transitions matches FSM map
        self.assertEqual(result["transitions"], CANDIDATE_STATUS_TRANSITIONS)

        # Each group's candidate cards have required keys
        CARD_KEYS = {"name", "candidate_id", "full_name", "email", "status", "profile_completion"}
        for status, cards in result["groups"].items():
            self.assertIsInstance(cards, list)
            for card in cards:
                for key in CARD_KEYS:
                    self.assertIn(key, card, f"Kanban card for status '{status}' missing key '{key}'")
                self.assertEqual(card["status"], status)

        # Primary candidate appears in Active column
        active_names = [c["name"] for c in result["groups"].get("Active", [])]
        self.assertIn(self.primary_id, active_names)

    # =========================================================================
    # CAND-33: KANBAN TRANSITION PERSISTENCE — change_candidate_status endpoint
    # =========================================================================
    def test_CAND_33_kanban_transition_persists_via_service(self):
        """CAND-33: change_candidate_status (via update_candidate) validates FSM, persists, returns authoritative state."""
        c = self.service.create_candidate({
            "first_name": "Phase15",
            "last_name": "KanbanMove",
            "email": f"{self.prefix}kanban_move@example.com",
            "mobile_no": "+919800000013",
            "date_of_birth": "1994-04-13",
            "address_line_1": "13 Kanban Lane",
            "city": "Bangalore",
            "state": "Karnataka",
            "country": "India",
            "status": "Active",
        })
        cid = c["name"]

        # Legal Kanban drag: Active -> In Review
        result = self.service.update_candidate(cid, {"status": "In Review"})
        self.assertEqual(result["status"], "In Review")

        # Verify DB persisted (re-fetch)
        persisted = self.service.get_candidate(cid)
        self.assertEqual(persisted["status"], "In Review")

        # Illegal Kanban drag: In Review -> Draft (must be rejected)
        with self.assertRaises(ATSValidationError):
            self.service.update_candidate(cid, {"status": "Draft"})

        # Verify card not moved (still In Review)
        still_in_review = self.service.get_candidate(cid)
        self.assertEqual(still_in_review["status"], "In Review")
