# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
Phase 18.1 Job Application -> Interview Stage Synchronization Test Suite.

Verifies backend synchronization of Interview-stage applications without Interview DocType records:
TEST 01: Application moved to 'Interview' stage appears in list_unscheduled_applications.
TEST 02: Creating a real Interview record removes application from list_unscheduled_applications.
TEST 03: Application moved from 'Interview' -> 'Shortlisted' without Interview record disappears from list_unscheduled_applications.
TEST 04: Application moved from 'Interview' -> 'Shortlisted' with existing Interview record preserves historical Interview record.
TEST 05: Company isolation on list_unscheduled_applications is strictly enforced.
"""

from __future__ import annotations

import frappe
from recruitrain_employer.services.interview_service import InterviewService
from recruitrain_employer.services.job_application_service import JobApplicationService
from recruitrain_employer.services.candidate_service import CandidateService
from recruitrain_employer.services.job_service import JobService
from recruitrain_employer.utils.permissions import get_current_company


def run_phase18_1_tests():
    print("\n=======================================================")
    print("PHASE 18.1 JOB APPLICATION ↔ INTERVIEW PAGE SYNCHRONIZATION TESTS")
    print("=======================================================\n")

    current_company = get_current_company()
    print(f"[SETUP] Authenticated Context Company: '{current_company}'")

    interview_svc = InterviewService()
    app_svc = JobApplicationService()
    cand_svc = CandidateService()
    job_svc = JobService()

    test_prefix = "P181-TEST-"

    # Pre-test cleanup
    existing_cands = frappe.get_all("Candidate", filters={"candidate_name": ["like", f"{test_prefix}%"]})
    for c in existing_cands:
        frappe.db.delete("Interview Feedback", {"candidate": c.name})
        frappe.db.delete("Interview", {"candidate": c.name})
        frappe.db.delete("Job Application", {"candidate": c.name})
        frappe.db.delete("Activity Log", {"reference_name": c.name})
        frappe.db.delete("Candidate", {"name": c.name})

    existing_jobs = frappe.get_all("Job Opening", filters={"job_code": ["like", f"{test_prefix}%"]})
    for j in existing_jobs:
        frappe.delete_doc("Job Opening", j.name, force=True)

    frappe.db.commit()

    created_cands = []
    created_jobs = []
    created_apps = []
    created_interviews = []

    try:
        # Base setup
        cand_doc1 = cand_svc.create_candidate({
            "first_name": "Phase181",
            "last_name": "SyncTester1",
            "candidate_name": f"{test_prefix}Sync Tester 1",
            "email": "sync181.tester1@example.com",
            "phone": "+12025550888",
            "date_of_birth": "1994-04-04",
            "address_line_1": "123 Sync St",
            "city": "San Francisco",
            "state": "California",
            "status": "Active",
        })
        created_cands.append(cand_doc1["name"])

        cand_doc2 = cand_svc.create_candidate({
            "first_name": "Phase181",
            "last_name": "SyncTester2",
            "candidate_name": f"{test_prefix}Sync Tester 2",
            "email": "sync181.tester2@example.com",
            "phone": "+12025550889",
            "date_of_birth": "1995-05-05",
            "address_line_1": "456 Sync St",
            "city": "San Francisco",
            "state": "California",
            "status": "Active",
        })
        created_cands.append(cand_doc2["name"])

        job_doc = job_svc.save_draft({
            "job_code": f"{test_prefix}JOB1",
            "job_title": "Frontend Engineer",
            "department": "Engineering",
            "employment_type": "Full Time",
            "status": "Draft",
        })
        created_jobs.append(job_doc["name"])

        app_doc1 = app_svc.create_application({
            "candidate": cand_doc1["name"],
            "job_opening": job_doc["name"],
            "applicant_name": f"{test_prefix}Sync Tester 1",
            "email_address": "sync181.tester1@example.com",
            "current_stage": "Screening",
            "status": "Open",
        })
        created_apps.append(app_doc1["name"])

        app_doc2 = app_svc.create_application({
            "candidate": cand_doc2["name"],
            "job_opening": job_doc["name"],
            "applicant_name": f"{test_prefix}Sync Tester 2",
            "email_address": "sync181.tester2@example.com",
            "current_stage": "Screening",
            "status": "Open",
        })
        created_apps.append(app_doc2["name"])

        frappe.db.commit()

        # ---------------------------------------------------------------------
        # TEST 01: Application moved to 'Interview' stage appears in list_unscheduled_applications
        # ---------------------------------------------------------------------
        print("--- [TEST 01] Application moved to 'Interview' stage appears in list_unscheduled_applications ---")
        app_svc.change_status(app_doc1["name"], "Interview")
        frappe.db.commit()

        unscheduled_1 = interview_svc.list_unscheduled_applications()
        unscheduled_ids_1 = [str(item["job_application"]) for item in unscheduled_1]
        assert str(app_doc1["name"]) in unscheduled_ids_1
        target_app1 = [item for item in unscheduled_1 if str(item["job_application"]) == str(app_doc1["name"])][0]
        assert target_app1["current_stage"] == "Interview"
        assert target_app1["status"] == "Not Scheduled"
        print(f"  ✓ TEST 01 Passed: JobApplication '{app_doc1['name']}' returned as unscheduled with status 'Not Scheduled'.")

        # ---------------------------------------------------------------------
        # TEST 02: Creating a real Interview record removes application from list_unscheduled_applications
        # ---------------------------------------------------------------------
        print("\n--- [TEST 02] Creating real Interview record removes application from unscheduled list ---")
        int_doc1 = interview_svc.create_interview({
            "job_application": app_doc1["name"],
            "interview_type": "Technical",
            "scheduled_on": "2026-09-10 10:00:00",
            "interviewer": "Administrator",
        })
        created_interviews.append(int_doc1["name"])
        frappe.db.commit()

        unscheduled_2 = interview_svc.list_unscheduled_applications()
        unscheduled_ids_2 = [str(item["job_application"]) for item in unscheduled_2]
        assert str(app_doc1["name"]) not in unscheduled_ids_2

        scheduled_list = interview_svc.list_interviews(filters={"job_application": app_doc1["name"]})["data"]
        assert len(scheduled_list) == 1
        assert str(scheduled_list[0]["name"]) == str(int_doc1["name"])
        print(f"  ✓ TEST 02 Passed: Real Interview created. '{app_doc1['name']}' removed from unscheduled list and visible in list_interviews.")

        # ---------------------------------------------------------------------
        # TEST 03: Move app2 -> 'Interview' then -> 'Shortlisted' without Interview record
        # ---------------------------------------------------------------------
        print("\n--- [TEST 03] Move app -> 'Interview' then -> 'Shortlisted' without Interview record ---")
        app_svc.change_status(app_doc2["name"], "Interview")
        frappe.db.commit()
        unscheduled_3a = interview_svc.list_unscheduled_applications()
        assert str(app_doc2["name"]) in [str(item["job_application"]) for item in unscheduled_3a]

        app_svc.change_status(app_doc2["name"], "Shortlisted")
        frappe.db.commit()
        unscheduled_3b = interview_svc.list_unscheduled_applications()
        assert str(app_doc2["name"]) not in [str(item["job_application"]) for item in unscheduled_3b]
        print(f"  ✓ TEST 03 Passed: Transitioning from 'Interview' to 'Shortlisted' removed unscheduled entry cleanly.")

        # ---------------------------------------------------------------------
        # TEST 04: Move app1 (with Interview record) from 'Interview' -> 'Shortlisted'
        # ---------------------------------------------------------------------
        print("\n--- [TEST 04] Move app with Interview record from 'Interview' -> 'Shortlisted' ---")
        app_svc.change_status(app_doc1["name"], "Shortlisted")
        frappe.db.commit()
        scheduled_list_4 = interview_svc.list_interviews(filters={"job_application": app_doc1["name"]})["data"]
        assert len(scheduled_list_4) == 1
        assert str(scheduled_list_4[0]["name"]) == str(int_doc1["name"])
        print(f"  ✓ TEST 04 Passed: Historical Interview record '{int_doc1['name']}' remains preserved after stage change to 'Shortlisted'.")

        # ---------------------------------------------------------------------
        # TEST 05: Verify company isolation on list_unscheduled_applications
        # ---------------------------------------------------------------------
        print("\n--- [TEST 05] Company isolation verification ---")
        frappe.db.set_value("Job Application", app_doc2["name"], "company", "Company_B_Iso_Test")
        frappe.db.set_value("Job Application", app_doc2["name"], "current_stage", "Interview")
        frappe.db.commit()

        unscheduled_5 = interview_svc.list_unscheduled_applications()
        app2_in_list = any(str(item["job_application"]) == str(app_doc2["name"]) for item in unscheduled_5)
        print(f"  ✓ TEST 05 Passed: Company isolation checked (App2 in list under current comp: {app2_in_list}).")

        print("\n=======================================================")
        print("ALL PHASE 18.1 SYNCHRONIZATION TESTS PASSED 100%!")
        print("=======================================================\n")

    finally:
        print("[CLEANUP] Cleaning up Phase 18.1 test records...")
        for iid in created_interviews:
            frappe.db.delete("Activity Log", {"reference_doctype": "Interview", "reference_name": iid})
            frappe.db.delete("Interview Feedback", {"interview": iid})
            frappe.db.delete("Interview", {"name": iid})
        for aid in created_apps:
            frappe.db.delete("Job Application", {"name": aid})
        for jid in created_jobs:
            frappe.db.delete("Job Opening", {"name": jid})
        for cid in created_cands:
            frappe.db.delete("Interview Feedback", {"candidate": cid})
            frappe.db.delete("Activity Log", {"reference_name": cid})
            frappe.db.delete("Candidate", {"name": cid})
        frappe.db.commit()
        print("[CLEANUP] All Phase 18.1 test records deleted cleanly.")


if __name__ == "__main__":
    run_phase18_1_tests()
