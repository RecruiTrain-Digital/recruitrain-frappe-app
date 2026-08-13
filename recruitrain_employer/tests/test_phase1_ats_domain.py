# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

import unittest
import frappe

from recruitrain_employer.services.candidate_service import CandidateService
from recruitrain_employer.services.job_application_service import JobApplicationService
from recruitrain_employer.services.interview_service import InterviewService
from recruitrain_employer.services.offer_service import OfferService

class TestPhase1ATSDomain(unittest.TestCase):
    """Test suite verifying Phase 1 ATS Domain Refactoring."""

    def setUp(self):
        frappe.set_user("Administrator")
        self.candidate_service = CandidateService()
        self.application_service = JobApplicationService()
        self.interview_service = InterviewService()
        self.offer_service = OfferService()

    def test_domain_lifecycle(self):
        """Test full domain lifecycle: Candidate -> Job Application -> Interview -> Offer -> Activity Log."""
        test_email = f"ats_test_{frappe.generate_hash(length=6)}@example.com"

        # 1. Create Candidate (Global Talent Profile)
        cand_data = {
            "first_name": "Domain",
            "last_name": "Tester",
            "email": test_email,
            "mobile_no": "+1234567890",
            "city": "Mumbai",
            "country": "India"
        }
        cand = self.candidate_service.create_candidate(cand_data)
        self.assertIsNotNone(cand.get("name"))
        cand_id = cand["name"]

        # Verify activity log
        logs = frappe.get_all("Activity Logs", filters={"candidate": cand_id, "activity_type": "Candidate Created"})
        self.assertGreater(len(logs), 0)

        # 2. Get or Create Job Opening for linking
        openings = frappe.get_all("Job Opening", limit=1, fields=["name", "company"])
        if not openings:
            job_doc = frappe.new_doc("Job Opening")
            job_doc.job_title = "Test Software Engineer"
            job_doc.company = cand.get("company") or "Test Company"
            job_doc.status = "Open"
            job_doc.insert(ignore_permissions=True)
            job_id = job_doc.name
            company = job_doc.company
        else:
            job_id = openings[0].name
            company = openings[0].company

        # 3. Create Job Application (Recruitment Lifecycle Nexus)
        app_data = {
            "candidate": cand_id,
            "job_opening": job_id,
            "company": company,
            "current_stage": "Applied"
        }
        app = self.application_service.create_application(app_data)
        app_id = app["name"]
        self.assertIsNotNone(app_id)

        # 4. Schedule Interview (linked to Job Application)
        int_data = {
            "job_application": app_id,
            "interview_type": "Technical",
            "scheduled_on": frappe.utils.now_datetime(),
            "interviewer": getattr(frappe.session, "user", "Administrator")
        }
        interview = self.interview_service.create_interview(int_data)
        interview_id = interview["name"]
        self.assertEqual(interview["job_application"], app_id)
        self.assertEqual(interview["candidate"], cand_id)

        # 5. Advance Job Application Stage -> Interviewing & verify Legacy Candidate Sync
        self.application_service.change_status(app_id, "Interview")
        updated_cand = frappe.get_doc("Candidate", cand_id)
        self.assertEqual(updated_cand.status, "Interviewing")

        # 6. Create Offer (linked to Job Application)
        offer_data = {
            "job_application": app_id,
            "offered_salary": 120000,
            "joining_date": frappe.utils.add_days(frappe.utils.today(), 30),
            "offer_status": "Draft"
        }
        offer = self.offer_service.create_offer(offer_data)
        offer_id = offer["name"]
        self.assertEqual(offer["job_application"], app_id)
        self.assertEqual(offer["candidate"], cand_id)

        # 7. Update Offer Status -> Sent & check logs
        self.offer_service.change_status(offer_id, "Sent")
        offer_logs = frappe.get_all("Activity Logs", filters={"job_application": app_id, "activity_type": "Offer Sent"})
        self.assertGreater(len(offer_logs), 0)

        frappe.db.rollback()
