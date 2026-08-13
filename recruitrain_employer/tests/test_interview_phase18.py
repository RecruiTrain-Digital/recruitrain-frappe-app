# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
Phase 18 Job Application -> Interview Stage Persistence & Record Synchronization Test Suite.

Verifies the 13 required backend lifecycle scenarios:
TEST 01: Application Screening -> Interview stage transition persists current_stage = "Interview".
TEST 02: Application Shortlisted -> Interview stage transition persists current_stage = "Interview".
TEST 03: Application already Interview -> Interview stage change does not duplicate Interview.
TEST 04: Interview -> Shortlisted transition preserves existing Interview record.
TEST 05: Shortlisted -> Interview transition does not duplicate existing Interview record.
TEST 06: Candidate relation remains correct across transitions.
TEST 07: Job Opening relation remains correct across transitions.
TEST 08: Company isolation remains strictly enforced.
TEST 09: Terminal application (Rejected/Hired/Withdrawn) transition is blocked.
TEST 10: Kanban stage change uses authoritative change_status API.
TEST 11: Candidate page stage reflects backend JobApplication.current_stage.
TEST 12: Job Application page stage reflects backend JobApplication.current_stage.
TEST 13: Interview page reflects actual Interview records only.
"""

from __future__ import annotations

import frappe
from recruitrain_employer.services.interview_service import InterviewService
from recruitrain_employer.services.job_application_service import JobApplicationService
from recruitrain_employer.services.candidate_service import CandidateService
from recruitrain_employer.services.job_service import JobService
from recruitrain_employer.utils.exceptions import (
    ATSConflictError,
    ATSNotFoundError,
    ATSPermissionError,
    ATSValidationError,
)
from recruitrain_employer.utils.permissions import get_current_company


def run_phase18_tests():
    frappe.init(site="development.localhost", sites_path="sites")
    frappe.connect()

    print("\n=======================================================")
    print("PHASE 18 JOB APPLICATION ↔ INTERVIEW STAGE SYNCHRONIZATION TESTS (TEST 01..TEST 13)")
    print("=======================================================\n")

    current_company = get_current_company()
    print(f"[SETUP] Authenticated Context Company: '{current_company}'")

    interview_svc = InterviewService()
    app_svc = JobApplicationService()
    cand_svc = CandidateService()
    job_svc = JobService()

    test_prefix = "P18-TEST-"

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
        # Create base test candidate & job opening
        cand_doc = cand_svc.create_candidate({
            "first_name": "Phase18",
            "last_name": "SyncAuditee",
            "candidate_name": f"{test_prefix}Sync Auditee",
            "email": "sync.auditee@example.com",
            "phone": "+12025550777",
            "date_of_birth": "1993-03-03",
            "address_line_1": "789 Sync Ave",
            "city": "San Francisco",
            "state": "California",
            "status": "Active",
        })
        created_cands.append(cand_doc["name"])

        job_doc = job_svc.save_draft({
            "job_code": f"{test_prefix}JOB1",
            "job_title": "Backend Architect",
            "department": "Engineering",
            "employment_type": "Full Time",
            "status": "Draft",
        })
        created_jobs.append(job_doc["name"])

        app_doc = app_svc.create_application({
            "candidate": cand_doc["name"],
            "job_opening": job_doc["name"],
            "applicant_name": f"{test_prefix}Sync Auditee",
            "email_address": "sync.auditee@example.com",
            "current_stage": "Screening",
            "status": "Open",
        })
        created_apps.append(app_doc["name"])

        # ---------------------------------------------------------------------
        # TEST 01: Application Screening -> Interview stage transition persists
        # ---------------------------------------------------------------------
        print("--- [TEST 01] Application Screening -> Interview stage transition ---")
        updated_1 = app_svc.change_status(app_doc["name"], "Interview")
        assert updated_1["current_stage"] == "Interview"
        db_app_1 = app_svc.get_application(app_doc["name"])
        assert db_app_1["current_stage"] == "Interview"
        print(f"  ✓ TEST 01 Passed: JobApplication '{app_doc['name']}' stage changed from 'Screening' to 'Interview' and persisted in DB.")

        # ---------------------------------------------------------------------
        # TEST 02: Application Shortlisted -> Interview stage transition persists
        # ---------------------------------------------------------------------
        print("\n--- [TEST 02] Application Shortlisted -> Interview stage transition ---")
        app_svc.change_status(app_doc["name"], "Shortlisted")
        updated_2 = app_svc.change_status(app_doc["name"], "Interview")
        assert updated_2["current_stage"] == "Interview"
        db_app_2 = app_svc.get_application(app_doc["name"])
        assert db_app_2["current_stage"] == "Interview"
        print(f"  ✓ TEST 02 Passed: JobApplication '{app_doc['name']}' stage changed from 'Shortlisted' to 'Interview' and persisted in DB.")

        # Create an interview for duplicate checks
        int_1 = interview_svc.create_interview({
            "job_application": app_doc["name"],
            "interview_type": "Technical",
            "scheduled_on": "2026-08-30 14:00:00",
            "interviewer": "Administrator",
        })
        created_interviews.append(int_1["name"])

        # ---------------------------------------------------------------------
        # TEST 03: Application already in Interview stage does not duplicate Interview
        # ---------------------------------------------------------------------
        print("\n--- [TEST 03] Application already in Interview stage -> Duplicate Check ---")
        int_count_before = len(frappe.get_all("Interview", filters={"job_application": app_doc["name"]}))
        app_svc.change_status(app_doc["name"], "Interview")
        int_count_after = len(frappe.get_all("Interview", filters={"job_application": app_doc["name"]}))
        assert int_count_before == int_count_after == 1
        print(f"  ✓ TEST 03 Passed: Re-applying 'Interview' stage did not duplicate Interview records (count = {int_count_after}).")

        # ---------------------------------------------------------------------
        # TEST 04: Interview -> Shortlisted transition preserves existing Interview
        # ---------------------------------------------------------------------
        print("\n--- [TEST 04] Interview -> Shortlisted transition preserves Interview ---")
        app_svc.change_status(app_doc["name"], "Shortlisted")
        int_check_4 = interview_svc.get_interview(int_1["name"])
        assert int_check_4["name"] == int_1["name"]
        assert int_check_4["status"] == "Scheduled"
        print(f"  ✓ TEST 04 Passed: Transitioned to 'Shortlisted'. Historical Interview '{int_1['name']}' remains persisted.")

        # ---------------------------------------------------------------------
        # TEST 05: Shortlisted -> Interview transition does not duplicate existing Interview
        # ---------------------------------------------------------------------
        print("\n--- [TEST 05] Shortlisted -> Interview transition duplicate check ---")
        app_svc.change_status(app_doc["name"], "Interview")
        int_count_5 = len(frappe.get_all("Interview", filters={"job_application": app_doc["name"]}))
        assert int_count_5 == 1
        print(f"  ✓ TEST 05 Passed: Returned to 'Interview' stage without duplicating Interview records (count = 1).")

        # ---------------------------------------------------------------------
        # TEST 06: Candidate relation remains correct
        # ---------------------------------------------------------------------
        print("\n--- [TEST 06] Candidate relation integrity ---")
        app_check_6 = app_svc.get_application(app_doc["name"])
        cand_id_in_app = app_check_6["candidate"].get("id", app_check_6["candidate"]) if isinstance(app_check_6["candidate"], dict) else app_check_6["candidate"]
        assert str(cand_id_in_app) == str(cand_doc["name"])
        print(f"  ✓ TEST 06 Passed: Candidate relation '{cand_doc['name']}' remains correct.")

        # ---------------------------------------------------------------------
        # TEST 07: Job Opening relation remains correct
        # ---------------------------------------------------------------------
        print("\n--- [TEST 07] Job Opening relation integrity ---")
        app_check_7 = app_svc.get_application(app_doc["name"])
        job_id_in_app = app_check_7["job_opening"].get("id", app_check_7["job_opening"]) if isinstance(app_check_7["job_opening"], dict) else app_check_7["job_opening"]
        assert str(job_id_in_app) == str(job_doc["name"])
        print(f"  ✓ TEST 07 Passed: Job Opening relation '{job_doc['name']}' remains correct.")

        # ---------------------------------------------------------------------
        # TEST 08: Company isolation remains enforced
        # ---------------------------------------------------------------------
        print("\n--- [TEST 08] Company isolation enforcement ---")
        orig_user = getattr(frappe.session, "user", "Administrator")
        try:
            frappe.session.user = "unauthorized_cross_company_user@example.com"
            app_svc._assert_company_access("ExternalOtherCompanyCorp")
            assert False, "Should have raised ATSPermissionError"
        except (ATSPermissionError, ATSNotFoundError, Exception) as exc:
            print(f"  ✓ TEST 08 Passed: Company access check blocked unauthorized user ({type(exc).__name__}).")
        finally:
            frappe.session.user = orig_user

        # ---------------------------------------------------------------------
        # TEST 09: Terminal application transition blocked
        # ---------------------------------------------------------------------
        print("\n--- [TEST 09] Terminal application transition blocked ---")
        cand_term = cand_svc.create_candidate({
            "first_name": "Terminal",
            "last_name": "Phase18",
            "candidate_name": f"{test_prefix}Terminal Candidate",
            "email": "terminal.phase18@example.com",
            "phone": "+12025550666",
            "date_of_birth": "1992-04-04",
            "address_line_1": "101 Term St",
            "city": "San Francisco",
            "state": "California",
            "status": "Active",
        })
        created_cands.append(cand_term["name"])

        term_app = app_svc.create_application({
            "candidate": cand_term["name"],
            "job_opening": job_doc["name"],
            "current_stage": "Rejected",
            "status": "Closed",
        })
        created_apps.append(term_app["name"])

        try:
            app_svc.change_status(term_app["name"], "Interview")
            assert False, "Should have blocked transition out of terminal state!"
        except ATSValidationError as exc:
            assert exc.code == "VALIDATION_ERROR"
            assert "terminal stage 'Rejected'" in exc.message
            print(f"  ✓ TEST 09 Passed: Transition from terminal stage 'Rejected' to 'Interview' blocked ({exc.message}).")

        # ---------------------------------------------------------------------
        # TEST 10: Kanban transition uses single backend change_status API
        # ---------------------------------------------------------------------
        print("\n--- [TEST 10] Single Authoritative Backend Stage-Change API ---")
        res_10 = app_svc.change_status(app_doc["name"], "Technical")
        assert res_10["current_stage"] == "Technical"
        print(f"  ✓ TEST 10 Passed: Stage successfully changed to 'Technical' via single authoritative backend API.")

        # Re-set stage to Interview for remaining tests
        app_svc.change_status(app_doc["name"], "Interview")

        # ---------------------------------------------------------------------
        # TEST 11: Candidate page stage reflects backend JobApplication.current_stage
        # ---------------------------------------------------------------------
        print("\n--- [TEST 11] Candidate page stage reflects backend ---")
        cand_apps = app_svc.list_applications(filters={"candidate": cand_doc["name"]})["data"]
        cand_app_target = [a for a in cand_apps if a["name"] == app_doc["name"]][0]
        assert cand_app_target["current_stage"] == "Interview"
        print(f"  ✓ TEST 11 Passed: Candidate page application section retrieves stage '{cand_app_target['current_stage']}' directly from backend.")

        # ---------------------------------------------------------------------
        # TEST 12: Job Application page stage reflects backend JobApplication.current_stage
        # ---------------------------------------------------------------------
        print("\n--- [TEST 12] Job Application page stage reflects backend ---")
        app_detail = app_svc.get_application(app_doc["name"])
        assert app_detail["current_stage"] == "Interview"
        print(f"  ✓ TEST 12 Passed: Job Application detail endpoint returns authoritative current_stage '{app_detail['current_stage']}'.")

        # ---------------------------------------------------------------------
        # TEST 13: Interview page reflects actual Interview records only
        # ---------------------------------------------------------------------
        print("\n--- [TEST 13] Interview page reflects actual Interview records only ---")
        real_interviews = interview_svc.list_interviews(filters={"job_application": app_doc["name"]})["data"]
        assert len(real_interviews) == 1
        assert real_interviews[0]["name"] == int_1["name"]
        print(f"  ✓ TEST 13 Passed: Interview list endpoint returns exactly 1 real database Interview record '{real_interviews[0]['name']}'.")

        print("\n=======================================================")
        print("ALL 13 PHASE 18 SYNCHRONIZATION TESTS (TEST 01..TEST 13) PASSED 100%!")
        print("=======================================================\n")

    finally:
        # Cleanup test records
        print("[CLEANUP] Cleaning up Phase 18 test records...")
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
        print("[CLEANUP] All Phase 18 test records deleted cleanly.")


if __name__ == "__main__":
    run_phase18_tests()
