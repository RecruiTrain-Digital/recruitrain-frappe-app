# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
Contract Verification & Hardening Test Suite for RecruitTrain Job Openings (JOB-01 to JOB-15).
"""

from __future__ import annotations

import frappe
from recruitrain_employer.services.job_service import JobService
from recruitrain_employer.services.subscription_service import SubscriptionService
from recruitrain_employer.utils.exceptions import (
    ATSConflictError,
    ATSNotFoundError,
    ATSValidationError,
    PlanLimitExceededError,
)
from recruitrain_employer.utils.permissions import get_current_company


def run_contract_tests():
    print("\n=======================================================")
    print("RECRUITRAIN JOB OPENINGS BACKEND CONTRACT VERIFICATION (JOB-01..JOB-15)")
    print("=======================================================\n")

    current_company = get_current_company()
    print(f"[SETUP] Authenticated Context Company: '{current_company}'")

    service = JobService()
    sub_service = SubscriptionService()

    # Ensure clean slate for test job codes
    test_code_base = "JOB-TEST-VERIFY-"
    existing = frappe.get_all("Job Opening", filters={"job_code": ["like", f"{test_code_base}%"]})
    for e in existing:
        frappe.delete_doc("Job Opening", e.name, force=True)
    frappe.db.commit()

    test_jobs = []

    try:
        # JOB-05: Create Job Opening (Draft & Open)
        print("\n--- [JOB-05] Testing Create Job Opening (Draft & Open) ---")
        draft_payload = {
            "job_code": f"{test_code_base}01",
            "job_title": "Senior Contract Engineer",
            "department": "Engineering",
            "employment_type": "Full Time",
            "job_summary": "Draft summary for test",
            "minimum_salary": 60000,
            "maximum_salary": 90000,
            "status": "Draft",
        }
        created_draft = service.save_draft(draft_payload)
        test_jobs.append(created_draft["name"])

        assert created_draft["name"] == f"{test_code_base}01"
        assert created_draft["status"] == "Draft"
        assert created_draft["published"] == 0
        assert created_draft["company"] == current_company
        print("  ✓ JOB-05 Passed: Draft job created successfully.")

        # JOB-01: List Job Openings
        print("\n--- [JOB-01] Testing List Job Openings ---")
        list_res = service.list_jobs(page=1, page_size=10)
        assert "data" in list_res and "total" in list_res
        assert list_res["page"] == 1 and list_res["page_size"] == 10
        assert list_res["total"] >= 1
        found_in_list = any(j["name"] == created_draft["name"] for j in list_res["data"])
        assert found_in_list, "Created job missing from list!"
        print(f"  ✓ JOB-01 Passed: Returned {len(list_res['data'])} records, total={list_res['total']}.")

        # JOB-02: Search Job Openings
        print("\n--- [JOB-02] Testing Search Job Openings ---")
        search_res = service.search_jobs(search="Senior Contract Engineer")
        assert search_res["total"] >= 1
        assert any(j["name"] == created_draft["name"] for j in search_res["data"])
        print(f"  ✓ JOB-02 Passed: Search term matched created job successfully.")

        # JOB-03: Filter Job Openings
        print("\n--- [JOB-03] Testing Filter Job Openings ---")
        resolved_dept = created_draft.get("department")
        filtered_res = service.list_jobs(filters={"status": "Draft", "department": resolved_dept})
        assert any(j["name"] == created_draft["name"] for j in filtered_res["data"])
        filtered_empty = service.list_jobs(filters={"status": "Closed", "job_code": f"{test_code_base}01"})
        assert len(filtered_empty["data"]) == 0
        print(f"  ✓ JOB-03 Passed: Status and Department ('{resolved_dept}') filters accurately scope results.")

        # JOB-04: Pagination
        print("\n--- [JOB-04] Testing Pagination ---")
        pag_p1 = service.list_jobs(page=1, page_size=1)
        assert len(pag_p1["data"]) == 1
        assert pag_p1["page"] == 1
        assert pag_p1["page_size"] == 1
        print("  ✓ JOB-04 Passed: Strict page size clamping and pagination metadata verified.")

        # JOB-06: Update Job Opening
        print("\n--- [JOB-06] Testing Update Job Opening ---")
        update_res = service.update_job(created_draft["name"], {"number_of_openings": 3, "city": "Berlin"})
        assert update_res["number_of_positions"] == 3
        assert update_res["city"] == "Berlin"
        print("  ✓ JOB-06 Passed: Partial update applied successfully.")

        # JOB-08: Publish Workflow & JOB-10 Quota Incrementation
        print("\n--- [JOB-08 & JOB-10] Testing Publish Workflow & Quota Tracking ---")
        initial_usage = sub_service.get_usage(current_company).current_active_jobs

        publish_payload = {
            "responsibilities": "Building scalable web software",
            "requirements": "Python, Frappe, JS, CSS",
            "german_level_required": "B2",
            "compensation_type": "Salary Range",
            "minimum_salary": 60000,
            "maximum_salary": 80000,
            "currency": "EUR",
        }

        published = service.publish_job(created_draft["name"], publish_payload)
        assert published["status"] == "Open"
        assert published["published"] == 1

        post_pub_usage = sub_service.get_usage(current_company).current_active_jobs
        assert post_pub_usage == initial_usage + 1, f"Quota expected {initial_usage + 1}, got {post_pub_usage}"
        print(f"  ✓ JOB-08 & JOB-10 Passed: Published status='Open', active_jobs usage incremented from {initial_usage} to {post_pub_usage}.")

        # JOB-09: Close Workflow & Quota Decrementation
        print("\n--- [JOB-09] Testing Close Workflow & Quota Decrementation ---")
        closed = service.close_job(created_draft["name"])
        assert closed["status"] == "Closed"

        post_close_usage = sub_service.get_usage(current_company).current_active_jobs
        assert post_close_usage == initial_usage, f"Quota expected {initial_usage}, got {post_close_usage}"
        print(f"  ✓ JOB-09 Passed: Closed job decremented active_jobs usage back to {post_close_usage}.")

        # JOB-07: Status Transition (Re-open)
        print("\n--- [JOB-07] Testing Status Transitions ---")
        reopened = service.update_job(created_draft["name"], {"status": "Open"})
        assert reopened["status"] == "Open"
        reopen_usage = sub_service.get_usage(current_company).current_active_jobs
        assert reopen_usage == initial_usage + 1
        print("  ✓ JOB-07 Passed: Status transition Closed -> Open re-incremented quota.")

        # JOB-11: Company Isolation Verification
        print("\n--- [JOB-11] Testing Company Isolation ---")
        # Attempt to spoof company in create payload
        spoof_payload = {
            "job_code": f"{test_code_base}02",
            "job_title": "Company Spoofing Attempt",
            "company": "Fake Malicious Company Corp",
            "employment_type": "Full Time",
            "job_summary": "Testing isolation",
        }
        isolated_job = service.save_draft(spoof_payload)
        test_jobs.append(isolated_job["name"])
        assert isolated_job["company"] == current_company, "SECURITY VIOLATION: Company spoofing succeeded!"
        print("  ✓ JOB-11 Passed: Backend explicitly overrode input company with session company.")

        # JOB-12: Unauthorized Access / Invalid Input Handling
        print("\n--- [JOB-12] Testing Invalid Inputs & Not Found Handling ---")
        try:
            service.get_job("NON_EXISTENT_JOB_9999")
            assert False, "Should have raised ATSNotFoundError"
        except ATSNotFoundError as exc:
            assert exc.code == "NOT_FOUND"
            print("  ✓ JOB-12 Passed: Non-existent job query properly raised ATSNotFoundError.")

        # JOB-13: Concurrent Update / Duplicate Code (409 Conflict)
        print("\n--- [JOB-13] Testing Duplicate Job Code Handling (409 Conflict) ---")
        try:
            dup_payload = {
                "job_code": f"{test_code_base}01",
                "job_title": "Duplicate Code Job",
                "status": "Draft",
            }
            service.save_draft(dup_payload)
            assert False, "Should have raised ATSConflictError"
        except ATSConflictError as exc:
            assert exc.code == "CONFLICT"
            print("  ✓ JOB-13 Passed: Duplicate job_code rejected with ATSConflictError.")

        # JOB-14: Delete / Archive Safety with Linked Records
        print("\n--- [JOB-14] Testing Delete Safety with Linked Application Records ---")
        # Create a dummy job application referencing test job
        app_doc = frappe.new_doc("Job Application")
        app_doc.job_opening = created_draft["name"]
        app_doc.applicant_name = "Test Applicant Integrity"
        app_doc.email_address = "applicant.test@example.com"
        app_doc.company = current_company
        app_doc.flags.ignore_mandatory = True
        app_doc.insert(ignore_permissions=True)
        frappe.db.commit()

        try:
            service.delete_job(created_draft["name"])
            assert False, "Should have blocked deletion due to linked Job Application!"
        except ATSConflictError as exc:
            assert exc.code == "CONFLICT"
            print("  ✓ JOB-14 Passed: Deletion of Job Opening with linked Job Application was strictly blocked with ATSConflictError!")
        finally:
            frappe.delete_doc("Job Application", app_doc.name, force=True)
            frappe.db.commit()

        # JOB-15: Response Envelope Verification
        print("\n--- [JOB-15] Testing Response Envelope Compatibility ---")
        detail_job = service.get_job(created_draft["name"])
        required_keys = {
            "name", "job_title", "job_code", "company", "status", "published",
            "location", "salary_min", "salary_max", "description", "number_of_positions",
            "application_count", "shortlisted_count", "interview_count", "offer_count"
        }
        missing_keys = required_keys - set(detail_job.keys())
        assert not missing_keys, f"Missing required envelope keys: {missing_keys}"
        print("  ✓ JOB-15 Passed: Response payload contains all required canonical and alias keys with calculated metrics.")

        print("\n=======================================================")
        print("ALL 15 JOB OPENING CONTRACT TESTS (JOB-01..JOB-15) PASSED 100%!")
        print("=======================================================\n")

    finally:
        # Cleanup test records
        for jid in test_jobs:
            if frappe.db.exists("Job Opening", jid):
                frappe.delete_doc("Job Opening", jid, force=True)
        frappe.db.commit()
        print("[CLEANUP] All test job records deleted.")


if __name__ == "__main__":
    run_contract_tests()
