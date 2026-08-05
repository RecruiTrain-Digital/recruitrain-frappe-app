# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
Automated Test Suite for Department-Profession Master Data Taxonomy & Validation.
"""

from __future__ import annotations

import frappe

from recruitrain_employer.api.master import list_departments, list_professions
from recruitrain_employer.services.job_service import JobService
from recruitrain_employer.utils.exceptions import ATSValidationError
from recruitrain_employer.validators.department_validator import DepartmentResolver
from recruitrain_employer.validators.profession_validator import ProfessionResolver


def run_tests():
    print("\n--- Starting Department-Profession Taxonomy Test Suite ---\n")

    # 1. API: list_departments
    print("[TEST 1] Testing list_departments API endpoint...")
    dept_res = list_departments()
    assert dept_res["success"] is True, f"API failed: {dept_res}"
    depts = dept_res["data"]
    assert len(depts) >= 16, f"Expected at least 16 canonical departments, got {len(depts)}"

    dept_display_names = [d["display_name"] for d in depts]
    for required_dept in [
        "Healthcare",
        "Information Technology",
        "Engineering",
        "Finance",
        "Human Resources",
        "Marketing",
        "Sales",
        "Customer Support",
        "Legal",
        "Operations",
        "Administration",
        "Manufacturing",
        "Logistics",
        "Procurement",
        "Quality Assurance",
        "Research & Development",
    ]:
        assert required_dept in dept_display_names, f"Missing canonical department display_name: {required_dept}"

    # Verify return dict keys: id, name, display_name
    assert "id" in depts[0] and "name" in depts[0] and "display_name" in depts[0]
    print("  -> list_departments API passed!")

    # 2. API: list_professions(department)
    print("\n[TEST 2] Testing list_professions API endpoint with Department filtering...")
    hc_res = list_professions(department="Healthcare")
    assert hc_res["success"] is True
    hc_profs = hc_res["data"]
    hc_prof_names = [p["name"] for p in hc_profs]

    assert "Nurse" in hc_prof_names, "Missing Nurse in Healthcare professions"
    assert "Doctor" in hc_prof_names, "Missing Doctor in Healthcare professions"
    assert "Pflegefachkraft" in hc_prof_names, "Missing Pflegefachkraft in Healthcare professions"

    # CRITICAL: Verify NO unrelated professions returned
    assert "Backend Developer" not in hc_prof_names, "CRITICAL ERROR: Unrelated profession 'Backend Developer' returned for Healthcare!"
    assert "Software Engineer" not in hc_prof_names, "CRITICAL ERROR: Unrelated profession 'Software Engineer' returned for Healthcare!"
    print(f"  -> Healthcare filtered list returned {len(hc_prof_names)} valid professions and zero unrelated professions.")

    it_res = list_professions(department="Information Technology")
    it_profs = it_res["data"]
    it_prof_names = [p["name"] for p in it_profs]
    assert "Software Engineer" in it_prof_names
    assert "Backend Developer" in it_prof_names
    assert "Nurse" not in it_prof_names, "Nurse returned under IT!"
    print(f"  -> Information Technology filtered list returned {len(it_prof_names)} valid professions.")

    # 3. Mismatched Department / Profession Validation Test
    print("\n[TEST 3] Testing Mismatched Department/Profession Validation Rejection...")
    service = JobService()

    mismatched_payload = {
        "title": "Mismatched Job Test",
        "department": "Healthcare",
        "profession": "Backend Developer",
        "employment_type": "Full Time",
    }

    failed = False
    try:
        service.save_draft(mismatched_payload)
    except ATSValidationError as exc:
        failed = True
        print(f"  -> Correctly rejected mismatched combination: {exc.message}")

    assert failed is True, "CRITICAL BUG: Mismatched combination (Healthcare + Backend Developer) was allowed to save!"

    # 4. Valid Department / Profession Validation Test
    print("\n[TEST 4] Testing Valid Department/Profession Combination...")
    valid_payload = {
        "title": "Valid Nurse Job Test",
        "category": "health-care",
        "categorySub": "registered nurse",
        "type": "Full-time",
    }

    valid_res = service.save_draft(valid_payload)
    job_id = valid_res["name"]

    assert valid_res["department"] in ("Healthcare", "Healthcare - RT"), f"Expected Healthcare, got {valid_res['department']}"
    assert valid_res["profession"] in ("Registered Nurse", "Nurse"), f"Unexpected profession: {valid_res['profession']}"
    print(f"  -> Valid job saved successfully with resolved Department '{valid_res['department']}' and Profession '{valid_res['profession']}'.")

    # Cleanup
    service.delete_job(job_id)
    print("  -> Test job cleaned up cleanly.")

    print("\n--- ALL DEPARTMENT-PROFESSION TAXONOMY TESTS PASSED SUCCESSFULLY! ---\n")


if __name__ == "__main__":
    run_tests()
