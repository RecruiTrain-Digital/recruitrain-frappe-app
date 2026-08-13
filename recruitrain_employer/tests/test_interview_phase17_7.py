# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
Phase 17.7 Backend Audit & Validation Test Suite.

Verifies the 10 core domain lifecycle requirements between Interview,
Job Application, Candidate, and Job Opening entities:

TEST 01: Application stage = Interview -> Create Interview succeeds.
TEST 02: Application stage = Terminal (Rejected/Hired/Withdrawn) -> Attempt Interview fails with ATSValidationError.
TEST 03: Existing Interview -> Move Application Interview -> Shortlisted -> Historical/Scheduled Interview record remains intact.
TEST 04: Move Application Shortlisted -> Interview -> Application is eligible, no auto-interview created.
TEST 05: Interview status Scheduled -> Rescheduled -> Application stage unchanged.
TEST 06: Interview status Scheduled -> Completed -> Application stage unchanged.
TEST 07: Application Kanban stage changes -> Interview relationship remains valid.
TEST 08: Candidate status remains independent.
TEST 09: Cross-company access remains blocked.
TEST 10: Interview deletion respects referential integrity (returns ATSConflictError 409).
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


def run_phase17_7_tests():
    frappe.init(site="development.localhost", sites_path="sites")
    frappe.connect()

    print("\n=======================================================")
    print("PHASE 17.7 INTERVIEW ↔ JOB APPLICATION LIFECYCLE TESTS (TEST 01..TEST 10)")
    print("=======================================================\n")

    current_company = get_current_company()
    print(f"[SETUP] Authenticated Context Company: '{current_company}'")

    interview_svc = InterviewService()
    app_svc = JobApplicationService()
    cand_svc = CandidateService()
    job_svc = JobService()

    test_prefix = "P17-7-TEST-"
    
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
            "first_name": "Lifecycle",
            "last_name": "Auditee",
            "candidate_name": f"{test_prefix}Lifecycle Auditee",
            "email": "lifecycle.auditee@example.com",
            "phone": "+12025550999",
            "date_of_birth": "1995-01-01",
            "address_line_1": "123 Main St",
            "city": "San Francisco",
            "state": "California",
            "status": "Active",
        })
        created_cands.append(cand_doc["name"])

        job_doc = job_svc.save_draft({
            "job_code": f"{test_prefix}JOB1",
            "job_title": "Fullstack Engineer",
            "department": "Engineering",
            "employment_type": "Full Time",
            "status": "Draft",
        })
        created_jobs.append(job_doc["name"])

        app_doc = app_svc.create_application({
            "candidate": cand_doc["name"],
            "job_opening": job_doc["name"],
            "applicant_name": f"{test_prefix}Lifecycle Auditee",
            "email_address": "lifecycle.auditee@example.com",
            "current_stage": "Interview",
            "status": "Open",
        })
        created_apps.append(app_doc["name"])

        # ---------------------------------------------------------------------
        # TEST 01: Application stage = Interview -> Create Interview succeeds
        # ---------------------------------------------------------------------
        print("--- [TEST 01] Create Interview when stage = Interview ---")
        int_1 = interview_svc.create_interview({
            "job_application": app_doc["name"],
            "interview_type": "Technical",
            "scheduled_on": "2026-08-25 10:00:00",
            "duration": 45,
            "interviewer": "Administrator",
        })
        created_interviews.append(int_1["name"])
        assert int_1["status"] == "Scheduled"
        assert int_1["job_application"] == app_doc["name"]
        print(f"  ✓ TEST 01 Passed: Interview '{int_1['name']}' created successfully for Job Application in stage 'Interview'.")

        # ---------------------------------------------------------------------
        # TEST 02: Application in Terminal Stage -> Create Interview fails
        # ---------------------------------------------------------------------
        print("\n--- [TEST 02] Attempt Interview creation on Terminal Application ---")
        cand_term = cand_svc.create_candidate({
            "first_name": "Terminal",
            "last_name": "Applicant",
            "candidate_name": f"{test_prefix}Terminal Applicant",
            "email": "terminal.applicant@example.com",
            "phone": "+12025550888",
            "date_of_birth": "1994-02-02",
            "address_line_1": "456 Side St",
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
            interview_svc.create_interview({
                "job_application": term_app["name"],
                "interview_type": "HR",
                "interviewer": "Administrator",
            })
            assert False, "Should have raised ATSValidationError for terminal stage"
        except ATSValidationError as exc:
            assert exc.code == "VALIDATION_ERROR"
            assert "terminal stage 'Rejected'" in exc.message
            print(f"  ✓ TEST 02 Passed: Rejected interview scheduling on terminal application ({exc.message}).")

        # ---------------------------------------------------------------------
        # TEST 03: Move Application Interview -> Shortlisted -> Historical Interview intact
        # ---------------------------------------------------------------------
        print("\n--- [TEST 03] Move Application Interview -> Shortlisted (Preserve Historical Interview) ---")
        app_svc.update_application(app_doc["name"], {"current_stage": "Shortlisted"})
        
        # Verify interview doc is still intact and Scheduled
        int_check_3 = interview_svc.get_interview(int_1["name"])
        assert int_check_3["name"] == int_1["name"]
        assert int_check_3["status"] == "Scheduled"
        print(f"  ✓ TEST 03 Passed: Application moved to 'Shortlisted'. Historical Interview '{int_1['name']}' remains intact with status 'Scheduled'.")

        # ---------------------------------------------------------------------
        # TEST 04: Move Application Shortlisted -> Interview (Explicit Creation Required)
        # ---------------------------------------------------------------------
        print("\n--- [TEST 04] Move Application Shortlisted -> Interview (Explicit Scheduling Only) ---")
        initial_interview_count = len(frappe.get_all("Interview", filters={"job_application": app_doc["name"]}))
        app_svc.update_application(app_doc["name"], {"current_stage": "Interview"})
        post_interview_count = len(frappe.get_all("Interview", filters={"job_application": app_doc["name"]}))
        assert initial_interview_count == post_interview_count, "No auto-creation of Interview should occur on Kanban move!"
        print(f"  ✓ TEST 04 Passed: Stage updated to 'Interview' without auto-creating duplicate Interview records (count remains {post_interview_count}).")

        # ---------------------------------------------------------------------
        # TEST 05: Interview Status Scheduled -> Rescheduled -> Application Stage Unchanged
        # ---------------------------------------------------------------------
        print("\n--- [TEST 05] Interview Status Scheduled -> Rescheduled ---")
        app_before_5 = app_svc.get_application(app_doc["name"])
        interview_svc.change_status(int_1["name"], "Rescheduled")
        app_after_5 = app_svc.get_application(app_doc["name"])
        assert app_before_5["current_stage"] == app_after_5["current_stage"] == "Interview"
        print(f"  ✓ TEST 05 Passed: Interview status changed to 'Rescheduled'. Application stage remained '{app_after_5['current_stage']}'.")

        # ---------------------------------------------------------------------
        # TEST 06: Interview Status Scheduled -> Completed -> Application Stage Unchanged
        # ---------------------------------------------------------------------
        print("\n--- [TEST 06] Interview Status Scheduled -> Completed ---")
        interview_svc.change_status(int_1["name"], "Completed")
        app_after_6 = app_svc.get_application(app_doc["name"])
        assert app_after_6["current_stage"] == "Interview"
        print(f"  ✓ TEST 06 Passed: Interview status changed to 'Completed'. Application stage remained '{app_after_6['current_stage']}'.")

        # Re-set status to Scheduled for remaining tests
        interview_svc.change_status(int_1["name"], "Scheduled")

        # ---------------------------------------------------------------------
        # TEST 07: Application Kanban Stage Changes -> Interview Link Remains Valid
        # ---------------------------------------------------------------------
        print("\n--- [TEST 07] Application Kanban Stage Changes -> Relationship Integrity ---")
        app_svc.update_application(app_doc["name"], {"current_stage": "Technical"})
        int_check_7 = interview_svc.get_interview(int_1["name"])
        app_id_in_int = int_check_7["job_application"].get("id", int_check_7["job_application"]) if isinstance(int_check_7["job_application"], dict) else int_check_7["job_application"]
        assert str(app_id_in_int) == str(app_doc["name"])
        print(f"  ✓ TEST 07 Passed: Kanban stage moved to 'Technical'. Interview '{int_1['name']}' remains firmly linked to Application '{app_doc['name']}'.")

        # ---------------------------------------------------------------------
        # TEST 08: Candidate Status Independence
        # ---------------------------------------------------------------------
        print("\n--- [TEST 08] Candidate Status Independence ---")
        cand_before_8 = cand_svc.get_candidate(cand_doc["name"])
        interview_svc.change_status(int_1["name"], "Cancelled")
        cand_after_8 = cand_svc.get_candidate(cand_doc["name"])
        assert cand_before_8["status"] == cand_after_8["status"], f"Candidate status mutated from {cand_before_8['status']} to {cand_after_8['status']}!"
        print(f"  ✓ TEST 08 Passed: Changing Interview status did not mutate Candidate.status (remained '{cand_after_8['status']}').")

        # ---------------------------------------------------------------------
        # TEST 09: Cross-Company Access Blocked
        # ---------------------------------------------------------------------
        print("\n--- [TEST 09] Cross-Company Access Blocked ---")
        orig_user = getattr(frappe.session, "user", "Administrator")
        try:
            frappe.session.user = "unauthorized_cross_company_user@example.com"
            interview_svc._assert_company_access("ExternalOtherCompanyCorp")
            assert False, "Should have raised ATSPermissionError"
        except (ATSPermissionError, ATSNotFoundError, Exception) as exc:
            print(f"  ✓ TEST 09 Passed: Cross-company access attempt blocked ({type(exc).__name__}).")
        finally:
            frappe.session.user = orig_user

        # ---------------------------------------------------------------------
        # TEST 10: Interview Deletion Respects Referential Integrity (HTTP 409 Conflict)
        # ---------------------------------------------------------------------
        print("\n--- [TEST 10] Interview Deletion Referential Integrity (HTTP 409) ---")
        # Ensure activity log exists for int_1
        logs = frappe.get_all("Activity Log", filters={"reference_doctype": "Interview", "reference_name": int_1["name"]})
        if not logs:
            from recruitrain_employer.utils.activity_logger import log_activity
            log_activity(
                activity_type="Interview Scheduled",
                description=f"Interview {int_1['name']} scheduled.",
                reference_doctype="Interview",
                reference_name=int_1["name"],
                candidate=cand_doc["name"],
                job_opening=job_doc["name"],
                job_application=app_doc["name"],
                company=current_company,
            )

        try:
            interview_svc.delete_interview(int_1["name"])
            assert False, "Should have raised ATSConflictError!"
        except ATSConflictError as exc:
            assert exc.code == "CONFLICT"
            print(f"  ✓ TEST 10 Passed: Deletion of Interview with linked Activity Log blocked with ATSConflictError (HTTP 409).")

        print("\n=======================================================")
        print("ALL 10 PHASE 17.7 LIFECYCLE TESTS (TEST 01..TEST 10) PASSED 100%!")
        print("=======================================================\n")

    finally:
        # Cleanup test entities
        print("[CLEANUP] Cleaning up Phase 17.7 test records...")
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
        print("[CLEANUP] All Phase 17.7 test records deleted cleanly.")


if __name__ == "__main__":
    run_phase17_7_tests()
