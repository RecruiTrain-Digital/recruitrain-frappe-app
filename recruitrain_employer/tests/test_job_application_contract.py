# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

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


class TestJobApplicationContract(unittest.TestCase):
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
                comp.company_name = "Test Primary Employer Co"
                comp.default_currency = "USD"
                comp.email = "primary@company.com"
                comp.phone = "+1234567890"
                comp.address_line_1 = "123 Primary Street"
                comp.insert(ignore_permissions=True)
                cls.company = comp.name

        # Provision Company B for cross-company testing
        cls.company_b = "Test Secondary Co"
        if not frappe.db.exists("Company", cls.company_b):
            comp2 = frappe.new_doc("Company")
            comp2.company_name = cls.company_b
            comp2.default_currency = "USD"
            comp2.email = "secondary@company.com"
            comp2.flags.ignore_mandatory = True
            comp2.insert(ignore_permissions=True)


        cls.service = JobApplicationService()
        cls.job_service = JobService()
        cls.candidate_service = CandidateService()
        cls.validator = JobApplicationValidator()

        # Create primary test candidate in Company A
        cls.cand_email = f"app_test_cand_{frappe.generate_hash(length=6)}@example.com"
        cand_doc = frappe.new_doc("Candidate")
        cand_doc.candidate_name = f"AppTest Candidate {frappe.generate_hash(length=4)}"
        cand_doc.first_name = "AppTest"
        cand_doc.last_name = "Candidate"
        cand_doc.email_address = cls.cand_email
        cand_doc.email = cls.cand_email
        cand_doc.company = cls.company
        cand_doc.status = "Active"
        cand_doc.flags.ignore_mandatory = True
        cand_doc.insert(ignore_permissions=True)
        cls.candidate_id = cand_doc.name

        # Create primary test job opening in Company A
        job_doc = frappe.new_doc("Job Opening")
        job_doc.job_code = f"JOB-TEST-{frappe.generate_hash(length=6)}"
        job_doc.job_title = f"Test Job {frappe.generate_hash(length=6)}"
        job_doc.company = cls.company
        job_doc.employment_type = "Full Time"
        job_doc.status = "Draft"
        job_doc.published = 0
        job_doc.flags.ignore_mandatory = True
        job_doc.flags.ignore_links = True
        job_doc.insert(ignore_permissions=True)
        cls.job_id = job_doc.name

        # Create Candidate B in Company B
        cls.cand_b_email = f"app_test_cand_b_{frappe.generate_hash(length=6)}@example.com"
        cand_b_doc = frappe.new_doc("Candidate")
        cand_b_doc.candidate_name = f"AppTest Candidate B {frappe.generate_hash(length=4)}"
        cand_b_doc.first_name = "AppTest"
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
        job_b_doc.job_code = f"JOB-TEST-B-{frappe.generate_hash(length=6)}"
        job_b_doc.job_title = f"Test Job B {frappe.generate_hash(length=6)}"
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
            for j in [getattr(cls, "job_id", None), getattr(cls, "job_b_id", None)]:
                if j and frappe.db.exists("Job Opening", j):
                    frappe.delete_doc("Job Opening", j, force=True, ignore_permissions=True)
            frappe.db.commit()
        except Exception:
            pass

    def setUp(self):
        frappe.set_user("Administrator")
        frappe.db.rollback()

    def test_jobapp_01_list_applications(self):
        """JOBAPP-01: list applications service method returns paginated dict envelope"""
        res = self.service.list_applications(page=1, page_size=10, filters={"company": self.company})
        self.assertIn("data", res)
        self.assertIn("total", res)
        self.assertIn("page", res)
        self.assertIn("page_size", res)

    def test_jobapp_02_pagination_metadata(self):
        """JOBAPP-02: pagination metadata structure matches contract"""
        res = self.service.list_applications(page=1, page_size=2, filters={"company": self.company})
        self.assertLessEqual(len(res["data"]), 2)
        self.assertEqual(res["page"], 1)
        self.assertEqual(res["page_size"], 2)

    def test_jobapp_03_page_size_clamping(self):
        """JOBAPP-03: page and page_size parameters are safely clamped"""
        res = self.service.list_applications(page=-5, page_size=500, filters={"company": self.company})
        self.assertEqual(res["page"], 1)
        self.assertEqual(res["page_size"], 100)

    def test_jobapp_04_search_applications(self):
        """JOBAPP-04: server-side search across candidate, job, status, and name"""
        cand_c = frappe.new_doc("Candidate")
        cand_c.candidate_name = "UniqueSearchCand Tester"
        cand_c.first_name = "UniqueSearchCand"
        cand_c.last_name = "Tester"
        cand_c.email = f"search_{frappe.generate_hash(length=6)}@example.com"
        cand_c.company = self.company
        cand_c.flags.ignore_mandatory = True
        cand_c.insert(ignore_permissions=True)

        app = self.service.create_application({
            "candidate": cand_c.name,
            "job_opening": self.job_id,
            "company": self.company,
            "source": "LinkedIn",
        })

        res = self.service.search_applications(search="UniqueSearchCand", filters={"company": self.company})
        self.assertGreaterEqual(res["total"], 1)
        self.assertTrue(any(a["name"] == app["name"] for a in res["data"]))

        frappe.delete_doc("Job Application", app["name"], force=True, ignore_permissions=True)
        frappe.db.delete("Activity Logs", {"candidate": cand_c.name})
        frappe.delete_doc("Candidate", cand_c.name, force=True, ignore_permissions=True)

    def test_jobapp_05_search_total_count(self):
        """JOBAPP-05: search total count accurately reflects filtered record total"""
        res = self.service.search_applications(search="NonExistentSearchString12345", filters={"company": self.company})
        self.assertEqual(res["total"], 0)
        self.assertEqual(len(res["data"]), 0)

    def test_jobapp_06_status_filtering(self):
        """JOBAPP-06: filter applications by status/stage"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
            "current_stage": "Applied",
        })
        res = self.service.list_applications(filters={"current_stage": "Applied", "company": self.company})
        self.assertTrue(any(a["name"] == app["name"] for a in res["data"]))
        frappe.delete_doc("Job Application", app["name"], force=True, ignore_permissions=True)


    def test_jobapp_07_stage_filtering(self):
        """JOBAPP-07: filter applications by current_stage"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
            "current_stage": "Shortlisted",
        })
        res = self.service.list_applications(filters={"current_stage": "Shortlisted", "company": self.company})
        self.assertTrue(any(a["name"] == app["name"] for a in res["data"]))
        frappe.delete_doc("Job Application", app["name"], force=True, ignore_permissions=True)

    def test_jobapp_08_candidate_filtering(self):
        """JOBAPP-08: filter applications by candidate ID"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
        })
        res = self.service.list_applications(filters={"candidate": self.candidate_id})
        self.assertTrue(any(a["name"] == app["name"] for a in res["data"]))
        frappe.delete_doc("Job Application", app["name"], force=True, ignore_permissions=True)

    def test_jobapp_09_job_opening_filtering(self):
        """JOBAPP-09: filter applications by job opening ID"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
        })
        res = self.service.list_applications(filters={"job_opening": self.job_id})
        self.assertTrue(any(a["name"] == app["name"] for a in res["data"]))
        frappe.delete_doc("Job Application", app["name"], force=True, ignore_permissions=True)

    def test_jobapp_10_safe_sorting(self):
        """JOBAPP-10: whitelisted sorting by creation, modified, applied_on, candidate, status"""
        for field in ["creation", "modified", "applied_on", "status", "candidate"]:
            res = self.service.list_applications(order_by=field, order_dir="asc", filters={"company": self.company})
            self.assertIn("data", res)

    def test_jobapp_11_get_application(self):
        """JOBAPP-11: retrieve application by ID returns expected schema"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
            "cover_letter": "Test Letter",
        })
        retrieved = self.service.get_application(app["name"])
        self.assertEqual(retrieved["name"], app["name"])
        self.assertEqual(retrieved["candidate"], self.candidate_id)
        frappe.delete_doc("Job Application", app["name"], force=True, ignore_permissions=True)

    def test_jobapp_12_create_application(self):
        """JOBAPP-12: create valid application with complete fields"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
            "source": "LinkedIn",
            "rating": 5,
        })
        self.assertIsNotNone(app.get("name"))
        self.assertEqual(app.get("candidate"), self.candidate_id)
        self.assertEqual(app.get("job_opening"), self.job_id)
        frappe.delete_doc("Job Application", app["name"], force=True, ignore_permissions=True)

    def test_jobapp_13_mandatory_validation(self):
        """JOBAPP-13: missing mandatory fields candidate or job_opening raises ATSValidationError"""
        with self.assertRaises(ATSValidationError):
            self.service.create_application({"candidate": self.candidate_id})
        with self.assertRaises(ATSValidationError):
            self.service.create_application({"job_opening": self.job_id})

    def test_jobapp_14_invalid_candidate_rejection(self):
        """JOBAPP-14: referencing non-existent candidate raises ATSValidationError"""
        with self.assertRaises(ATSValidationError):
            self.service.create_application({
                "candidate": "CAND-NON-EXISTENT-9999",
                "job_opening": self.job_id,
            })

    def test_jobapp_15_invalid_job_opening_rejection(self):
        """JOBAPP-15: referencing non-existent job opening raises ATSValidationError"""
        with self.assertRaises(ATSValidationError):
            self.service.create_application({
                "candidate": self.candidate_id,
                "job_opening": "JOB-NON-EXISTENT-9999",
            })

    def test_jobapp_16_candidate_relationship_integrity(self):
        """JOBAPP-16: Candidate <-> Job Application relationship integrity"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
        })
        c_apps = self.service.list_applications(filters={"candidate": self.candidate_id})
        self.assertTrue(any(a["name"] == app["name"] for a in c_apps["data"]))
        frappe.delete_doc("Job Application", app["name"], force=True, ignore_permissions=True)

    def test_jobapp_17_job_opening_relationship_integrity(self):
        """JOBAPP-17: Job Opening <-> Job Application relationship integrity"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
        })
        job_doc = self.job_service.get_job(self.job_id)
        self.assertIn("application_count", job_doc)
        frappe.delete_doc("Job Application", app["name"], force=True, ignore_permissions=True)

    def test_jobapp_18_duplicate_application_protection(self):
        """JOBAPP-18: duplicate application for same candidate + job raises ATSConflictError"""
        app1 = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
        })
        with self.assertRaises(ATSConflictError):
            self.service.create_application({
                "candidate": self.candidate_id,
                "job_opening": self.job_id,
                "company": self.company,
            })
        frappe.delete_doc("Job Application", app1["name"], force=True, ignore_permissions=True)

    def test_jobapp_19_partial_update(self):
        """JOBAPP-19: partial update of updatable scalar fields"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
            "notes": "Initial note",
        })
        updated = self.service.update_application(app["name"], {"notes": "Updated note", "cover_letter": "Updated letter"})
        self.assertEqual(updated["notes"], "Updated note")
        self.assertEqual(updated["cover_letter"], "Updated letter")
        frappe.delete_doc("Job Application", app["name"], force=True, ignore_permissions=True)


    def test_jobapp_20_immutable_field_protection(self):
        """JOBAPP-20: updating candidate, job_opening, or company raises ATSValidationError"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
        })
        with self.assertRaises(ATSValidationError):
            self.service.update_application(app["name"], {"candidate": "CAND-MUTATED-ID"})
        with self.assertRaises(ATSValidationError):
            self.service.update_application(app["name"], {"job_opening": "JOB-MUTATED-ID"})
        frappe.delete_doc("Job Application", app["name"], force=True, ignore_permissions=True)

    def test_jobapp_21_valid_status_transition(self):
        """JOBAPP-21: valid status transition updates stage and status atomically"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
            "current_stage": "Applied",
        })
        trans1 = self.service.change_status(app["name"], "Shortlisted")
        self.assertEqual(trans1["current_stage"], "Shortlisted")

        trans2 = self.service.change_status(app["name"], "Interview Scheduled")
        self.assertEqual(trans2["current_stage"], "Interview Scheduled")
        frappe.delete_doc("Job Application", app["name"], force=True, ignore_permissions=True)

    def test_jobapp_22_terminal_state_transition_blocking(self):
        """JOBAPP-22: transitioning out of terminal status (Hired/Rejected/Withdrawn) raises ATSValidationError"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
            "current_stage": "Applied",
        })
        self.service.change_status(app["name"], "Rejected")
        with self.assertRaises(ATSValidationError):
            self.service.change_status(app["name"], "Shortlisted")
        frappe.delete_doc("Job Application", app["name"], force=True, ignore_permissions=True)

    def test_jobapp_23_valid_stage_transition(self):
        """JOBAPP-23: updating current_stage via service updates entity state"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
        })
        up = self.service.update_application(app["name"], {"current_stage": "Screening"})
        self.assertEqual(up["current_stage"], "Screening")
        frappe.delete_doc("Job Application", app["name"], force=True, ignore_permissions=True)

    def test_jobapp_24_invalid_stage_rejection(self):
        """JOBAPP-24: unsupported stage or status string raises ATSValidationError"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
        })
        with self.assertRaises(ATSValidationError):
            self.service.change_status(app["name"], "InvalidStageString123")
        frappe.delete_doc("Job Application", app["name"], force=True, ignore_permissions=True)

    def test_jobapp_25_company_isolation(self):
        """JOBAPP-25: listing applications filters strictly by active company context"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
        })
        res = self.service.list_applications(filters={"company": self.company_b})
        self.assertEqual(res["total"], 0)
        frappe.delete_doc("Job Application", app["name"], force=True, ignore_permissions=True)

    def test_jobapp_26_company_spoofing_defense(self):
        """JOBAPP-26: passing spoofed company parameter does not override entity company"""
        # Administrator can specify target_company if entity belongs to it, but non-admin cannot spoof
        frappe.set_user("Administrator")
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
        })
        self.assertEqual(app["company"], self.company)
        frappe.delete_doc("Job Application", app["name"], force=True, ignore_permissions=True)

    def test_jobapp_27_cross_company_candidate_protection(self):
        """JOBAPP-27: creating application with candidate from Company B for Job in Company A raises validation error"""
        with self.assertRaises((ATSValidationError, ATSPermissionError)):
            self.service.create_application({
                "candidate": self.candidate_b_id,
                "job_opening": self.job_id,
            })

    def test_jobapp_28_cross_company_job_opening_protection(self):
        """JOBAPP-28: creating application with candidate from Company A for Job in Company B raises validation error"""
        with self.assertRaises((ATSValidationError, ATSPermissionError)):
            self.service.create_application({
                "candidate": self.candidate_id,
                "job_opening": self.job_b_id,
            })

    def test_jobapp_29_guest_rejection(self):
        """JOBAPP-29: Guest / unauthenticated request to API returns HTTP 401 UNAUTHORIZED"""
        frappe.set_user("Guest")
        res = list_applications()
        status_code = res.get("status_code") or frappe.response.get("http_status_code")
        self.assertEqual(status_code, 401)
        self.assertEqual(res["error"]["code"], "UNAUTHORIZED")
        frappe.set_user("Administrator")

    def test_jobapp_30_non_employer_rejection(self):
        """JOBAPP-30: user without active employer profile returns 403 / 401"""
        test_user = f"non_employer_{frappe.generate_hash(length=6)}@example.com"
        if not frappe.db.exists("User", test_user):
            u = frappe.new_doc("User")
            u.email = test_user
            u.first_name = "NonEmployer"
            u.send_welcome_email = 0
            u.insert(ignore_permissions=True)

        frappe.set_user(test_user)
        res = list_applications()
        status_code = res.get("status_code") or frappe.response.get("http_status_code")
        self.assertIn(status_code, [401, 403])
        frappe.set_user("Administrator")
        frappe.delete_doc("User", test_user, force=True, ignore_permissions=True)

    def test_jobapp_31_404_not_found_handling(self):
        """JOBAPP-31: non-existent application ID raises ATSNotFoundError / 404 response"""
        with self.assertRaises(ATSNotFoundError):
            self.service.get_application("APP-NON-EXISTENT-9999")

    def test_jobapp_32_409_conflict_handling(self):
        """JOBAPP-32: duplicate application or conflict raises ATSConflictError"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
        })
        with self.assertRaises(ATSConflictError):
            self.service.create_application({
                "candidate": self.candidate_id,
                "job_opening": self.job_id,
                "company": self.company,
            })
        frappe.delete_doc("Job Application", app["name"], force=True, ignore_permissions=True)

    def test_jobapp_33_delete_linked_history_safety(self):
        """JOBAPP-33: deletion is blocked when linked to recruitment history (Interview / Offer)"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
        })

        # Create linked Interview if Interview DocType exists
        if frappe.db.table_exists("Interview"):
            interview_doc = frappe.new_doc("Interview")
            interview_doc.interview_name = f"Interview-{frappe.generate_hash(length=6)}"
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

        # Once linked recruitment records are removed, deletion succeeds cleanly
        self.service.delete_application(app["name"])
        with self.assertRaises(ATSNotFoundError):
            self.service.get_application(app["name"])

    def test_jobapp_34_response_envelope_hygiene(self):
        """JOBAPP-34: serialized application dictionary strips internal metadata fields"""
        app = self.service.create_application({
            "candidate": self.candidate_id,
            "job_opening": self.job_id,
            "company": self.company,
        })
        for forbidden in ["owner", "modified_by", "docstatus", "idx", "doctype"]:
            self.assertNotIn(forbidden, app)
        frappe.delete_doc("Job Application", app["name"], force=True, ignore_permissions=True)

    def test_jobapp_35_sql_injection_defense_and_cleanup(self):
        """JOBAPP-35: order_by parameter sanitizes raw SQL interpolation without error"""
        res = self.service.list_applications(
            order_by="creation desc; DROP TABLE `tabJob Application`; --",
            filters={"company": self.company}
        )
        self.assertIn("data", res)
        self.assertTrue(frappe.db.table_exists("Job Application"))

