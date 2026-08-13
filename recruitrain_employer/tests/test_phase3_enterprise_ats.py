# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from recruitrain_employer.services.pipeline_service import PipelineService
from recruitrain_employer.services.note_service import CandidateNoteService
from recruitrain_employer.services.talent_pool_service import TalentPoolService
from recruitrain_employer.services.candidate_service import CandidateService
from recruitrain_employer.services.job_application_service import JobApplicationService
from recruitrain_employer.services.interview_service import InterviewService
from recruitrain_employer.services.offer_service import OfferService
from recruitrain_employer.services.dashboard_service import DashboardService
from recruitrain_employer.api.bulk_operations import bulk_change_stage, bulk_archive_candidates
from recruitrain_employer.tasks import send_daily_reminders

class TestPhase3EnterpriseATS(FrappeTestCase):
    """Integration test suite for Phase 3 Enterprise ATS Platform capabilities."""

    def setUp(self):
        frappe.set_user("Administrator")
        self.company = "Test Enterprise Corp"
        if not frappe.db.exists("Company", self.company):
            comp = frappe.new_doc("Company")
            comp.company_name = self.company
            comp.insert(ignore_permissions=True)

    def test_module1_recruitment_pipeline_engine(self):
        service = PipelineService()
        default_pipe = service.get_or_create_default_pipeline(self.company)
        self.assertIsNotNone(default_pipe.get("name"))
        self.assertTrue(len(default_pipe.get("stages", [])) >= 5)

        custom_pipe = service.create_pipeline({
            "pipeline_name": "Executive Hiring Pipeline",
            "company": self.company,
            "stages": [
                {"stage_name": "Applied", "stage_type": "Applied", "stage_order": 1},
                {"stage_name": "VP Review", "stage_type": "Screening", "stage_order": 2},
                {"stage_name": "Executive Board Round", "stage_type": "Interview", "stage_order": 3},
                {"stage_name": "Executive Offer", "stage_type": "Offer", "stage_order": 4},
                {"stage_name": "Hired", "stage_type": "Hired", "stage_order": 5, "is_terminal": 1},
            ]
        })
        self.assertEqual(custom_pipe["pipeline_name"], "Executive Hiring Pipeline")

    def test_module3_candidate_notes(self):
        cand_svc = CandidateService()
        cand = cand_svc.create_candidate({
            "first_name": "Enterprise",
            "last_name": "Applicant",
            "email": "enterprise.applicant@test.com",
            "company": self.company,
        })

        note_svc = CandidateNoteService()
        note = note_svc.add_note({
            "candidate": cand["id"],
            "company": self.company,
            "content": "Strong technical leadership background. @recruiter_john",
            "is_pinned": 1,
            "mentions": ["recruiter_john@test.com"],
        })
        self.assertEqual(note["is_pinned"], 1)

        notes = note_svc.list_notes(cand["id"])
        self.assertTrue(len(notes) >= 1)

    def test_module7_talent_pools(self):
        pool_svc = TalentPoolService()
        pool = pool_svc.create_pool({
            "pool_name": "Silver Medalists 2026",
            "company": self.company,
            "category": "Silver Medalists",
            "description": "High potential candidates who reached final offer round.",
        })
        self.assertEqual(pool["pool_name"], "Silver Medalists 2026")

        cand_svc = CandidateService()
        cand = cand_svc.create_candidate({
            "first_name": "Silver",
            "last_name": "Medalist",
            "email": "silver.medalist@test.com",
            "company": self.company,
        })

        updated_pool = pool_svc.add_candidate_to_pool(pool["name"], cand["id"], notes="Runner up for Senior Architect role.")
        self.assertEqual(len(updated_pool["members"]), 1)

    def test_module8_bulk_operations(self):
        cand_svc = CandidateService()
        cand1 = cand_svc.create_candidate({
            "first_name": "Bulk",
            "last_name": "One",
            "email": "bulk.one@test.com",
            "company": self.company,
        })
        cand2 = cand_svc.create_candidate({
            "first_name": "Bulk",
            "last_name": "Two",
            "email": "bulk.two@test.com",
            "company": self.company,
        })

        frappe.form_dict = {"candidate_ids": [cand1["id"], cand2["id"]]}
        res = bulk_archive_candidates()
        self.assertTrue(res.get("success"))
        self.assertEqual(res["data"]["archived_count"], 2)

    def test_module10_dashboard_analytics(self):
        dash_svc = DashboardService()
        overview = dash_svc.get_overview(self.company)
        self.assertIn("open_jobs", overview)
        self.assertIn("total_applications", overview)
        self.assertIn("todays_interviews", overview)

    def test_module13_background_jobs(self):
        # Verify background scheduler tasks run without error
        send_daily_reminders()
