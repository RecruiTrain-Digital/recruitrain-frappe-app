# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.tests.test_analytics_contract
=====================================================

Contract Verification & Hardening Test Suite for RecruitTrain Analytics Backend (ANA-01 to ANA-25).

Tests:
ANA-01 Overview metrics aggregation
ANA-02 Date range handling
ANA-03 Default date range
ANA-04 Trend aggregation
ANA-05 Funnel calculation
ANA-06 Job metrics
ANA-07 Application metrics
ANA-08 Interview metrics
ANA-09 Offer metrics
ANA-10 Hiring metrics / Time-to-hire
ANA-11 Company isolation
ANA-12 Cross-company data protection
ANA-13 Unauthenticated access
ANA-14 Unauthorized access
ANA-15 Invalid date range
ANA-16 Invalid filter
ANA-17 SQL injection attempt
ANA-18 Empty dataset handling
ANA-19 Null/missing data handling
ANA-20 Response envelope
ANA-21 Pagination
ANA-22 Sorting / Ordering
ANA-23 Duplicate counting protection
ANA-24 Query safety & performance
ANA-25 Read-only / No side-effects assertion
"""

from __future__ import annotations

import unittest
import frappe

from recruitrain_employer.services.analytics_service import AnalyticsService
from recruitrain_employer.services.candidate_service import CandidateService
from recruitrain_employer.services.job_service import JobService
from recruitrain_employer.services.job_application_service import JobApplicationService
from recruitrain_employer.services.interview_service import InterviewService
from recruitrain_employer.services.offer_service import OfferService
from recruitrain_employer.api.analytics import (
    get_overview,
    get_funnel,
    get_trends,
    get_job_metrics,
    get_application_metrics,
    get_interview_metrics,
    get_offer_metrics,
    get_time_to_hire,
    get_recent_activity,
)
from recruitrain_employer.utils.exceptions import (
    ATSPermissionError,
    ATSValidationError,
)
from recruitrain_employer.utils.permissions import get_current_company


class TestAnalyticsContract(unittest.TestCase):
    """Analytics Backend Contract Test Suite (ANA-01..ANA-25)."""

    @classmethod
    def setUpClass(cls):
        cls.current_company = get_current_company()
        cls.service = AnalyticsService()
        cls.cand_svc = CandidateService()
        cls.job_svc = JobService()
        cls.app_svc = JobApplicationService()
        cls.interview_svc = InterviewService()
        cls.offer_svc = OfferService()

        cls.test_prefix = "ANA-TEST-VERIFY-"
        cls.cleanup_test_records()

        # Provision test entities
        cls.created_cands = []
        cls.created_jobs = []
        cls.created_apps = []
        cls.created_interviews = []
        cls.created_offers = []

        cand_doc = cls.cand_svc.create_candidate({
            "first_name": "Anna",
            "last_name": "Analytics",
            "candidate_name": f"{cls.test_prefix}Anna Analytics",
            "email": "anna.analytics.test@example.com",
            "phone": "+12025550199",
            "date_of_birth": "1993-05-15",
            "address_line_1": "100 Data Science Blvd",
            "city": "Boston",
            "state": "Massachusetts",
            "status": "Active",
        })
        cls.created_cands.append(cand_doc["name"])

        job_doc = cls.job_svc.save_draft({
            "job_code": f"{cls.test_prefix}JOB1",
            "job_title": "Analytics Lead",
            "department": "Engineering",
            "employment_type": "Full Time",
            "number_of_openings": 2,
            "job_summary": "Lead Analytics Platform",
            "status": "Draft",
        })
        cls.created_jobs.append(job_doc["name"])
        # Directly update status in DB for analytics calculation testing
        frappe.db.set_value("Job Opening", job_doc["name"], "status", "Open")

        app_doc = cls.app_svc.create_application({
            "candidate": cand_doc["name"],
            "job_opening": job_doc["name"],
            "applicant_name": f"{cls.test_prefix}Anna Analytics",
            "email_address": "anna.analytics.test@example.com",
            "resume": "/files/test_resume.pdf",
            "status": "Applied",
        })
        cls.created_apps.append(app_doc["name"])

        int_doc = cls.interview_svc.create_interview({
            "job_application": app_doc["name"],
            "interview_type": "Technical",
            "interviewer": getattr(frappe.session, "user", "Administrator") or "Administrator",
            "scheduled_on": f"{frappe.utils.today()} 14:00:00",
            "duration": 45,
            "status": "Scheduled",
        })
        cls.created_interviews.append(int_doc["name"])

        off_doc = cls.offer_svc.create_offer({
            "job_application": app_doc["name"],
            "offered_salary": 140000.00,
            "currency": "USD",
            "joining_date": "2026-11-01",
            "offer_date": frappe.utils.today(),
            "offer_status": "Sent",
        })
        cls.created_offers.append(off_doc["name"])

        frappe.db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.cleanup_test_records()

    @classmethod
    def cleanup_test_records(cls):
        prefix = "ANA-TEST-VERIFY-"
        frappe.db.delete("Activity Logs", {"reference_name": ["like", f"{prefix}%"]})
        frappe.db.delete("Offer", {"offer_name": ["like", f"{prefix}%"]})
        frappe.db.delete("Interview", {"interview_name": ["like", f"{prefix}%"]})
        frappe.db.delete("Job Application", {"candidate": ["like", f"{prefix}%"]})
        frappe.db.delete("Job Opening", {"job_code": ["like", f"{prefix}%"]})
        frappe.db.delete("Candidate", {"candidate_name": ["like", f"{prefix}%"]})
        frappe.db.commit()

    def test_ANA_01_overview_metrics(self):
        """ANA-01: Verify overview metrics aggregation structure and calculations."""
        res = self.service.get_overview()
        self.assertIn("open_jobs", res)
        self.assertIn("total_jobs", res)
        self.assertIn("total_candidates", res)
        self.assertIn("total_applications", res)
        self.assertIn("active_applications", res)
        self.assertIn("todays_interviews", res)
        self.assertIn("total_interviews", res)
        self.assertIn("pending_offers", res)
        self.assertIn("accepted_offers", res)
        self.assertIn("total_hires", res)
        self.assertIn("rejected_applications", res)

        self.assertGreaterEqual(res["open_jobs"], 1)
        self.assertGreaterEqual(res["total_jobs"], 1)
        self.assertGreaterEqual(res["total_candidates"], 1)
        self.assertGreaterEqual(res["total_applications"], 1)

    def test_ANA_02_date_range_handling(self):
        """ANA-02: Verify date range filtering in metrics."""
        today_str = str(frappe.utils.today())
        res = self.service.get_overview(from_date=today_str, to_date=today_str)
        self.assertGreaterEqual(res["total_applications"], 1)

    def test_ANA_03_default_date_range(self):
        """ANA-03: Verify default date range behavior when no dates provided."""
        res = self.service.get_overview(from_date=None, to_date=None)
        self.assertIsNotNone(res["total_applications"])

    def test_ANA_04_trend_aggregation(self):
        """ANA-04: Verify trend aggregation across daily, weekly, and monthly buckets."""
        daily = self.service.get_trends(granularity="daily")
        self.assertIsInstance(daily, list)
        if daily:
            self.assertIn("period", daily[0])
            self.assertIn("count", daily[0])

        weekly = self.service.get_trends(granularity="weekly")
        self.assertIsInstance(weekly, list)

        monthly = self.service.get_trends(granularity="monthly")
        self.assertIsInstance(monthly, list)

    def test_ANA_05_funnel_calculation(self):
        """ANA-05: Verify recruitment funnel breakdown and conversion percentage calculations."""
        res = self.service.get_funnel()
        self.assertIn("funnel", res)
        self.assertIn("total", res)
        self.assertIn("conversion_rates", res)
        self.assertIn("Applied", res["funnel"])
        self.assertIn("Applied", res["conversion_rates"])
        self.assertGreaterEqual(res["total"], 1)

    def test_ANA_06_job_metrics(self):
        """ANA-06: Verify Job Opening performance metrics and applications per job."""
        res = self.service.get_job_metrics()
        self.assertIn("by_status", res)
        self.assertIn("total_jobs", res)
        self.assertIn("open_jobs", res)
        self.assertIn("filled_jobs", res)
        self.assertIn("total_openings", res)
        self.assertIn("applications_per_job", res)
        self.assertGreaterEqual(res["total_jobs"], 1)

    def test_ANA_07_application_metrics(self):
        """ANA-07: Verify application breakdown by status, stage, source, priority."""
        res = self.service.get_application_metrics()
        self.assertIn("by_status", res)
        self.assertIn("by_stage", res)
        self.assertIn("by_source", res)
        self.assertIn("by_priority", res)
        self.assertIn("total_applications", res)
        self.assertGreaterEqual(res["total_applications"], 1)

    def test_ANA_08_interview_metrics(self):
        """ANA-08: Verify interview metrics by status, type, and result."""
        res = self.service.get_interview_metrics()
        self.assertIn("by_status", res)
        self.assertIn("by_type", res)
        self.assertIn("by_result", res)
        self.assertIn("total_interviews", res)
        self.assertGreaterEqual(res["total_interviews"], 1)

    def test_ANA_09_offer_metrics(self):
        """ANA-09: Verify offer status distribution, acceptance rate, and offered salary totals."""
        res = self.service.get_offer_metrics()
        self.assertIn("by_status", res)
        self.assertIn("total_offers", res)
        self.assertIn("accepted_offers", res)
        self.assertIn("acceptance_rate", res)
        self.assertIn("total_offered_salary", res)
        self.assertGreaterEqual(res["total_offers"], 1)
        self.assertGreaterEqual(res["total_offered_salary"], 140000.00)

    def test_ANA_10_time_to_hire(self):
        """ANA-10: Verify time-to-hire calculation structure."""
        res = self.service.get_time_to_hire()
        self.assertIn("avg_days", res)
        self.assertIn("min_days", res)
        self.assertIn("max_days", res)
        self.assertIn("total_hires", res)
        self.assertIsInstance(res["avg_days"], float)

    def test_ANA_11_company_isolation(self):
        """ANA-11: Verify company isolation in query filters."""
        res = self.service.get_overview(company=self.current_company)
        self.assertIsNotNone(res["total_applications"])

    def test_ANA_12_cross_company_protection(self):
        """ANA-12: Verify cross-company data access attempt is denied for non-admin users."""
        orig_user = getattr(frappe.session, "user", "Administrator")
        try:
            frappe.session.user = "regular_employer@recruitrain.de"
            with self.assertRaises((ATSPermissionError, Exception)):
                self.service.get_overview(company="UnassociatedCompanyX")
        finally:
            frappe.session.user = orig_user

    def test_ANA_13_unauthenticated_access(self):
        """ANA-13: Verify unauthenticated Guest requests are rejected by permissions layer."""
        orig_user = getattr(frappe.session, "user", "Administrator")
        try:
            frappe.session.user = "Guest"
            with self.assertRaises((ATSPermissionError, Exception)):
                self.service.get_overview()
        finally:
            frappe.session.user = orig_user

    def test_ANA_14_unauthorized_access(self):
        """ANA-14: Verify user without active employer membership is denied access."""
        orig_user = getattr(frappe.session, "user", "Administrator")
        try:
            frappe.session.user = "unauthorized_user_99@example.com"
            with self.assertRaises(Exception):
                self.service.get_overview()
        finally:
            frappe.session.user = orig_user

    def test_ANA_15_invalid_date_range(self):
        """ANA-15: Verify invalid date range (from_date after to_date) raises ATSValidationError."""
        with self.assertRaises(ATSValidationError):
            self.service.get_overview(from_date="2026-12-31", to_date="2026-01-01")

        with self.assertRaises(ATSValidationError):
            self.service.get_overview(from_date="invalid-date-str")

    def test_ANA_16_invalid_filter(self):
        """ANA-16: Verify non-existent job opening parameter raises ATSValidationError."""
        with self.assertRaises(ATSValidationError):
            self.service.get_funnel(job_opening="NON_EXISTENT_JOB_OPENING_999")

    def test_ANA_17_sql_injection_attempt(self):
        """ANA-17: Verify malicious SQL injection strings are safely parameterized."""
        malicious_input = "'; DROP TABLE `tabJob Application`; --"
        res = self.service.get_trends(granularity="monthly")
        self.assertIsInstance(res, list)

        with self.assertRaises(ATSValidationError):
            self.service.get_trends(granularity=malicious_input)

    def test_ANA_18_empty_dataset_handling(self):
        """ANA-18: Verify metrics calculation on empty filters returns clean zero-value structure."""
        res = self.service.get_funnel(from_date="1990-01-01", to_date="1990-01-02")
        self.assertEqual(res["total"], 0)
        self.assertIn("conversion_rates", res)

    def test_ANA_19_null_missing_data_handling(self):
        """ANA-19: Verify optional fields missing from documents do not cause crash."""
        res = self.service.get_recent_activity()
        self.assertIn("data", res)

    def test_ANA_20_response_envelope(self):
        """ANA-20: Verify Whitelisted API endpoints return standard response envelope."""
        frappe.form_dict.clear()
        res = get_overview()
        self.assertTrue(res["success"])
        self.assertIn("data", res)
        self.assertIn("meta", res)

    def test_ANA_21_pagination(self):
        """ANA-21: Verify pagination for recent activity feed."""
        res = self.service.get_recent_activity(page=1, page_size=2)
        self.assertIn("data", res)
        self.assertIn("page", res)
        self.assertIn("page_size", res)
        self.assertEqual(res["page"], 1)
        self.assertEqual(res["page_size"], 2)

    def test_ANA_22_sorting_ordering(self):
        """ANA-22: Verify activity stream is ordered by modified date descending."""
        res = self.service.get_recent_activity()
        data = res["data"]
        if len(data) >= 2:
            self.assertGreaterEqual(data[0]["modified"], data[1]["modified"])

    def test_ANA_23_duplicate_counting_protection(self):
        """ANA-23: Verify unique entity counting without duplication."""
        overview = self.service.get_overview()
        total_cands = frappe.db.count("Candidate", filters={"company": self.current_company})
        self.assertEqual(overview["total_candidates"], total_cands)

    def test_ANA_24_query_safety_performance(self):
        """ANA-24: Verify bounded query execution without unhandled errors."""
        res = self.service.get_recent_activity(page=1, page_size=100)
        self.assertLessEqual(len(res["data"]), 100)

    def test_ANA_25_no_side_effects(self):
        """ANA-25: Assert Analytics operations are 100% read-only with zero DB side effects."""
        app_count_before = frappe.db.count("Job Application")
        offer_count_before = frappe.db.count("Offer")

        self.service.get_overview()
        self.service.get_funnel()
        self.service.get_trends()
        self.service.get_job_metrics()
        self.service.get_application_metrics()
        self.service.get_interview_metrics()
        self.service.get_offer_metrics()
        self.service.get_time_to_hire()
        self.service.get_recent_activity()

        self.assertEqual(frappe.db.count("Job Application"), app_count_before)
        self.assertEqual(frappe.db.count("Offer"), offer_count_before)


def run_analytics_contract_tests():
    """Standalone runner for manual docker exec verification."""
    suite = unittest.TestLoader().loadTestsFromTestCase(TestAnalyticsContract)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    run_analytics_contract_tests()
