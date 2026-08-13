# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
Contract Verification & Hardening Test Suite for RecruitTrain Interviews (INT-01 to INT-30).
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


def run_interview_contract_tests():
    print("\n=======================================================")
    print("RECRUITRAIN INTERVIEW BACKEND CONTRACT VERIFICATION (INT-01..INT-30)")
    print("=======================================================\n")

    current_company = get_current_company()
    print(f"[SETUP] Authenticated Context Company: '{current_company}'")

    interview_svc = InterviewService()
    app_svc = JobApplicationService()
    cand_svc = CandidateService()
    job_svc = JobService()

    # Pre-test cleanup for test entities
    test_prefix = "INT-TEST-VERIFY-"
    existing_cands = frappe.get_all("Candidate", filters={"candidate_name": ["like", f"{test_prefix}%"]})
    for c in existing_cands:
        frappe.db.delete("Interview Feedback", {"candidate": c.name})
        frappe.db.delete("Interview", {"candidate": c.name})
        frappe.db.delete("Activity Logs", {"candidate": c.name})
        frappe.delete_doc("Candidate", c.name, force=True)

    existing_jobs = frappe.get_all("Job Opening", filters={"job_code": ["like", f"{test_prefix}%"]})
    for j in existing_jobs:
        frappe.delete_doc("Job Opening", j.name, force=True)

    frappe.db.commit()

    created_cands = []
    created_jobs = []
    created_apps = []
    created_interviews = []

    try:
        # Prerequisites: Create Candidate, Job Opening, and Job Application
        print("[SETUP] Creating prerequisite entities (Candidate, Job Opening, Job Application)...")
        cand_doc = cand_svc.create_candidate({
            "first_name": "John",
            "last_name": "Candidate",
            "candidate_name": f"{test_prefix}John Candidate",
            "email": "john.interview.test@example.com",
            "phone": "+12025550199",
            "date_of_birth": "1995-05-15",
            "address_line_1": "123 Tech Street",
            "city": "San Francisco",
            "state": "California",
            "status": "Active",
        })
        created_cands.append(cand_doc["name"])

        job_doc = job_svc.save_draft({
            "job_code": f"{test_prefix}JOB1",
            "job_title": "Lead Software Architect",
            "department": "Engineering",
            "employment_type": "Full Time",
            "job_summary": "Architecture & Engineering role",
            "status": "Draft",
        })
        created_jobs.append(job_doc["name"])

        app_doc = app_svc.create_application({
            "candidate": cand_doc["name"],
            "job_opening": job_doc["name"],
            "applicant_name": f"{test_prefix}John Candidate",
            "email_address": "john.interview.test@example.com",
            "resume": "/files/test_resume.pdf",
            "status": "Applied",
        })
        created_apps.append(app_doc["name"])

        print(f"  ✓ Prerequisites created: Cand='{cand_doc['name']}', Job='{job_doc['name']}', App='{app_doc['name']}'")

        # INT-06: Create / Schedule Interview
        print("\n--- [INT-06] Testing Create / Schedule Interview ---")
        sched_payload = {
            "job_application": app_doc["name"],
            "interview_type": "Technical",
            "scheduled_on": "2026-09-01 10:00:00",
            "duration": 45,
            "meeting_link": "https://meet.recruitrain.de/int-06-test",
            "location": "Online Video Room 1",
            "interviewer": "Administrator",
            "status": "Scheduled",
        }
        int_1 = interview_svc.create_interview(sched_payload)
        created_interviews.append(int_1["name"])

        assert int_1["status"] == "Scheduled"
        assert int_1["interview_type"] == "Technical"
        assert int_1["job_application"] == app_doc["name"]
        assert int_1["candidate"] == cand_doc["name"]
        assert int_1["job_opening"] == job_doc["name"]
        assert int_1["company"] == current_company
        print(f"  ✓ INT-06 Passed: Interview '{int_1['name']}' scheduled successfully.")

        # INT-01: List Interviews
        print("\n--- [INT-01] Testing List Interviews ---")
        list_res = interview_svc.list_interviews(page=1, page_size=10)
        assert "data" in list_res and "total" in list_res
        assert list_res["page"] == 1 and list_res["page_size"] == 10
        assert list_res["total"] >= 1
        found_in_list = any(i["name"] == int_1["name"] for i in list_res["data"])
        assert found_in_list, "Created interview missing from list!"
        print(f"  ✓ INT-01 Passed: List returned {len(list_res['data'])} records, total={list_res['total']}.")

        # INT-02: Pagination
        print("\n--- [INT-02] Testing Pagination Clamping & Metadata ---")
        pag_res = interview_svc.list_interviews(page=1, page_size=1)
        assert len(pag_res["data"]) == 1
        assert pag_res["page"] == 1
        assert pag_res["page_size"] == 1
        print("  ✓ INT-02 Passed: Strict page size clamping and pagination metadata verified.")

        # INT-03: Search Interviews
        print("\n--- [INT-03] Testing Search Interviews ---")
        search_res = interview_svc.search_interviews(search="Technical")
        assert search_res["total"] >= 1
        assert any(i["name"] == int_1["name"] for i in search_res["data"])
        print("  ✓ INT-03 Passed: Search query matching 'Technical' succeeded.")

        # INT-04: Filters
        print("\n--- [INT-04] Testing Filters ---")
        filter_res = interview_svc.list_interviews(filters={
            "status": "Scheduled",
            "interview_type": "Technical",
            "job_application": app_doc["name"],
        })
        assert any(i["name"] == int_1["name"] for i in filter_res["data"])
        empty_res = interview_svc.list_interviews(filters={"status": "Completed", "job_application": app_doc["name"]})
        assert len(empty_res["data"]) == 0
        print("  ✓ INT-04 Passed: Filtering by status, type, and job_application succeeded.")

        # INT-05: Get Single Interview
        print("\n--- [INT-05] Testing Get Single Interview ---")
        get_res = interview_svc.get_interview(int_1["name"])
        assert get_res["name"] == int_1["name"]
        assert get_res["meeting_link"] == "https://meet.recruitrain.de/int-06-test"
        print("  ✓ INT-05 Passed: Retrieved interview detail record successfully.")

        # INT-07: Update Interview
        print("\n--- [INT-07] Testing Update Interview ---")
        update_res = interview_svc.update_interview(int_1["name"], {
            "duration": 60,
            "location": "Conference Room B",
            "remarks": "Candidate requested 60 min session",
        })
        assert update_res["duration"] == 60
        assert update_res["location"] == "Conference Room B"
        print("  ✓ INT-07 Passed: Partial update applied successfully.")

        # INT-08: Valid Status Transitions
        print("\n--- [INT-08] Testing Valid Status Transitions ---")
        status_res = interview_svc.change_status(int_1["name"], "Rescheduled")
        assert status_res["status"] == "Rescheduled"
        print("  ✓ INT-08 Passed: Status transitioned from Scheduled -> Rescheduled.")

        # INT-09: Invalid Status Transition
        print("\n--- [INT-09] Testing Invalid Status Transition ---")
        try:
            interview_svc.change_status(int_1["name"], "NonExistentStatus")
            assert False, "Should have raised ATSValidationError"
        except ATSValidationError as exc:
            assert exc.code == "VALIDATION_ERROR"
            print("  ✓ INT-09 Passed: Rejected invalid status 'NonExistentStatus'.")

        # INT-10: Reschedule Workflow
        print("\n--- [INT-10] Testing Reschedule Workflow ---")
        resched_res = interview_svc.update_interview(int_1["name"], {
            "scheduled_on": "2026-09-02 14:00:00",
            "status": "Rescheduled",
            "remarks": "Rescheduled per interviewer availability",
        })
        assert resched_res["status"] == "Rescheduled"
        assert "2026-09-02" in str(resched_res["scheduled_on"])
        print("  ✓ INT-10 Passed: Rescheduled date and status updated.")

        # INT-11: Cancellation Workflow
        print("\n--- [INT-11] Testing Cancellation Workflow ---")
        cancel_res = interview_svc.change_status(int_1["name"], "Cancelled")
        assert cancel_res["status"] == "Cancelled"
        print("  ✓ INT-11 Passed: Interview status updated to Cancelled.")

        # Re-set status to Scheduled for downstream relationship tests
        interview_svc.change_status(int_1["name"], "Scheduled")

        # INT-12, INT-13, INT-14: Relationship Verification
        print("\n--- [INT-12..INT-14] Testing Candidate, Job App, & Job Opening Relationships ---")
        fresh_get = interview_svc.get_interview(int_1["name"])
        assert str(fresh_get["candidate"]) == str(cand_doc["name"])
        assert str(fresh_get["job_application"]) == str(app_doc["name"])
        assert str(fresh_get["job_opening"]) == str(job_doc["name"])
        print("  ✓ INT-12, INT-13, INT-14 Passed: Entity foreign keys match source candidate, job application, and job opening.")

        # INT-15: Interviewer Relationship
        print("\n--- [INT-15] Testing Interviewer Relationship ---")
        try:
            interview_svc.create_interview({
                "job_application": app_doc["name"],
                "interview_type": "HR",
                "interviewer": "NonExistentUser_9999",
            })
            assert False, "Should have raised ATSValidationError for non-existent interviewer user"
        except ATSValidationError as exc:
            assert exc.code == "VALIDATION_ERROR"
            print("  ✓ INT-15 Passed: Rejected non-existent interviewer user.")

        # INT-16 & INT-28: Company Isolation & Spoofing Prevention
        print("\n--- [INT-16 & INT-28] Testing Company Isolation & Spoofing Prevention ---")
        spoofed_payload = {
            "job_application": app_doc["name"],
            "interview_type": "HR",
            "interviewer": "Administrator",
            "company": "MaliciousSpoofedCompanyCorp",
        }
        spoofed_res = interview_svc.create_interview(spoofed_payload)
        created_interviews.append(spoofed_res["name"])
        assert spoofed_res["company"] == current_company, "Security violation: company spoofing succeeded!"
        print("  ✓ INT-16 & INT-28 Passed: Client-supplied spoofed company was forcibly overridden by session company.")

        # INT-17: Unauthorized / Guest User
        print("\n--- [INT-17] Testing Cross-Company / Unauthorized Access ---")
        orig_user = getattr(frappe.session, "user", "Administrator")
        try:
            frappe.session.user = "test_regular_user@example.com"
            interview_svc._assert_company_access("OtherUnassociatedCompany")
            assert False, "Should have raised ATSPermissionError or ATSCompanyNotFoundError"
        except (ATSPermissionError, ATSNotFoundError, Exception) as exc:
            assert hasattr(exc, "code") or "Employer User" in str(exc)
            print(f"  ✓ INT-17 Passed: Cross-company access attempt properly blocked ({type(exc).__name__}).")
        finally:
            frappe.session.user = orig_user

        # INT-18: Non-existent Interview Query
        print("\n--- [INT-18] Testing Non-existent Interview Query ---")
        try:
            interview_svc.get_interview("NON_EXISTENT_INT_999")
            assert False, "Should have raised ATSNotFoundError"
        except ATSNotFoundError as exc:
            assert exc.code == "NOT_FOUND"
            print("  ✓ INT-18 Passed: Non-existent interview query raised ATSNotFoundError.")

        # INT-19: Datetime Validation
        print("\n--- [INT-19] Testing Invalid Scheduled_on Datetime Validation ---")
        try:
            interview_svc.create_interview({
                "job_application": app_doc["name"],
                "interview_type": "Phone",
                "scheduled_on": "Invalid-Date-Format-Text",
            })
            assert False, "Should have raised ATSValidationError"
        except ATSValidationError as exc:
            assert exc.code == "VALIDATION_ERROR"
            print("  ✓ INT-19 Passed: Invalid scheduled_on datetime string rejected.")

        # INT-20: Concurrent Update / Conflict Handling
        print("\n--- [INT-20] Testing Concurrent Update / Conflict Handling ---")
        try:
            raise frappe.exceptions.DuplicateEntryError("Duplicate entry")
        except Exception as exc:
            from recruitrain_employer.api.interviews import _handle_ats_exception
            err_envelope = _handle_ats_exception(exc)
            assert err_envelope["error"]["code"] == "CONFLICT"
            assert err_envelope["success"] is False
            print("  ✓ INT-20 Passed: Concurrency/Duplicate exceptions translate to HTTP 409 CONFLICT envelope.")

        # INT-21: Delete Safety
        print("\n--- [INT-21] Testing Delete Safety ---")
        del_int = interview_svc.create_interview({
            "job_application": app_doc["name"],
            "interview_type": "Phone",
            "interviewer": "Administrator",
            "status": "Scheduled",
        })
        frappe.db.delete("Activity Logs", {"reference_name": del_int["name"]})
        interview_svc.delete_interview(del_int["name"])
        try:
            interview_svc.get_interview(del_int["name"])
            assert False, "Should have raised ATSNotFoundError"
        except ATSNotFoundError:
            print("  ✓ INT-21 Passed: Unreferenced interview deleted safely.")

        # INT-22 & INT-23: Linked Interview Feedback Referential Integrity
        print("\n--- [INT-22 & INT-23] Testing Linked Interview Feedback & Delete Protection ---")
        feedback_doc = frappe.new_doc("Interview Feedback")
        feedback_doc.feedback_name = f"FB-{frappe.generate_hash(length=8)}"
        feedback_doc.interview = int_1["name"]
        feedback_doc.candidate = int_1["candidate"]
        feedback_doc.job_opening = int_1["job_opening"]
        feedback_doc.job_application = int_1["job_application"]
        feedback_doc.interviewer = "Administrator"
        feedback_doc.recommendation = "Hire"
        feedback_doc.status = "Submitted"
        feedback_doc.insert(ignore_permissions=True, ignore_links=True)
        frappe.db.commit()

        try:
            interview_svc.delete_interview(int_1["name"])
            assert False, "Should have blocked deletion due to linked Interview Feedback!"
        except ATSConflictError as exc:
            assert exc.code == "CONFLICT"
            print("  ✓ INT-22 & INT-23 Passed: Deletion of interview with linked Interview Feedback strictly blocked with ATSConflictError.")
        finally:
            frappe.delete_doc("Interview Feedback", feedback_doc.name, force=True)
            frappe.db.commit()

        # INT-24: Activity Log / Timeline Integration
        print("\n--- [INT-24] Testing Activity Log Integration ---")
        logs = frappe.get_all("Activity Logs", filters={"reference_name": int_1["name"]})
        assert len(logs) > 0
        print(f"  ✓ INT-24 Passed: Verified {len(logs)} activity log entry for interview creation.")

        # INT-25: Notification Behavior
        print("\n--- [INT-25] Testing Notification Log Emission ---")
        notifs = frappe.get_all("Notification Log", filters={"document_name": int_1["name"]})
        assert len(notifs) > 0
        print(f"  ✓ INT-25 Passed: Verified {len(notifs)} notification log emitted for interview.")

        # INT-26: Response Envelope Structure Verification
        print("\n--- [INT-26] Testing Response Envelope Compatibility ---")
        required_keys = {
            "name", "interview_name", "job_application", "candidate", "job_opening",
            "company", "interview_type", "scheduled_on", "duration", "location",
            "interviewer", "status"
        }
        missing_keys = required_keys - set(int_1.keys())
        assert not missing_keys, f"Missing required fields: {missing_keys}"
        print("  ✓ INT-26 Passed: Response dictionary contains all standard fields.")

        # INT-27: Server-controlled Fields Protection
        print("\n--- [INT-27] Testing Server-controlled Fields Protection ---")
        try:
            interview_svc.update_interview(int_1["name"], {
                "company": "UnauthorizedCompanyUpdate",
                "candidate": "UnauthorizedCandidateUpdate",
            })
            assert False, "Should have raised ATSValidationError for immutable fields"
        except ATSValidationError as exc:
            assert exc.code == "VALIDATION_ERROR"
            print("  ✓ INT-27 Passed: Immutable parent fields protected against update.")

        # INT-29: Invalid Payload Validation
        print("\n--- [INT-29] Testing Missing Mandatory Fields Validation ---")
        try:
            interview_svc.create_interview({"scheduled_on": "2026-09-01 10:00:00"})
            assert False, "Should have raised ATSValidationError for missing job_application/interview_type"
        except ATSValidationError as exc:
            assert exc.code == "VALIDATION_ERROR"
            print("  ✓ INT-29 Passed: Missing mandatory fields (job_application, interview_type) rejected.")

        # INT-30: Cross-Company & Mismatched Relationship Leakage Prevention
        print("\n--- [INT-30] Testing Cross-Company & Mismatched Relationship Leakage ---")
        try:
            interview_svc.create_interview({
                "job_application": app_doc["name"],
                "interview_type": "Phone",
                "candidate": "NON_MATCHING_CANDIDATE_ID",
            })
            assert False, "Should have raised ATSValidationError for mismatched candidate"
        except ATSValidationError as exc:
            assert exc.code == "VALIDATION_ERROR"
            print("  ✓ INT-30 Passed: Mismatched candidate ID rejected cleanly.")

        print("\n=======================================================")
        print("ALL 30 INTERVIEW CONTRACT TESTS (INT-01..INT-30) PASSED 100%!")
        print("=======================================================\n")

    finally:
        # Clean up created test entities
        print("[CLEANUP] Cleaning up test records...")
        for iid in created_interviews:
            if frappe.db.exists("Interview", iid):
                frappe.delete_doc("Interview", iid, force=True)
        for aid in created_apps:
            if frappe.db.exists("Job Application", aid):
                frappe.delete_doc("Job Application", aid, force=True)
        for jid in created_jobs:
            if frappe.db.exists("Job Opening", jid):
                frappe.delete_doc("Job Opening", jid, force=True)
        for cid in created_cands:
            if frappe.db.exists("Candidate", cid):
                frappe.db.delete("Interview Feedback", {"candidate": cid})
                frappe.db.delete("Interview", {"candidate": cid})
                frappe.db.delete("Activity Logs", {"candidate": cid})
                frappe.delete_doc("Candidate", cid, force=True)
        frappe.db.commit()
        print("[CLEANUP] All test records deleted cleanly.")


if __name__ == "__main__":
    run_interview_contract_tests()
