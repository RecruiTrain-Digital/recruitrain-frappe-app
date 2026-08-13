# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

import unittest
import frappe

from recruitrain_employer.services.candidate_service import CandidateService
from recruitrain_employer.services.job_application_service import JobApplicationService
from recruitrain_employer.services.interview_service import InterviewService
from recruitrain_employer.services.offer_service import OfferService
from recruitrain_employer.utils.exceptions import (
    ATSValidationError,
    ATSPermissionError,
    ATSConflictError,
)
from recruitrain_employer.utils.response import success_response, error_response, paginated_response

class TestPhase15ProductionHardening(unittest.TestCase):
    """Production Hardening Integration Test Suite covering Workflows 1-12."""

    def setUp(self):
        frappe.set_user("Administrator")
        self.candidate_service = CandidateService()
        self.application_service = JobApplicationService()
        self.interview_service = InterviewService()
        self.offer_service = OfferService()

    def test_workflow_1_candidate_lifecycle(self):
        """Workflow 1: Create Candidate -> Application -> Stage Movement -> Archive."""
        email = f"wf1_{frappe.generate_hash(length=6)}@example.com"
        cand = self.candidate_service.create_candidate({
            "first_name": "Workflow1",
            "last_name": "Tester",
            "email": email,
            "mobile_no": "+1111111111"
        })
        cand_id = cand["name"]
        company = cand["company"]

        # Create Job Opening
        job = frappe.new_doc("Job Opening")
        job.job_title = "WF1 Engineer"
        job.company = company
        job.status = "Open"
        job.insert(ignore_permissions=True)

        # Create Application
        app = self.application_service.create_application({
            "candidate": cand_id,
            "job_opening": job.name,
            "company": company,
            "current_stage": "Applied"
        })
        app_id = app["name"]

        # Move stage
        self.application_service.change_status(app_id, "Shortlisted")
        cand_doc = frappe.get_doc("Candidate", cand_id)
        self.assertEqual(cand_doc.status, "In Review")

        # Archive Candidate
        self.candidate_service.update_candidate(cand_id, {"status": "Archived"})
        cand_doc.reload()
        self.assertEqual(cand_doc.status, "Archived")

        frappe.db.rollback()

    def test_workflow_2_multi_application_independence(self):
        """Workflow 2: Candidate applies to multiple jobs independently."""
        email = f"wf2_{frappe.generate_hash(length=6)}@example.com"
        cand = self.candidate_service.create_candidate({
            "first_name": "MultiApp",
            "last_name": "Candidate",
            "email": email,
            "mobile_no": "+2222222222"
        })
        cand_id = cand["name"]
        company = cand["company"]

        job_a = frappe.new_doc("Job Opening")
        job_a.job_title = "Job A"
        job_a.company = company
        job_a.status = "Open"
        job_a.insert(ignore_permissions=True)

        job_b = frappe.new_doc("Job Opening")
        job_b.job_title = "Job B"
        job_b.company = company
        job_b.status = "Open"
        job_b.insert(ignore_permissions=True)

        app_a = self.application_service.create_application({
            "candidate": cand_id,
            "job_opening": job_a.name,
            "company": company,
            "expected_salary": 100000,
        })

        app_b = self.application_service.create_application({
            "candidate": cand_id,
            "job_opening": job_b.name,
            "company": company,
            "expected_salary": 150000,
        })

        self.assertNotEqual(app_a["name"], app_b["name"])
        self.assertEqual(app_a["expected_salary"], 100000)
        self.assertEqual(app_b["expected_salary"], 150000)

        # Move App A stage to Shortlisted
        self.application_service.change_status(app_a["name"], "Shortlisted")
        app_b_doc = frappe.get_doc("Job Application", app_b["name"])
        self.assertEqual(app_b_doc.current_stage, "Applied")

        frappe.db.rollback()

    def test_workflow_3_interview_sync(self):
        """Workflow 3: Interview scheduling and binding to Job Application."""
        email = f"wf3_{frappe.generate_hash(length=6)}@example.com"
        cand = self.candidate_service.create_candidate({"first_name": "Int", "last_name": "Tester", "email": email})
        job = frappe.new_doc("Job Opening")
        job.job_title = "Int Job"
        job.company = cand["company"]
        job.insert(ignore_permissions=True)

        app = self.application_service.create_application({"candidate": cand["name"], "job_opening": job.name, "company": cand["company"]})

        interview = self.interview_service.create_interview({
            "job_application": app["name"],
            "interview_type": "HR",
            "scheduled_on": frappe.utils.now_datetime(),
            "interviewer": "Administrator"
        })
        self.assertEqual(interview["job_application"], app["name"])
        self.assertEqual(interview["candidate"], cand["name"])

        frappe.db.rollback()

    def test_workflow_4_offer_fsm(self):
        """Workflow 4: Offer state machine transitions and invalid transition rejection."""
        email = f"wf4_{frappe.generate_hash(length=6)}@example.com"
        cand = self.candidate_service.create_candidate({"first_name": "Offer", "last_name": "Tester", "email": email})
        job = frappe.new_doc("Job Opening")
        job.job_title = "Offer Job"
        job.company = cand["company"]
        job.insert(ignore_permissions=True)

        app = self.application_service.create_application({"candidate": cand["name"], "job_opening": job.name, "company": cand["company"]})

        offer = self.offer_service.create_offer({
            "job_application": app["name"],
            "offered_salary": 120000,
            "offer_status": "Draft"
        })

        # Valid transition: Draft -> Pending Approval -> Approved -> Sent -> Accepted
        self.offer_service.change_status(offer["name"], "Pending Approval")
        self.offer_service.change_status(offer["name"], "Approved")
        self.offer_service.change_status(offer["name"], "Sent")
        self.offer_service.change_status(offer["name"], "Accepted")

        # Invalid transition from Accepted -> Sent must fail
        with self.assertRaises(ATSValidationError):
            self.offer_service.change_status(offer["name"], "Sent")

        frappe.db.rollback()

    def test_workflow_11_response_envelope_format(self):
        """Workflow 11: Consistent response structure check across all helpers."""
        s_res = success_response(data={"id": "1"}, message="OK")
        self.assertTrue(s_res["success"])
        self.assertIn("data", s_res)
        self.assertIn("message", s_res)
        self.assertIn("error", s_res)
        self.assertIn("meta", s_res)

        e_res = error_response(code="VALIDATION_ERROR", message="Bad Payload")
        self.assertFalse(e_res["success"])
        self.assertIn("data", e_res)
        self.assertIn("error", e_res)
        self.assertIn("meta", e_res)

        p_res = paginated_response(items=[{"id": "1"}], total=1)
        self.assertTrue(p_res["success"])
        self.assertIn("meta", p_res)

    def test_section_1_concurrent_update_locking(self):
        """Section 1: Optimistic locking & timestamp mismatch handling."""
        email = f"wf1_lock_{frappe.generate_hash(length=6)}@example.com"
        cand = self.candidate_service.create_candidate({
            "first_name": "Lock",
            "last_name": "Tester",
            "email": email,
        })
        cand_id = cand["name"]
        doc_a = frappe.get_doc("Candidate", cand_id)
        doc_b = frappe.get_doc("Candidate", cand_id)

        doc_a.first_name = "UpdateA"
        doc_a.save(ignore_permissions=True)

        doc_b.first_name = "UpdateB"
        with self.assertRaises(frappe.exceptions.TimestampMismatchError):
            doc_b.save(ignore_permissions=True)

        frappe.db.rollback()

    def test_section_2_archival_policy(self):
        """Section 2: Non-destructive archival workflow."""
        email = f"wf2_arc_{frappe.generate_hash(length=6)}@example.com"
        cand = self.candidate_service.create_candidate({
            "first_name": "Archive",
            "last_name": "Candidate",
            "email": email,
        })
        cand_id = cand["name"]
        self.candidate_service.update_candidate(cand_id, {"status": "Archived"})
        doc = frappe.get_doc("Candidate", cand_id)
        self.assertEqual(doc.status, "Archived")

        frappe.db.rollback()

