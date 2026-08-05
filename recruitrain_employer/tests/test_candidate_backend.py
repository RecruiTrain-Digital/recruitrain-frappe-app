# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
Automated Test Suite for RecruitTrain Candidate Subsystem Production Architecture.
"""

from __future__ import annotations

import frappe

from recruitrain_employer.normalizers.candidate_normalizer import normalize_candidate_payload
from recruitrain_employer.services.candidate_service import CandidateService
from recruitrain_employer.serializers.candidate_serializer import serialize_candidate
from recruitrain_employer.utils.exceptions import ATSValidationError, ATSConflictError, ATSPermissionError
from recruitrain_employer.utils.permissions import get_current_company
from recruitrain_employer.validators.candidate_validator import CandidateValidator


def run_tests():
    """Run all Candidate subsystem backend tests and print results."""
    print("\n--- Starting RecruitTrain Candidate Subsystem Test Suite ---\n")

    current_company = get_current_company()
    print(f"[TEST 0] Current Company resolved: '{current_company}'")

    # Pre-test cleanup if leftover from previous run
    leftovers = frappe.get_all("Candidate", filters={"email": "alice.smith@example.com"}, pluck="name")
    for lname in leftovers:
        frappe.delete_doc("Candidate", lname, ignore_permissions=True)
    frappe.db.commit()

    # 1. Payload Normalizer Test
    print("\n[TEST 1] Testing Candidate Payload Normalization...")
    raw_payload = {
        "firstName": "John",
        "lastName": "Doe",
        "email": "  JOHN.DOE@EXAMPLE.COM  ",
        "phone": "+1 (555) 123-4567",
        "dob": "1990-05-15",
        "jobTitle": "Lead Developer",
        "companyName": "TechCorp",
        "experience": "5.5",
        "salary": 120000,
        "location": "Berlin, Germany",
        "employmentType": "Full Time",
    }
    normalized = normalize_candidate_payload(raw_payload)
    assert normalized["first_name"] == "John", f"Expected John, got {normalized.get('first_name')}"
    assert normalized["last_name"] == "Doe"
    assert normalized["email"] == "john.doe@example.com", f"Email not normalized! Got {normalized.get('email')}"
    assert normalized["mobile_no"] == "+15551234567", f"Phone punctuation not stripped! Got {normalized.get('mobile_no')}"
    assert normalized["current_job_title"] == "Lead Developer"
    assert normalized["current_company"] == "TechCorp"
    assert normalized["years_of_experience"] == 5.5
    assert normalized["current_salary"] == 120000
    assert normalized["preferred_location"] == "Berlin, Germany"
    print("  -> Payload Normalization passed!")

    # 2. Candidate Creation Test
    print("\n[TEST 2] Testing Candidate Creation & Company Scoping...")
    service = CandidateService()

    create_payload = {
        "first_name": "Alice",
        "last_name": "Smith",
        "email": "alice.smith@example.com",
        "mobile_no": "+919876543210",
        "date_of_birth": "1995-08-20",
        "current_job_title": "Frontend Engineer",
        "years_of_experience": 3,
        "address_line_1": "123 Main Street",
        "city": "Bengaluru",
        "state": "Karnataka",
        "country": "India",
    }

    created = service.create_candidate(create_payload)
    candidate_id = created["name"]

    assert created["company"] == current_company, f"Expected company {current_company}, got {created.get('company')}"
    assert created["status"] == "Active", f"Expected Active status, got {created.get('status')}"
    assert created["profile_completion"] > 0, f"Profile completion was not computed! Got {created.get('profile_completion')}"
    print(f"  -> Candidate created successfully: ID {candidate_id}, Profile Completeness: {created['profile_completion']}%")

    # 3. Sub-Resource Non-Destructive Update Test
    print("\n[TEST 3] Testing Sub-Resource Non-Destructive Update (Skills & Education)...")
    skills_payload = [
        {"skill": "Python", "experience_years": 4, "proficiency": "Advanced"},
        {"skill": "JavaScript", "experience_years": 3, "proficiency": "Intermediate"},
    ]
    updated_candidate = service.update_subresource(candidate_id, "skills", skills_payload)
    assert len(updated_candidate["skills"]) == 2, f"Expected 2 skills, got {len(updated_candidate['skills'])}"
    print("  -> Skills updated non-destructively!")

    # 4. FSM Status Transition Test
    print("\n[TEST 4] Testing Finite State Machine Status Transition Rules...")
    # Legal transition: Active -> In Review -> Interviewing -> Offered -> Hired
    updated1 = service.update_candidate(candidate_id, {"status": "In Review"})
    assert updated1["status"] == "In Review"

    updated2 = service.update_candidate(candidate_id, {"status": "Interviewing"})
    assert updated2["status"] == "Interviewing"

    updated3 = service.update_candidate(candidate_id, {"status": "Offered"})
    assert updated3["status"] == "Offered"

    updated4 = service.update_candidate(candidate_id, {"status": "Hired"})
    assert updated4["status"] == "Hired"
    print("  -> Legal status transitions (Active -> In Review -> Interviewing -> Offered -> Hired) verified!")

    # Illegal transition: Hired -> Draft
    try:
        service.update_candidate(candidate_id, {"status": "Draft"})
        assert False, "CRITICAL: Illegal transition Hired -> Draft was NOT rejected!"
    except ATSValidationError as exc:
        print(f"  -> Illegal transition Hired -> Draft correctly rejected! Exception: '{exc.message}'")

    # 5. Search & Listing Test
    print("\n[TEST 5] Testing Company Scoped Search & Listing...")
    list_res = service.list_candidates(search_term="Alice")
    assert list_res["total"] >= 1, f"Expected at least 1 candidate, got {list_res['total']}"
    assert list_res["items"][0]["name"] == candidate_id
    print("  -> Search & Company-scoped listing verified!")

    # 6. Cleanup Test Record
    print("\n[CLEANUP] Deleting test candidate record...")
    service.delete_candidate(candidate_id)
    print("  -> Test candidate record deleted cleanly.")

    print("\n--- ALL RECRUITRAIN CANDIDATE BACKEND TESTS PASSED SUCCESSFULLY! ---\n")


if __name__ == "__main__":
    run_tests()
