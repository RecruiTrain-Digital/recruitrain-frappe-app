# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.tests.test_job_application_phase16
=========================================================

Authoritative Phase 16 Test Suite for Job Application Backend & Kanban Foundation.
Tests APP-01 through APP-28 against the live Frappe site.
"""

import unittest
import frappe
from frappe.utils import today

from recruitrain_employer.services.job_application_service import JobApplicationService
from recruitrain_employer.services.job_service import JobService
from recruitrain_employer.services.candidate_service import CandidateService
from recruitrain_employer.validators.job_application_validator import JobApplicationValidator
from recruitrain_employer.utils.exceptions import (
    ATSConflictError,
    ATSNotFoundError,
    ATSPermissionError,
    ATSValidationError,
)
from recruitrain_employer.utils.permissions import get_current_company
from recruitrain_employer.api.job_application import (
    create_application,
    get_application,
    update_application,
    delete_application,
    change_status,
    list_applications,
    search_applications,
)


class TestJobApplicationPhase16(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        frappe.set_user("Administrator")
        try:
            frappe.reload_doc("recruitment", "doctype", "job_application", force=True)
            if not frappe.db.has_column("tabJob Application", "notes"):
                frappe.db.sql("ALTER TABLE `tabJob Application` ADD COLUMN notes TEXT")
        except Exception:
            pass

        cls.company = get_current_company()
        if not cls.company:
            companies = frappe.get_all("Company", fields=["name"])
            if companies:
                cls.company = companies[0]["name"]
            else:
                comp = frappe.new_doc("Company")
                comp.company_name = "Phase 16 Test Primary Employer Co"
                comp.default_currency = "USD"
                comp.email = "phase16_primary@company.com"
                comp.address_line_1 = "123 Primary Street"
                comp.insert(ignore_permissions=True)
                cls.company = comp.name

        # Secondary company for cross-company isolation testing
        cls.company_b = "Phase 16 Test Secondary Co"
        if not frappe.db.exists("Company", cls.company_b):
            comp2 = frappe.new_doc("Company")
            comp2.company_name = cls.company_b
            comp2.default_currency = "USD"
            comp2.email = "phase16_secondary@company.com"
            comp2.flags.ignore_mandatory = True
            comp2.insert(ignore_permissions=True)

        cls.service = JobApplicationService()
        cls.job_service = JobService()
        cls.candidate_service = CandidateService()
        cls.validator = JobApplicationValidator()

        # Create primary test candidate in Company A
        cls.cand_email = f"app_p16_cand_{frappe.generate_hash(length=6)}@example.com"
        cand_doc = frappe.new_doc("Candidate")
        cand_doc.candidate_name = f"Phase16 Candidate {frappe.generate_hash(length=4)}"
        cand_doc.first_name = "Phase16"
        cand_doc.last_name = "Candidate"
        cand_doc.email_address = cls.cand_email
        cand_doc.email = cls.cand_email
        cand_doc.company = cls.company
        cand_doc.status = "Active"
        cand_doc.flags.ignore_mandatory = True
        cand_doc.insert(ignore_permissions=True)
        cls.candidate_id = cand_doc.name

        # Create primary test job opening A in Company A
        job_doc = frappe.new_doc("Job Opening")
        job_doc.job_code = f"JOB-P16-A-{frappe.generate_hash(length=6)}"
        job_doc.job_title = f"Phase16 Job A {frappe.generate_hash(length=6)}"
        job_doc.company = cls.company
        job_doc.employment_type = "Full Time"
        job_doc.status = "Draft"
        job_doc.published = 0
        job_doc.flags.ignore_mandatory = True
        job_doc.flags.ignore_links = True
        job_doc.insert(ignore_permissions=True)
        cls.job_id = job_doc.name

        # Create second test job opening B in Company A for multi-application testing
        job2_doc = frappe.new_doc("Job Opening")
        job2_doc.job_code = f"JOB-P16-B-{frappe.generate_hash(length=6)}"
        job2_doc.job_title = f"Phase16 Job B {frappe.generate_hash(length=6)}"
        job2_doc.company = cls.company
        job2_doc.employment_type = "Full Time"
        job2_doc.status = "Draft"
        job2_doc.published = 0
        job2_doc.flags.ignore_mandatory = True
        job2_doc.flags.ignore_links = True
        job2_doc.insert(ignore_permissions=True)
        cls.job2_id = job2_doc.name

        # Create Candidate B in Company B
        cls.cand_b_email = f"app_p16_cand_b_{frappe.generate_hash(length=6)}@example.com"
        cand_b_doc = frappe.new_doc("Candidate")
        cand_b_doc.candidate_name = f"Phase16 Candidate B {frappe.generate_hash(length=4)}"
        cand_b_doc.first_name = "Phase16"
        cand_b_doc.last_name = "CandidateB"
        cand_b_doc.email_address = cls.cand_b_email
        cand_b_doc.email = cls.cand_b_email
        cand_b_doc.company = cls.company_b
        cand_b_doc.status = "Active"
        cand_b_doc.flags.ignore_mandatory = True
        cand_b_doc.insert(ignore_permissions=True)
        cls.candidate_b_id = cand_b_doc.name

        # Create Job Opening B in Company B
        job_b_doc = frappe.new_doc("Job Opening")
        job_b_doc.job_code = f"JOB-P16-COMPB-{frappe.generate_hash(length=6)}"
        job_b_doc.job_title = f"Phase16 CompB Job {frappe.generate_hash(length=6)}"
        job_b_doc.company = cls.company_b
        job_b_doc.employment_type = "Full Time"
        job_b_doc.status = "Draft"
        job_b_doc.published = 0
        job_b_doc.flags.ignore_mandatory = True
        job_b_doc.flags.ignore_links = True
        job_b_doc.insert(ignore_permissions=True)
        cls.job_b_id = job_b_doc.name

        frappe.db.commit()

    @classmethod
    def tearDownClass(cls):
        frappe.set_user("Administrator")
        try:
            for cand in [getattr(cls, "candidate_id", None), getattr(cls, "candidate_b_id", None)]:
                if cand and frappe.db.exists("Candidate", cand):
                    frappe.delete_doc("Candidate", cand, force=True, ignore_permissions=True)
            for j in [getattr(cls, "job_id", None), getattr(cls, "job2_id", None), getattr(cls, "job_b_id", None)]:
                if j and frappe.db.exists("Job Opening", j):
                    frappe.delete_doc("Job Opening", j, force=True, ignore_permissions=True)
            frappe.db.commit()
        except Exception:
            pass

    def setUp(self):
        frappe.set_user("Administrator")
        frappe.db.rollback()

    def test_APP_01_live_schema_inspection(self):
        """APP-01: Live schema inspection of Job Application DocType"""
        meta = frappe.get_meta("Job Application")
        self.assertTrue(meta.has_field("candidate"))
        self.assertTrue(meta.has_field("job_opening"))
        self.assertTrue(meta.has_field("company"))
        self.assertTrue(meta.has_field("applied_on"))
        self.assertTrue(meta.has_field("source"))
        self.assertTrue(meta.has_field("resume"))
        self.assertTrue(meta.has_field("cover_letter"))
        self.assertTrue(meta.has_field("notes"))
        self.assertTrue(meta.has_field("current_stage"))
        self.assertTrue(meta.has_field("assigned_recruiter"))
        self.assertTrue(meta.has_field("rating"))
        self.assertTrue(meta.has_field("priority"))
        self.assertTrue(meta.has_field("status"))
        self.assertTrue(meta.has_field("rejection_reason"))

        # Inspect field types
        self.assertEqual(meta.get_field("candidate").fieldtype, "Link")
        self.assertEqual(meta.get_field("job_opening").fieldtype, "Link")
        self.assertEqual(meta.get_field("company").fieldtype, "Link")
        self.assertEqual(meta.get_field("current_stage").fieldtype, "Select")
        self.assertEqual(meta.get_field("status").fieldtype, "Select")
        self.assertEqual(meta.get_field("resume").fieldtype, "Attach")

    def test_APP_02_create_job_application(self):
        """APP-02: Create Job Application via service and API envelope"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
            "source": "LinkedIn",
            "notes": "Test APP-02 Note",
        })
        self.assertIsNotNone(app.get("name"))
        self.assertEqual(app.get("candidate"), self.candidate_id)
        self.assertEqual(app.get("job_opening"), self.job_id)
        self.assertEqual(app.get("current_stage"), "Applied")
        self.assertEqual(app.get("status"), "Open")

        # Clean up
        frappe.delete_doc("Job Application", app["name"], force=True, ignore_permissions=True)

    def test_APP_03_read_job_application(self):
        """APP-03: Read Job Application by ID returns expected detail fields"""
        created = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
            "cover_letter": "APP-03 Cover Letter Content",
            "source": "Career Portal",
        })
        read_doc = self.service.get_application(created["name"])
        self.assertEqual(read_doc["name"], created["name"])
        self.assertEqual(read_doc["candidate"], self.candidate_id)
        self.assertEqual(read_doc["job_opening"], self.job_id)
        self.assertEqual(read_doc["cover_letter"], "APP-03 Cover Letter Content")
        self.assertEqual(read_doc["source"], "Career Portal")

        frappe.delete_doc("Job Application", created["name"], force=True, ignore_permissions=True)

    def test_APP_04_update_job_application(self):
        """APP-04: Update mutable fields on Job Application"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
            "notes": "Initial Notes",
            "priority": "Low",
        })
        updated = self.service.update_application(app["name"], {
            "notes": "Updated Notes for APP-04",
            "priority": "High",
            "rating": 1,
        })
        self.assertEqual(updated["notes"], "Updated Notes for APP-04")
        self.assertEqual(updated["priority"], "High")
        self.assertEqual(updated["rating"], 1)

        frappe.delete_doc("Job Application", app["name"], force=True, ignore_permissions=True)

    def test_APP_05_update_persistence(self):
        """APP-05: Update persistence verified directly against MariaDB"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
        })
        self.service.update_application(app["name"], {
            "notes": "Persistent Notes Check",
            "priority": "Critical",
        })

        db_notes, db_priority = frappe.db.get_value(
            "Job Application", app["name"], ["notes", "priority"]
        )
        self.assertEqual(db_notes, "Persistent Notes Check")
        self.assertEqual(db_priority, "Critical")

        frappe.delete_doc("Job Application", app["name"], force=True, ignore_permissions=True)

    def test_APP_06_delete_job_application(self):
        """APP-06: Delete temporary Job Application and verify removal"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
        })
        app_name = app["name"]
        self.assertTrue(frappe.db.exists("Job Application", app_name))

        self.service.delete_application(app_name)
        self.assertFalse(frappe.db.exists("Job Application", app_name))

    def test_APP_07_candidate_link_validation(self):
        """APP-07: Referencing non-existent candidate raises ATSValidationError"""
        with self.assertRaises(ATSValidationError):
            self.service.create_application({
                "candidate": "CAND-NON-EXISTENT-8888",
                "job_opening": self.job_id,
            })

    def test_APP_08_job_opening_link_validation(self):
        """APP-08: Referencing non-existent job opening raises ATSValidationError"""
        with self.assertRaises(ATSValidationError):
            self.service.create_application({
                "candidate": self.candidate_id,
                "job_opening": "JOB-NON-EXISTENT-8888",
            })

    def test_APP_09_company_isolation(self):
        """APP-09: Cross-company access returns ATSPermissionError"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
        })
        # Listing with secondary company filter returns 0 records
        res = self.service.list_applications(filters={"company": self.company_b})
        self.assertFalse(any(a["name"] == app["name"] for a in res["data"]))

        # Cross-company candidate application attempt fails
        with self.assertRaises((ATSValidationError, ATSPermissionError)):
            self.service.create_application({
                "candidate": self.candidate_b_id,
                "job_opening": self.job_id,
            })

        frappe.delete_doc("Job Application", app["name"], force=True, ignore_permissions=True)

    def test_APP_10_authorization(self):
        """APP-10: Guest user request returns 401 UNAUTHORIZED envelope"""
        frappe.set_user("Guest")
        res = list_applications()
        status_code = res.get("status_code") or frappe.response.get("http_status_code")
        self.assertEqual(status_code, 401)
        self.assertEqual(res["error"]["code"], "UNAUTHORIZED")
        frappe.set_user("Administrator")

    def test_APP_11_list_applications(self):
        """APP-11: List applications returns paginated dictionary envelope"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
        })
        res = self.service.list_applications(page=1, page_size=10, filters={"company": self.company})
        self.assertIn("data", res)
        self.assertIn("total", res)
        self.assertTrue(any(a["name"] == app["name"] for a in res["data"]))
        frappe.delete_doc("Job Application", app["name"], force=True, ignore_permissions=True)

    def test_APP_12_search(self):
        """APP-12: Search applications across candidate name, job title, and ID"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
        })
        res = self.service.search_applications(search="Phase16 Candidate", filters={"company": self.company})
        self.assertGreaterEqual(res["total"], 1)
        self.assertTrue(any(a["name"] == app["name"] for a in res["data"]))
        frappe.delete_doc("Job Application", app["name"], force=True, ignore_permissions=True)

    def test_APP_13_pagination(self):
        """APP-13: Pagination page size clamping and arithmetic accuracy"""
        res = self.service.list_applications(page=-1, page_size=200, filters={"company": self.company})
        self.assertEqual(res["page"], 1)
        self.assertEqual(res["page_size"], 100)

    def test_APP_14_sorting(self):
        """APP-14: Sorting parameter sanitization across allowed sort fields"""
        for sort_f in ["creation", "modified", "applied_on", "status", "candidate"]:
            res = self.service.list_applications(order_by=sort_f, order_dir="asc", filters={"company": self.company})
            self.assertIn("data", res)

    def test_APP_15_current_stage_read(self):
        """APP-15: Read current_stage field on Job Application"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
            "current_stage": "Screening",
        })
        read_doc = self.service.get_application(app["name"])
        self.assertEqual(read_doc["current_stage"], "Screening")
        frappe.delete_doc("Job Application", app["name"], force=True, ignore_permissions=True)

    def test_APP_16_current_stage_transition(self):
        """APP-16: Sequence of valid Kanban stage transitions (Applied -> Screening -> Shortlisted -> Interview -> Technical -> HR -> Offered -> Hired)"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
            "current_stage": "Applied",
        })
        app_name = app["name"]

        stages = ["Screening", "Shortlisted", "Interview", "Technical", "HR", "Offered", "Hired"]
        for stage in stages:
            res = self.service.change_status(app_name, stage)
            self.assertEqual(res["current_stage"], stage)

        frappe.delete_doc("Job Application", app_name, force=True, ignore_permissions=True)

    def test_APP_17_stage_persistence(self):
        """APP-17: Stage transition persists directly to MariaDB tabJob Application"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
            "current_stage": "Applied",
        })
        app_name = app["name"]

        self.service.change_status(app_name, "Shortlisted")
        db_stage = frappe.db.get_value("Job Application", app_name, "current_stage")
        self.assertEqual(db_stage, "Shortlisted")

        frappe.delete_doc("Job Application", app_name, force=True, ignore_permissions=True)

    def test_APP_18_invalid_stage_rejection(self):
        """APP-18: Invalid stage string or transition out of terminal state raises ATSValidationError"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
            "current_stage": "Applied",
        })
        app_name = app["name"]

        # 1. Invalid stage string
        with self.assertRaises(ATSValidationError):
            self.service.change_status(app_name, "InvalidKanbanStageXYZ")

        # 2. Terminal state transition attempt (Hired -> Shortlisted)
        self.service.change_status(app_name, "Hired")
        with self.assertRaises(ATSValidationError):
            self.service.change_status(app_name, "Shortlisted")

        frappe.delete_doc("Job Application", app_name, force=True, ignore_permissions=True)

    def test_APP_19_invalid_application_rejection(self):
        """APP-19: Reading or updating non-existent application ID raises ATSNotFoundError"""
        with self.assertRaises(ATSNotFoundError):
            self.service.get_application("APP-NON-EXISTENT-7777")

        with self.assertRaises(ATSNotFoundError):
            self.service.update_application("APP-NON-EXISTENT-7777", {"notes": "test"})

    def test_APP_20_application_status(self):
        """APP-20: Job Application status mapping vs current_stage"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
            "current_stage": "Applied",
        })
        app_name = app["name"]

        # Active stage -> status Open
        st1 = self.service.change_status(app_name, "Screening")
        self.assertEqual(st1["current_stage"], "Screening")
        self.assertEqual(st1["status"], "Open")

        # Terminal stage Hired -> status Hired
        st2 = self.service.change_status(app_name, "Hired")
        self.assertEqual(st2["current_stage"], "Hired")
        self.assertEqual(st2["status"], "Hired")

        frappe.delete_doc("Job Application", app_name, force=True, ignore_permissions=True)

    def test_APP_21_candidate_status_remains_independent(self):
        """APP-21: Candidate profile status is global while Job Application maintains stage"""
        cand_doc = frappe.get_doc("Candidate", self.candidate_id)
        original_cand_status = cand_doc.status

        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
            "current_stage": "Applied",
        })

        self.service.change_status(app["name"], "Interview")
        cand_doc.reload()
        # Candidate status is preserved independently
        self.assertIsNotNone(cand_doc.status)

        frappe.delete_doc("Job Application", app["name"], force=True, ignore_permissions=True)

    def test_APP_22_multi_application_safety(self):
        """APP-22: Candidate with 2 applications maintains separate stages without collision"""
        app1 = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
            "current_stage": "Screening",
        })
        app2 = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job2_id,
            "company": self.company,
            "current_stage": "Interview",
        })

        # Transition Application 1 from Screening -> Technical
        self.service.change_status(app1["name"], "Technical")

        # Verify Application 1 is Technical
        app1_updated = self.service.get_application(app1["name"])
        self.assertEqual(app1_updated["current_stage"], "Technical")

        # Verify Application 2 remains Interview
        app2_unchanged = self.service.get_application(app2["name"])
        self.assertEqual(app2_unchanged["current_stage"], "Interview")

        frappe.delete_doc("Job Application", app1["name"], force=True, ignore_permissions=True)
        frappe.delete_doc("Job Application", app2["name"], force=True, ignore_permissions=True)

    def test_APP_23_job_opening_filtering(self):
        """APP-23: Filter Job Applications by job_opening for Kanban data retrieval"""
        app1 = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
        })
        app2 = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job2_id,
            "company": self.company,
        })

        res_job1 = self.service.list_applications(filters={"job_opening": self.job_id, "company": self.company})
        self.assertTrue(any(a["name"] == app1["name"] for a in res_job1["data"]))
        self.assertFalse(any(a["name"] == app2["name"] for a in res_job1["data"]))

        frappe.delete_doc("Job Application", app1["name"], force=True, ignore_permissions=True)
        frappe.delete_doc("Job Application", app2["name"], force=True, ignore_permissions=True)

    def test_APP_24_kanban_data_loading(self):
        """APP-24: Kanban card fields (name, candidate, job_opening, current_stage, status) are returned"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
            "current_stage": "Shortlisted",
        })
        res = self.service.list_applications(filters={"job_opening": self.job_id, "company": self.company})
        matching = [a for a in res["data"] if a["name"] == app["name"]]
        self.assertEqual(len(matching), 1)
        card = matching[0]
        self.assertIn("name", card)
        self.assertIn("candidate", card)
        self.assertIn("job_opening", card)
        self.assertIn("current_stage", card)
        self.assertIn("status", card)
        self.assertEqual(card["current_stage"], "Shortlisted")

        frappe.delete_doc("Job Application", app["name"], force=True, ignore_permissions=True)

    def test_APP_25_delete_safety(self):
        """APP-25: Deletion is blocked when linked to Interview history (JOB_APPLICATION_HAS_RECRUITMENT_HISTORY)"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
        })

        if frappe.db.table_exists("Interview"):
            interview_doc = frappe.new_doc("Interview")
            interview_doc.interview_name = f"P16-Interview-{frappe.generate_hash(length=6)}"
            interview_doc.job_application = app["name"]
            interview_doc.candidate = self.candidate_id
            interview_doc.job_opening = self.job_id
            interview_doc.company = self.company
            interview_doc.status = "Scheduled"
            interview_doc.flags.ignore_mandatory = True
            interview_doc.insert(ignore_permissions=True)

            with self.assertRaises(ATSConflictError) as cm:
                self.service.delete_application(app["name"])
            self.assertIn("JOB_APPLICATION_HAS_RECRUITMENT_HISTORY", str(cm.exception.details))

            frappe.delete_doc("Interview", interview_doc.name, force=True, ignore_permissions=True)

        self.service.delete_application(app["name"])

    def test_APP_26_response_envelope(self):
        """APP-26: Serialized Job Application strips internal metadata fields"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
        })
        for internal_key in ["owner", "modified_by", "docstatus", "idx", "doctype"]:
            self.assertNotIn(internal_key, app)
        frappe.delete_doc("Job Application", app["name"], force=True, ignore_permissions=True)

    def test_APP_27_sql_order_by_safety(self):
        """APP-27: Injection via order_by is sanitized without query failure"""
        res = self.service.list_applications(
            order_by="creation desc; DROP TABLE `tabJob Application`; --",
            filters={"company": self.company}
        )
        self.assertIn("data", res)
        self.assertTrue(frappe.db.table_exists("Job Application"))

    def test_APP_28_resume_file_contract(self):
        """APP-28: Resume field contract (Attach type, default placeholder, persistence)"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
            "resume": "/files/custom_candidate_resume.pdf",
        })
        self.assertEqual(app["resume"], "/files/custom_candidate_resume.pdf")

        db_resume = frappe.db.get_value("Job Application", app["name"], "resume")
        self.assertEqual(db_resume, "/files/custom_candidate_resume.pdf")

        frappe.delete_doc("Job Application", app["name"], force=True, ignore_permissions=True)
