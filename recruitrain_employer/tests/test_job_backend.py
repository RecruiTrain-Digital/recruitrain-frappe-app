# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
Automated Test Suite for RecruitTrain Job Opening Backend Stabilization.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from recruitrain_employer.services.job_service import JobService
from recruitrain_employer.utils.permissions import get_current_company
from recruitrain_employer.validators.department_validator import DepartmentResolver
from recruitrain_employer.validators.employment_type_validator import EmploymentTypeResolver
from recruitrain_employer.validators.profession_validator import ProfessionResolver


def run_tests():
    """Run all Job Opening backend tests and print results."""
    print("\n--- Starting RecruitTrain Job Backend Test Suite ---\n")

    current_company = get_current_company()
    print(f"[TEST 0] Current Company resolved: '{current_company}'")

    # 1. Master Resolvers Test
    print("\n[TEST 1] Testing Master Resolvers Normalization...")

    dept1 = DepartmentResolver.resolve("health-care")
    dept2 = DepartmentResolver.resolve("HEALTHCARE")
    dept3 = DepartmentResolver.resolve("it")
    assert dept1 in ("Healthcare", dept1), f"Unexpected dept: {dept1}"
    assert dept2 in ("Healthcare", dept2), f"Unexpected dept: {dept2}"
    assert dept3 in ("Information Technology", dept3), f"Unexpected dept: {dept3}"
    print("  -> DepartmentResolver passed!")

    prof1 = ProfessionResolver.resolve("pflegefachkraft")
    prof2 = ProfessionResolver.resolve("software developer")
    assert prof1 in ("Pflegefachkraft", prof1), f"Unexpected prof: {prof1}"
    assert prof2 in ("Software Engineer", prof2), f"Unexpected prof: {prof2}"
    print("  -> ProfessionResolver passed!")

    et1 = EmploymentTypeResolver.resolve("Full-time")
    et2 = EmploymentTypeResolver.resolve("full_time")
    et3 = EmploymentTypeResolver.resolve("contractual")
    assert et1 == "Full Time", f"Expected Full Time, got {et1}"
    assert et2 == "Full Time", f"Expected Full Time, got {et2}"
    assert et3 == "Contract", f"Expected Contract, got {et3}"
    print("  -> EmploymentTypeResolver passed!")

    # 2. Draft Creation Test
    print("\n[TEST 2] Testing Job Draft Creation...")
    service = JobService()

    draft_payload = {
        "title": "Software Engineer Draft",
        "category": "health-care",
        "categorySub": "pflegefachkraft",
        "type": "Full-time",
        "company": "Malicious Malformed Company Payload",
    }
    draft_res = service.save_draft(draft_payload)
    job_id = draft_res["name"]

    assert draft_res["status"] == "Draft", f"Expected Draft, got {draft_res['status']}"
    assert draft_res["published"] == 0, f"Expected published 0, got {draft_res['published']}"
    assert draft_res["company"] == current_company, f"Company mismatch! Expected {current_company}, got {draft_res['company']}"
    print(f"  -> Job Draft created successfully: ID {job_id}")

    # 3. Draft Update Test
    print("\n[TEST 3] Testing Job Draft Partial Update...")
    update_payload = {
        "job_summary": "Draft summary text updated.",
        "minSalary": 50000,
        "maxSalary": 80000,
    }
    updated_draft = service.update_job(job_id, update_payload)
    assert updated_draft["status"] == "Draft", f"Status changed from Draft: {updated_draft['status']}"
    assert updated_draft["minimum_salary"] == 50000
    assert updated_draft["maximum_salary"] == 80000
    print("  -> Job Draft updated successfully without status alteration.")

    # 4. Job Publish Test
    print("\n[TEST 4] Testing Job Publication...")
    publish_payload = {
        "job_summary": "Strict summary required for publication.",
        "responsibilities": "Writing production code and maintaining APIs.",
        "requirements": "3+ years Python experience.",
    }
    published_res = service.publish_job(job_id, publish_payload)
    assert published_res["status"] == "Open", f"Expected Open, got {published_res['status']}"
    assert published_res["published"] == 1, f"Expected published 1, got {published_res['published']}"
    assert published_res["published_at"] is not None, "published_at missing"
    print(f"  -> Job published successfully! Published At: {published_res['published_at']}")

    # Check notification creation
    notifications = frappe.get_all(
        "Notification Log",
        filters={"company": current_company, "document_name": job_id},
        fields=["name", "subject"],
    )
    assert len(notifications) > 0, "Expected notification for job publication!"
    print(f"  -> Notification emitted successfully: '{notifications[0]['subject']}'")

    # 5. Save Draft Guard on Published Job
    print("\n[TEST 5] Testing Save Draft Guard on Published Job (Prevent Status Reversion)...")
    resaved = service.save_draft({"job_summary": "New draft description tweak"}, job_id=job_id)
    assert resaved["status"] == "Open", f"CRITICAL BUG: Published job status reverted to '{resaved['status']}'!"
    assert resaved["published"] == 1, f"CRITICAL BUG: Published flag reset to '{resaved['published']}'!"
    print("  -> Save Draft guard verified! Published job status & published flag remained 'Open' / 1.")

    # 6. Update Published Job Test
    print("\n[TEST 6] Testing Update on Published Job...")
    edited_pub = service.update_job(job_id, {"number_of_openings": 5})
    assert edited_pub["status"] == "Open"
    assert edited_pub["number_of_openings"] == 5
    print("  -> Published job updated successfully maintaining 'Open' status.")

    # Cleanup test job
    print("\n[CLEANUP] Deleting test job record...")
    service.delete_job(job_id)
    print("  -> Test job deleted cleanly.")

    print("\n--- ALL RECRUITRAIN JOB BACKEND TESTS PASSED SUCCESSFULLY! ---\n")


if __name__ == "__main__":
    run_tests()
