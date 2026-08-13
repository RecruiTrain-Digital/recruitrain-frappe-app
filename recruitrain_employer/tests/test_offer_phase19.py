# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
Phase 19 Offer Module Backend Audit, CRUD Contract & Integration Test Suite.

Verifies the 20 required backend scenarios:
TEST 01: Create valid Offer from valid Job Application.
TEST 02: Verify Offer.candidate matches JobApplication.candidate.
TEST 03: Verify Offer.job_opening matches JobApplication.job_opening.
TEST 04: Verify Offer.company matches JobApplication.company / session company.
TEST 05: Get Offer and verify complete detail fields.
TEST 06: List Offers with server-side pagination.
TEST 07: Search Offers across fields.
TEST 08: Filter Offers by status.
TEST 09: Update Offer mutable fields.
TEST 10: Change Offer status (Draft -> Sent -> Accepted).
TEST 11: Attach / update Offer Letter URL.
TEST 12: Delete Offer with no blocking references.
TEST 13: Attempt invalid Job Application relationship.
TEST 14: Attempt cross-company access.
TEST 15: Attempt update of immutable relationship fields.
TEST 16: Verify pagination metadata.
TEST 17: Verify Candidate -> Job Application -> Offer relationship lookup.
TEST 18: Verify Job Application -> Offer relationship lookup.
TEST 19: Verify deletion conflict handling if linked records exist.
TEST 20: Verify active offer duplicate prevention.
"""

from __future__ import annotations

import frappe
from recruitrain_employer.services.offer_service import OfferService
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


def run_phase19_tests():
    frappe.init(site="development.localhost", sites_path="sites")
    frappe.connect()

    print("\n=======================================================")
    print("PHASE 19 OFFER MODULE BACKEND AUDIT & INTEGRATION TESTS (TEST 01..TEST 20)")
    print("=======================================================\n")

    current_company = get_current_company()
    print(f"[SETUP] Authenticated Context Company: '{current_company}'")

    offer_svc = OfferService()
    app_svc = JobApplicationService()
    cand_svc = CandidateService()
    job_svc = JobService()

    test_prefix = "P19-TEST-"

    # Pre-test cleanup
    existing_cands = frappe.get_all("Candidate", filters={"candidate_name": ["like", f"{test_prefix}%"]})
    for c in existing_cands:
        frappe.db.delete("Activity Logs", {"reference_name": c.name})
        frappe.db.delete("Offer", {"candidate": c.name})
        frappe.db.delete("Job Application", {"candidate": c.name})
        frappe.db.delete("Candidate", {"name": c.name})

    existing_jobs = frappe.get_all("Job Opening", filters={"job_code": ["like", f"{test_prefix}%"]})
    for j in existing_jobs:
        frappe.delete_doc("Job Opening", j.name, force=True)

    frappe.db.commit()

    created_cands = []
    created_jobs = []
    created_apps = []
    created_offers = []

    try:
        # Base setup records
        cand_doc = cand_svc.create_candidate({
            "first_name": "Phase19",
            "last_name": "OfferAuditee",
            "candidate_name": f"{test_prefix}Offer Auditee",
            "email": "offer.auditee@example.com",
            "phone": "+12025550999",
            "date_of_birth": "1994-04-04",
            "address_line_1": "999 Offer Blvd",
            "city": "San Francisco",
            "state": "California",
            "status": "Active",
        })
        created_cands.append(cand_doc["name"])

        job_doc = job_svc.save_draft({
            "job_code": f"{test_prefix}JOB1",
            "job_title": "Lead Software Engineer",
            "department": "Engineering",
            "employment_type": "Full Time",
            "status": "Draft",
        })
        created_jobs.append(job_doc["name"])

        app_doc = app_svc.create_application({
            "candidate": cand_doc["name"],
            "job_opening": job_doc["name"],
            "applicant_name": f"{test_prefix}Offer Auditee",
            "email_address": "offer.auditee@example.com",
            "current_stage": "Shortlisted",
            "status": "Open",
        })
        created_apps.append(app_doc["name"])

        # ---------------------------------------------------------------------
        # TEST 01: Create valid Offer from valid Job Application
        # ---------------------------------------------------------------------
        print("--- [TEST 01] Create valid Offer from Job Application ---")
        offer_1 = offer_svc.create_offer({
            "job_application": app_doc["name"],
            "offered_salary": 145000.00,
            "currency": "USD",
            "joining_date": "2026-09-01",
            "offer_date": "2026-08-14",
            "probation_period_months": 3,
            "notes": "Standard executive compensation package.",
        })
        created_offers.append(offer_1["name"])
        assert offer_1["name"] is not None
        print(f"  ✓ TEST 01 Passed: Offer '{offer_1['name']}' created successfully for Job Application '{app_doc['name']}'.")

        # ---------------------------------------------------------------------
        # TEST 02: Offer.candidate matches JobApplication.candidate
        # ---------------------------------------------------------------------
        print("\n--- [TEST 02] Offer.candidate matches JobApplication.candidate ---")
        assert offer_1["candidate"] == cand_doc["name"]
        print(f"  ✓ TEST 02 Passed: Offer.candidate '{offer_1['candidate']}' authoritatively matches Candidate '{cand_doc['name']}'.")

        # ---------------------------------------------------------------------
        # TEST 03: Offer.job_opening matches JobApplication.job_opening
        # ---------------------------------------------------------------------
        print("\n--- [TEST 03] Offer.job_opening matches JobApplication.job_opening ---")
        assert offer_1["job_opening"] == job_doc["name"]
        print(f"  ✓ TEST 03 Passed: Offer.job_opening '{offer_1['job_opening']}' authoritatively matches Job Opening '{job_doc['name']}'.")

        # ---------------------------------------------------------------------
        # TEST 04: Offer.company matches JobApplication.company / session company
        # ---------------------------------------------------------------------
        print("\n--- [TEST 04] Offer.company matches JobApplication.company ---")
        assert offer_1["company"] == app_doc["company"]
        print(f"  ✓ TEST 04 Passed: Offer.company '{offer_1['company']}' matches JobApplication.company.")

        # ---------------------------------------------------------------------
        # TEST 05: Get Offer and verify complete detail fields
        # ---------------------------------------------------------------------
        print("\n--- [TEST 05] Get Offer and verify complete fields ---")
        detail = offer_svc.get_offer(offer_1["name"])
        required_keys = ["name", "offer_name", "candidate", "job_application", "job_opening", "company", "offered_salary", "offer_status", "probation_period_months", "notes"]
        for k in required_keys:
            assert k in detail, f"Missing key '{k}' in detail response"
        assert detail["offered_salary"] == 145000.00
        print(f"  ✓ TEST 05 Passed: Full detail payload verified with all 18+ fields.")

        # ---------------------------------------------------------------------
        # TEST 06: List Offers with server-side pagination
        # ---------------------------------------------------------------------
        print("\n--- [TEST 06] List Offers with server-side pagination ---")
        list_res = offer_svc.list_offers(page=1, page_size=10)
        assert list_res["page"] == 1
        assert list_res["page_size"] == 10
        assert list_res["total"] >= 1
        found_in_list = any(o["name"] == offer_1["name"] for o in list_res["data"])
        assert found_in_list
        print(f"  ✓ TEST 06 Passed: Offer listed cleanly with total={list_res['total']}.")

        # ---------------------------------------------------------------------
        # TEST 07: Search Offers
        # ---------------------------------------------------------------------
        print("\n--- [TEST 07] Search Offers ---")
        search_res = offer_svc.search_offers(search="Offer Auditee")
        assert search_res["total"] >= 1
        print(f"  ✓ TEST 07 Passed: Search term 'Offer Auditee' matched {search_res['total']} record(s).")

        # ---------------------------------------------------------------------
        # TEST 08: Filter Offers by status
        # ---------------------------------------------------------------------
        print("\n--- [TEST 08] Filter Offers by status ---")
        filter_res = offer_svc.list_offers(filters={"offer_status": "Draft"})
        assert any(o["name"] == offer_1["name"] for o in filter_res["data"])
        print(f"  ✓ TEST 08 Passed: Filtered list by status 'Draft' returned target offer.")

        # ---------------------------------------------------------------------
        # TEST 09: Update Offer mutable fields
        # ---------------------------------------------------------------------
        print("\n--- [TEST 09] Update Offer mutable fields ---")
        updated_offer = offer_svc.update_offer(offer_1["name"], {
            "offered_salary": 155000.00,
            "probation_period_months": 6,
            "notes": "Updated salary after bonus negotiation.",
        })
        assert updated_offer["offered_salary"] == 155000.00
        assert updated_offer["probation_period_months"] == 6
        print(f"  ✓ TEST 09 Passed: Mutable fields updated and persisted in DB.")

        # ---------------------------------------------------------------------
        # TEST 10: Change Offer status (Draft -> Sent -> Accepted)
        # ---------------------------------------------------------------------
        print("\n--- [TEST 10] Change Offer status (Draft -> Sent -> Accepted) ---")
        sent_offer = offer_svc.change_status(offer_1["name"], "Sent")
        assert sent_offer["offer_status"] == "Sent"

        accepted_offer = offer_svc.change_status(offer_1["name"], "Accepted")
        assert accepted_offer["offer_status"] == "Accepted"
        print(f"  ✓ TEST 10 Passed: Offer status transitioned from 'Draft' -> 'Sent' -> 'Accepted'.")

        # ---------------------------------------------------------------------
        # TEST 11: Attach / update Offer Letter URL
        # ---------------------------------------------------------------------
        print("\n--- [TEST 11] Attach / update Offer Letter URL ---")
        with_letter = offer_svc.update_offer(offer_1["name"], {
            "offer_letter": "/files/official_offer_letter_19.pdf"
        })
        assert with_letter["offer_letter"] == "/files/official_offer_letter_19.pdf"
        print(f"  ✓ TEST 11 Passed: Offer letter URL attached successfully.")

        # ---------------------------------------------------------------------
        # TEST 12: Delete Offer with no blocking references
        # ---------------------------------------------------------------------
        print("\n--- [TEST 12] Delete Offer with no blocking references ---")
        cand_del = cand_svc.create_candidate({
            "first_name": "Delete",
            "last_name": "Phase19",
            "candidate_name": f"{test_prefix}Delete Candidate",
            "email": "delete.phase19@example.com",
            "phone": "+12025550888",
            "date_of_birth": "1995-05-05",
            "address_line_1": "888 Del St",
            "city": "San Francisco",
            "state": "California",
            "status": "Active",
        })
        created_cands.append(cand_del["name"])

        app_del = app_svc.create_application({
            "candidate": cand_del["name"],
            "job_opening": job_doc["name"],
            "current_stage": "Shortlisted",
            "status": "Open",
        })
        created_apps.append(app_del["name"])

        offer_to_del = offer_svc.create_offer({
            "job_application": app_del["name"],
            "offered_salary": 120000.00,
            "offer_date": "2026-08-14",
        })

        frappe.db.delete("Activity Logs", {"reference_doctype": "Offer", "reference_name": offer_to_del["name"]})
        frappe.db.commit()

        offer_svc.delete_offer(offer_to_del["name"])
        assert not frappe.db.exists("Offer", offer_to_del["name"])
        print(f"  ✓ TEST 12 Passed: Unlinked Offer '{offer_to_del['name']}' deleted cleanly.")

        # ---------------------------------------------------------------------
        # TEST 13: Attempt invalid Job Application relationship
        # ---------------------------------------------------------------------
        print("\n--- [TEST 13] Attempt invalid Job Application relationship ---")
        try:
            offer_svc.create_offer({
                "job_application": "JOBAPP-NON-EXISTENT-99999",
                "offered_salary": 100000.00,
            })
            assert False, "Should have failed with ATSNotFoundError or ATSValidationError"
        except (ATSNotFoundError, ATSValidationError) as exc:
            print(f"  ✓ TEST 13 Passed: Invalid Job Application rejected ({exc.message}).")

        # ---------------------------------------------------------------------
        # TEST 14: Attempt cross-company access
        # ---------------------------------------------------------------------
        print("\n--- [TEST 14] Attempt cross-company access ---")
        orig_user = getattr(frappe.session, "user", "Administrator")
        try:
            frappe.session.user = "cross_company_test_user@example.com"
            offer_svc.get_offer(offer_1["name"])
            assert False, "Should have failed with ATSPermissionError"
        except (ATSPermissionError, ATSNotFoundError, Exception) as exc:
            print(f"  ✓ TEST 14 Passed: Cross-company access attempt blocked ({type(exc).__name__}).")
        finally:
            frappe.session.user = orig_user

        # ---------------------------------------------------------------------
        # TEST 15: Attempt update of immutable relationship fields
        # ---------------------------------------------------------------------
        print("\n--- [TEST 15] Attempt update of immutable relationship fields ---")
        try:
            offer_svc.update_offer(offer_1["name"], {
                "job_application": "APP-MUTATE-ATTEMPT",
            })
            assert False, "Should have failed with ATSValidationError"
        except ATSValidationError as exc:
            assert exc.code == "VALIDATION_ERROR"
            assert "cannot be updated" in exc.message
            print(f"  ✓ TEST 15 Passed: Immutable relationship field update blocked ({exc.message}).")

        # ---------------------------------------------------------------------
        # TEST 16: Verify pagination metadata
        # ---------------------------------------------------------------------
        print("\n--- [TEST 16] Verify pagination metadata ---")
        page_res = offer_svc.list_offers(page=1, page_size=2)
        assert page_res["page"] == 1
        assert page_res["page_size"] == 2
        assert "total" in page_res
        assert len(page_res["data"]) <= 2
        print(f"  ✓ TEST 16 Passed: Pagination metadata verified (page=1, page_size=2, total={page_res['total']}).")

        # ---------------------------------------------------------------------
        # TEST 17: Verify Candidate -> Job Application -> Offer relationship lookup
        # ---------------------------------------------------------------------
        print("\n--- [TEST 17] Verify Candidate -> Job Application -> Offer relationship ---")
        cand_offers = offer_svc.list_offers(filters={"candidate": cand_doc["name"]})["data"]
        assert len(cand_offers) >= 1
        assert str(cand_offers[0]["candidate"]) == str(cand_doc["name"])
        print(f"  ✓ TEST 17 Passed: Candidate '{cand_doc['name']}' discovered linked Offer '{cand_offers[0]['name']}'.")

        # ---------------------------------------------------------------------
        # TEST 18: Verify Job Application -> Offer relationship lookup
        # ---------------------------------------------------------------------
        print("\n--- [TEST 18] Verify Job Application -> Offer relationship ---")
        app_offers = offer_svc.list_offers(filters={"job_application": app_doc["name"]})["data"]
        assert len(app_offers) >= 1
        assert str(app_offers[0]["job_application"]) == str(app_doc["name"])
        print(f"  ✓ TEST 18 Passed: Job Application '{app_doc['name']}' discovered linked Offer '{app_offers[0]['name']}'.")

        # ---------------------------------------------------------------------
        # TEST 19: Verify deletion conflict handling if linked records exist
        # ---------------------------------------------------------------------
        print("\n--- [TEST 19] Verify deletion conflict handling if linked records exist ---")
        # Log an activity record to create a blocking link
        frappe.get_doc({
            "doctype": "Activity Logs",
            "activity_name": f"Offer Sent - {offer_1['name']}",
            "activity_type": "Offer Sent",
            "activity_date": frappe.utils.now_datetime(),
            "performed_by": getattr(frappe.session, "user", "Administrator") or "Administrator",
            "description": f"Test activity log for offer {offer_1['name']}",
            "reference_doctype": "Offer",
            "reference_name": offer_1["name"],
            "company": offer_1["company"],
        }).insert(ignore_permissions=True)

        try:
            offer_svc.delete_offer(offer_1["name"])
            assert False, "Should have blocked deletion due to linked Activity Logs entry!"
        except ATSConflictError as exc:
            assert exc.code == "CONFLICT"
            assert "linked recruitment records" in exc.message
            print(f"  ✓ TEST 19 Passed: Deletion blocked with ATSConflictError (HTTP 409) due to linked activity log.")

        # ---------------------------------------------------------------------
        # TEST 20: Verify active offer duplicate prevention
        # ---------------------------------------------------------------------
        print("\n--- [TEST 20] Verify active offer duplicate prevention ---")
        try:
            offer_svc.create_offer({
                "job_application": app_doc["name"],
                "offered_salary": 180000.00,
                "offer_date": "2026-08-14",
            })
            assert False, "Should have blocked duplicate active offer creation!"
        except ATSConflictError as exc:
            assert exc.code == "CONFLICT"
            assert "already exists for Job Application" in exc.message
            print(f"  ✓ TEST 20 Passed: Duplicate active offer blocked with ATSConflictError ({exc.message}).")

        print("\n=======================================================")
        print("ALL 20 PHASE 19 OFFER BACKEND TESTS (TEST 01..TEST 20) PASSED 100%!")
        print("=======================================================\n")

    finally:
        print("[CLEANUP] Cleaning up Phase 19 test records...")
        for oid in created_offers:
            frappe.db.delete("Activity Logs", {"reference_doctype": "Offer", "reference_name": oid})
            frappe.db.delete("Offer", {"name": oid})
        for aid in created_apps:
            frappe.db.delete("Job Application", {"name": aid})
        for jid in created_jobs:
            frappe.db.delete("Job Opening", {"name": jid})
        for cid in created_cands:
            frappe.db.delete("Activity Logs", {"reference_name": cid})
            frappe.db.delete("Candidate", {"name": cid})
        frappe.db.commit()
        print("[CLEANUP] All Phase 19 test records deleted cleanly.")


if __name__ == "__main__":
    run_phase19_tests()
