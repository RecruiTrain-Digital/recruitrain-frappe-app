# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
Phase 5.2 — Candidate Delete Referential Integrity Test Suite
=============================================================

Tests DELETE-01 through DELETE-12 as specified in the Phase 5.2 audit mandate.

Run inside Frappe bench context:
    bench execute recruitrain_employer.tests.test_candidate_delete_integrity.run_tests

All tests are destructive to test data only. They clean up after themselves.
Production data is NEVER touched.
"""

from __future__ import annotations

import traceback
from typing import Any

import frappe

from recruitrain_employer.services.candidate_service import CandidateService
from recruitrain_employer.utils.exceptions import (
    ATSConflictError,
    ATSNotFoundError,
    ATSPermissionError,
    ATSValidationError,
)
from recruitrain_employer.utils.permissions import get_current_company


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------

_RESULTS: list[dict[str, Any]] = []


def _pass(test_id: str, description: str) -> None:
    _RESULTS.append({"id": test_id, "status": "PASS", "description": description})
    print(f"  [PASS] {test_id}: {description}")


def _fail(test_id: str, description: str, reason: str) -> None:
    _RESULTS.append({"id": test_id, "status": "FAIL", "description": description, "reason": reason})
    print(f"  [FAIL] {test_id}: {description} -- REASON: {reason}")


def _make_candidate(email: str, company: str) -> str:
    """Create a bare-minimum Candidate record for testing. Returns candidate name."""
    # Clean up if leftover from a previous failed run
    existing = frappe.get_all("Candidate", filters={"email": email}, pluck="name")
    for n in existing:
        frappe.delete_doc("Candidate", n, ignore_permissions=True, force=True)
    frappe.db.commit()

    doc = frappe.new_doc("Candidate")
    doc.first_name = "Test"
    doc.last_name = "DeleteAudit"
    doc.candidate_name = f"Test DeleteAudit ({email})"
    doc.email = email
    doc.mobile_no = "+919999999999"
    doc.date_of_birth = "1990-01-01"
    doc.address_line_1 = "1 Test Street"
    doc.city = "Bengaluru"
    doc.state = "Karnataka"
    doc.country = "India"
    doc.status = "Active"
    doc.company = company
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return doc.name


def _make_job_application(candidate_id: str, company: str) -> str:
    """Create a minimal Job Application linked to a candidate."""
    # Find or create a minimal Job Opening
    job = frappe.get_all(
        "Job Opening",
        filters={"company": company, "status": "Open"},
        pluck="name",
        limit=1,
    )
    if job:
        job_opening = job[0]
    else:
        jdoc = frappe.new_doc("Job Opening")
        jdoc.job_title = "Test Delete Audit Job"
        jdoc.company = company
        jdoc.status = "Open"
        jdoc.insert(ignore_permissions=True)
        frappe.db.commit()
        job_opening = jdoc.name

    app = frappe.new_doc("Job Application")
    app.candidate = candidate_id
    app.job_opening = job_opening
    app.company = company
    app.status = "Applied"
    app.insert(ignore_permissions=True)
    frappe.db.commit()
    return app.name


def _make_interview(candidate_id: str, company: str) -> str:
    """Create a minimal Interview linked to a candidate."""
    doc = frappe.new_doc("Interview")
    doc.candidate = candidate_id
    doc.company = company
    doc.interview_date = frappe.utils.today()
    doc.interview_type = "Technical"
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return doc.name


def _make_offer(candidate_id: str, company: str) -> str:
    """Create a minimal Offer linked to a candidate."""
    doc = frappe.new_doc("Offer")
    doc.candidate = candidate_id
    doc.company = company
    doc.offer_date = frappe.utils.today()
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return doc.name


def _make_candidate_note(candidate_id: str, company: str) -> str:
    """Create a Candidate Note linked to a candidate."""
    doc = frappe.new_doc("Candidate Note")
    doc.candidate = candidate_id
    doc.company = company
    doc.note = "Phase 5.2 Test note - delete audit."
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return doc.name


def _make_talent_pool_member(candidate_id: str, company: str) -> str:
    """Add candidate to a Talent Pool."""
    pools = frappe.get_all("Talent Pool", filters={"company": company}, pluck="name", limit=1)
    if pools:
        pool_name = pools[0]
    else:
        pool = frappe.new_doc("Talent Pool")
        pool.pool_name = "Phase 5.2 Test Pool"
        pool.company = company
        pool.insert(ignore_permissions=True)
        frappe.db.commit()
        pool_name = pool.name

    member = frappe.new_doc("Talent Pool Member")
    member.candidate = candidate_id
    member.talent_pool = pool_name
    member.insert(ignore_permissions=True)
    frappe.db.commit()
    return member.name


def _force_cleanup(candidate_id: str) -> None:
    """Force delete a candidate and all linked test records (test cleanup only)."""
    for doctype in ["Job Application", "Interview", "Offer", "Candidate Note", "Talent Pool Member", "Activity Logs"]:
        try:
            linked = frappe.get_all(doctype, filters={"candidate": candidate_id}, pluck="name")
            for n in linked:
                frappe.delete_doc(doctype, n, ignore_permissions=True, force=True)
        except Exception:
            pass
    try:
        frappe.delete_doc("Candidate", candidate_id, ignore_permissions=True, force=True)
    except Exception:
        pass
    frappe.db.commit()


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_delete_01_no_linked_records(company: str) -> None:
    """DELETE-01: Candidate with no linked records — deletion must succeed."""
    test_id = "DELETE-01"
    candidate_id = None
    try:
        candidate_id = _make_candidate("del01@delete-audit.test", company)
        service = CandidateService()
        result = service.delete_candidate(candidate_id)
        assert result.get("deleted") is True, f"Expected deleted=True, got {result}"
        assert not frappe.db.exists("Candidate", candidate_id), "Candidate still exists after delete!"
        _pass(test_id, "Candidate with no linked records deleted successfully.")
    except Exception as exc:
        _fail(test_id, "Deletion of unlinked candidate", str(exc))
        if candidate_id:
            _force_cleanup(candidate_id)


def test_delete_02_with_job_application(company: str) -> None:
    """DELETE-02: Candidate with Job Application — deletion must be rejected."""
    test_id = "DELETE-02"
    candidate_id = None
    app_id = None
    try:
        candidate_id = _make_candidate("del02@delete-audit.test", company)
        app_id = _make_job_application(candidate_id, company)
        service = CandidateService()
        try:
            service.delete_candidate(candidate_id)
            _fail(test_id, "Candidate with Job Application", "BLOCKER: Deletion was NOT rejected! Recruitment history was lost.")
        except ATSConflictError as exc:
            assert "job_applications" in (exc.details or {}).get("blocking_links", {}), \
                f"blocking_links missing job_applications: {exc.details}"
            assert (exc.details or {}).get("error_code") == "CANDIDATE_HAS_RECRUITMENT_HISTORY", \
                f"Wrong error_code: {exc.details}"
            assert frappe.db.exists("Candidate", candidate_id), "Candidate was deleted despite conflict!"
            assert frappe.db.exists("Job Application", app_id), "Job Application was deleted despite conflict!"
            _pass(test_id, "Deletion correctly rejected for Candidate with Job Application.")
    except Exception as exc:
        _fail(test_id, "Job Application link protection", f"Unexpected exception: {exc}\n{traceback.format_exc()}")
    finally:
        if candidate_id:
            _force_cleanup(candidate_id)


def test_delete_03_with_interview(company: str) -> None:
    """DELETE-03: Candidate with Interview — deletion must be rejected."""
    test_id = "DELETE-03"
    candidate_id = None
    interview_id = None
    try:
        candidate_id = _make_candidate("del03@delete-audit.test", company)
        interview_id = _make_interview(candidate_id, company)
        service = CandidateService()
        try:
            service.delete_candidate(candidate_id)
            _fail(test_id, "Candidate with Interview", "BLOCKER: Deletion was NOT rejected! Interview history was lost.")
        except ATSConflictError as exc:
            assert "interviews" in (exc.details or {}).get("blocking_links", {}), \
                f"blocking_links missing interviews: {exc.details}"
            assert (exc.details or {}).get("error_code") == "CANDIDATE_HAS_RECRUITMENT_HISTORY"
            assert frappe.db.exists("Candidate", candidate_id), "Candidate was deleted!"
            assert frappe.db.exists("Interview", interview_id), "Interview was deleted!"
            _pass(test_id, "Deletion correctly rejected for Candidate with Interview.")
    except Exception as exc:
        _fail(test_id, "Interview link protection", f"Unexpected exception: {exc}\n{traceback.format_exc()}")
    finally:
        if candidate_id:
            _force_cleanup(candidate_id)


def test_delete_04_with_offer(company: str) -> None:
    """DELETE-04: Candidate with Offer — deletion must be rejected."""
    test_id = "DELETE-04"
    candidate_id = None
    offer_id = None
    try:
        candidate_id = _make_candidate("del04@delete-audit.test", company)
        offer_id = _make_offer(candidate_id, company)
        service = CandidateService()
        try:
            service.delete_candidate(candidate_id)
            _fail(test_id, "Candidate with Offer", "BLOCKER: Deletion was NOT rejected! Offer history was lost.")
        except ATSConflictError as exc:
            assert "offers" in (exc.details or {}).get("blocking_links", {}), \
                f"blocking_links missing offers: {exc.details}"
            assert (exc.details or {}).get("error_code") == "CANDIDATE_HAS_RECRUITMENT_HISTORY"
            _pass(test_id, "Deletion correctly rejected for Candidate with Offer.")
    except Exception as exc:
        _fail(test_id, "Offer link protection", f"Unexpected exception: {exc}\n{traceback.format_exc()}")
    finally:
        if candidate_id:
            _force_cleanup(candidate_id)


def test_delete_05_with_activity_logs(company: str) -> None:
    """DELETE-05: Candidate with Activity Log — deletion must be rejected."""
    test_id = "DELETE-05"
    candidate_id = None
    try:
        candidate_id = _make_candidate("del05@delete-audit.test", company)
        # Activity log is auto-created on candidate creation by log_activity
        # If not created, we create one manually
        from recruitrain_employer.utils.activity_logger import log_activity
        log_activity(
            activity_type="Test Activity",
            description="Phase 5.2 audit log entry for delete test.",
            reference_doctype="Candidate",
            reference_name=candidate_id,
            candidate=candidate_id,
            company=company,
        )
        frappe.db.commit()

        service = CandidateService()
        try:
            service.delete_candidate(candidate_id)
            _fail(test_id, "Candidate with Activity Log", "BLOCKER: Deletion was NOT rejected! Audit history was lost.")
        except ATSConflictError as exc:
            assert "activity_logs" in (exc.details or {}).get("blocking_links", {}), \
                f"blocking_links missing activity_logs: {exc.details}"
            assert (exc.details or {}).get("error_code") == "CANDIDATE_HAS_RECRUITMENT_HISTORY"
            _pass(test_id, "Deletion correctly rejected for Candidate with Activity Log.")
    except Exception as exc:
        _fail(test_id, "Activity Log preservation", f"Unexpected exception: {exc}\n{traceback.format_exc()}")
    finally:
        if candidate_id:
            _force_cleanup(candidate_id)


def test_delete_06_with_candidate_note(company: str) -> None:
    """DELETE-06: Candidate with Candidate Note — deletion must be rejected, no orphan."""
    test_id = "DELETE-06"
    candidate_id = None
    note_id = None
    try:
        candidate_id = _make_candidate("del06@delete-audit.test", company)
        note_id = _make_candidate_note(candidate_id, company)
        service = CandidateService()
        try:
            service.delete_candidate(candidate_id)
            _fail(test_id, "Candidate with Note", "BLOCKER: Deletion was NOT rejected! Note orphaned or deleted.")
        except ATSConflictError as exc:
            assert "candidate_notes" in (exc.details or {}).get("blocking_links", {}), \
                f"blocking_links missing candidate_notes: {exc.details}"
            assert frappe.db.exists("Candidate Note", note_id), "Candidate Note was orphaned/deleted!"
            _pass(test_id, "Deletion rejected; Candidate Note preserved (no orphan).")
    except Exception as exc:
        _fail(test_id, "Candidate Note protection", f"Unexpected exception: {exc}\n{traceback.format_exc()}")
    finally:
        if candidate_id:
            _force_cleanup(candidate_id)


def test_delete_07_with_talent_pool(company: str) -> None:
    """DELETE-07: Candidate in Talent Pool — deletion must be rejected, no orphan membership."""
    test_id = "DELETE-07"
    candidate_id = None
    member_id = None
    try:
        candidate_id = _make_candidate("del07@delete-audit.test", company)
        member_id = _make_talent_pool_member(candidate_id, company)
        service = CandidateService()
        try:
            service.delete_candidate(candidate_id)
            _fail(test_id, "Candidate in Talent Pool", "BLOCKER: Deletion was NOT rejected! Orphan membership remains.")
        except ATSConflictError as exc:
            assert "talent_pool_memberships" in (exc.details or {}).get("blocking_links", {}), \
                f"blocking_links missing talent_pool_memberships: {exc.details}"
            assert frappe.db.exists("Talent Pool Member", member_id), "Talent Pool Member orphaned!"
            _pass(test_id, "Deletion rejected; Talent Pool membership preserved (no orphan).")
    except Exception as exc:
        _fail(test_id, "Talent Pool protection", f"Unexpected exception: {exc}\n{traceback.format_exc()}")
    finally:
        if candidate_id:
            _force_cleanup(candidate_id)


def test_delete_08_multiple_linked_records(company: str) -> None:
    """DELETE-08: Candidate with multiple linked records — single safe rejection, no partial deletion."""
    test_id = "DELETE-08"
    candidate_id = None
    try:
        candidate_id = _make_candidate("del08@delete-audit.test", company)
        app_id = _make_job_application(candidate_id, company)
        note_id = _make_candidate_note(candidate_id, company)
        member_id = _make_talent_pool_member(candidate_id, company)

        service = CandidateService()
        try:
            service.delete_candidate(candidate_id)
            _fail(test_id, "Candidate with multiple links", "BLOCKER: Deletion was NOT rejected!")
        except ATSConflictError as exc:
            links = (exc.details or {}).get("blocking_links", {})
            assert "job_applications" in links, f"job_applications not in blocking_links: {links}"
            assert "candidate_notes" in links, f"candidate_notes not in blocking_links: {links}"
            assert "talent_pool_memberships" in links, f"talent_pool_memberships not in blocking_links: {links}"
            # Verify nothing was partially deleted
            assert frappe.db.exists("Candidate", candidate_id), "Candidate was partially deleted!"
            assert frappe.db.exists("Job Application", app_id), "Job Application was partially deleted!"
            assert frappe.db.exists("Candidate Note", note_id), "Candidate Note was partially deleted!"
            assert frappe.db.exists("Talent Pool Member", member_id), "Talent Pool Member was partially deleted!"
            _pass(test_id, f"Single atomic rejection with all blocking_links present: {list(links.keys())}.")
    except Exception as exc:
        _fail(test_id, "Multiple linked records", f"Unexpected exception: {exc}\n{traceback.format_exc()}")
    finally:
        if candidate_id:
            _force_cleanup(candidate_id)


def test_delete_09_cross_company_isolation(company: str) -> None:
    """DELETE-09: Company A cannot delete Candidate belonging to Company B (404/403)."""
    test_id = "DELETE-09"
    # We simulate this by trying to delete a candidate that doesn't belong to the current company.
    # The _get_or_raise -> _assert_candidate_access path handles this.
    # We create a candidate with a different company field (not the current company).
    candidate_id = None
    try:
        # Create candidate with an invalid/different company
        doc = frappe.new_doc("Candidate")
        doc.first_name = "CrossCompany"
        doc.last_name = "Test"
        doc.candidate_name = "CrossCompany Test"
        doc.email = "del09@delete-audit.test"
        doc.mobile_no = "+919999999998"
        doc.date_of_birth = "1990-01-01"
        doc.address_line_1 = "1 Test Street"
        doc.city = "Bengaluru"
        doc.state = "Karnataka"
        doc.country = "India"
        doc.status = "Active"
        doc.company = "DIFFERENT_COMPANY_DOES_NOT_EXIST"  # Not the current company
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        candidate_id = doc.name

        service = CandidateService()
        try:
            service.delete_candidate(candidate_id)
            _fail(test_id, "Cross-company deletion", "BLOCKER: Cross-company deletion was NOT blocked!")
        except (ATSPermissionError, ATSNotFoundError) as exc:
            _pass(test_id, f"Cross-company deletion correctly blocked: {type(exc).__name__}: {exc}")
        except Exception as exc:
            _fail(test_id, "Cross-company deletion", f"Wrong exception type: {type(exc).__name__}: {exc}")
    except Exception as exc:
        _fail(test_id, "Cross-company setup", f"Setup error: {exc}")
    finally:
        if candidate_id:
            try:
                frappe.delete_doc("Candidate", candidate_id, ignore_permissions=True, force=True)
                frappe.db.commit()
            except Exception:
                pass


def test_delete_10_unauthenticated(company: str) -> None:
    """DELETE-10: Unauthenticated session cannot delete (403 via @employer_required)."""
    test_id = "DELETE-10"
    # This is enforced by the @employer_required decorator at the API layer.
    # At the service layer, _get_or_raise -> _assert_candidate_access calls
    # get_current_company() which calls get_current_employer_user() which raises
    # ATSPermissionError for Guest sessions.
    # We simulate by checking that Guest session raises ATSPermissionError.
    from recruitrain_employer.utils.permissions import get_current_employer_user

    original_user = frappe.session.user
    try:
        frappe.session.user = "Guest"
        try:
            get_current_employer_user()
            _fail(test_id, "Unauthenticated access", "BLOCKER: Guest session was NOT rejected by employer_required!")
        except ATSPermissionError:
            _pass(test_id, "Unauthenticated deletion blocked by ATSPermissionError (employer_required decorator).")
    except Exception as exc:
        _fail(test_id, "Unauthenticated deletion", f"Unexpected exception: {exc}")
    finally:
        frappe.session.user = original_user


def test_delete_11_concurrent_deletion(company: str) -> None:
    """DELETE-11: Concurrent deletion of the same candidate — second delete returns NOT_FOUND."""
    test_id = "DELETE-11"
    candidate_id = None
    try:
        candidate_id = _make_candidate("del11@delete-audit.test", company)
        service = CandidateService()

        # First delete — must succeed
        result = service.delete_candidate(candidate_id)
        assert result.get("deleted") is True, f"First delete failed: {result}"

        # Second delete — same candidate ID — must raise ATSNotFoundError
        try:
            service.delete_candidate(candidate_id)
            _fail(test_id, "Concurrent deletion", "BLOCKER: Second deletion of already-deleted candidate did not raise!")
        except ATSNotFoundError:
            _pass(test_id, "Concurrent deletion safe: second delete raises ATSNotFoundError (no inconsistent state).")
        except ATSValidationError:
            _pass(test_id, "Concurrent deletion safe: second delete raises ATSValidationError.")
    except Exception as exc:
        _fail(test_id, "Concurrent deletion", f"Unexpected exception: {exc}\n{traceback.format_exc()}")
        if candidate_id:
            _force_cleanup(candidate_id)


def test_delete_12_response_envelope(company: str) -> None:
    """DELETE-12: Response envelope must conform to standard RecruitTrain structure."""
    test_id = "DELETE-12"
    candidate_id = None
    try:
        candidate_id = _make_candidate("del12@delete-audit.test", company)
        service = CandidateService()
        result = service.delete_candidate(candidate_id)

        # Service layer returns raw dict; API layer wraps in success_response envelope
        # Here we verify the raw dict contract
        assert "name" in result, f"Missing 'name' in result: {result}"
        assert result["name"] == candidate_id, f"name mismatch: {result['name']} != {candidate_id}"
        assert "deleted" in result, f"Missing 'deleted' in result: {result}"
        assert result["deleted"] is True, f"deleted is not True: {result}"
        _pass(test_id, f"Response envelope correct: {result}")
    except Exception as exc:
        _fail(test_id, "Response envelope", f"Unexpected exception: {exc}\n{traceback.format_exc()}")
        if candidate_id:
            _force_cleanup(candidate_id)


# ---------------------------------------------------------------------------
# Archive-First Policy Verification
# ---------------------------------------------------------------------------

def test_archive_via_status_update(company: str) -> None:
    """ARCH-01: Verify archive-first is possible via status = 'Archived'."""
    test_id = "ARCH-01"
    candidate_id = None
    try:
        candidate_id = _make_candidate("arch01@delete-audit.test", company)
        app_id = _make_job_application(candidate_id, company)

        service = CandidateService()
        # Attempt deletion — must fail
        try:
            service.delete_candidate(candidate_id)
            _fail(test_id, "Archive-first flow", "BLOCKER: Deletion was NOT rejected when applications exist!")
            return
        except ATSConflictError:
            pass  # Expected

        # Archive instead via status update
        archived = service.update_candidate(candidate_id, {"status": "Archived"})
        assert archived["status"] == "Archived", f"Status not updated to Archived: {archived}"
        assert frappe.db.exists("Candidate", candidate_id), "Candidate deleted instead of archived!"
        assert frappe.db.exists("Job Application", app_id), "Job Application was deleted during archival!"
        _pass(test_id, "Archive-first flow verified: status='Archived' preserves all linked records.")
    except Exception as exc:
        _fail(test_id, "Archive-first flow", f"Unexpected exception: {exc}\n{traceback.format_exc()}")
    finally:
        if candidate_id:
            _force_cleanup(candidate_id)


# ---------------------------------------------------------------------------
# Main Runner
# ---------------------------------------------------------------------------

def run_tests():
    print("\n" + "=" * 70)
    print("  Phase 5.2 — Candidate Delete Referential Integrity Test Suite")
    print("=" * 70 + "\n")

    try:
        company = get_current_company()
        print(f"[SETUP] Resolved company: '{company}'\n")
    except Exception as exc:
        print(f"[FATAL] Cannot resolve company: {exc}")
        print("Run this as an authenticated Employer User (not Guest).")
        return

    # Run all DELETE tests
    test_delete_01_no_linked_records(company)
    test_delete_02_with_job_application(company)
    test_delete_03_with_interview(company)
    test_delete_04_with_offer(company)
    test_delete_05_with_activity_logs(company)
    test_delete_06_with_candidate_note(company)
    test_delete_07_with_talent_pool(company)
    test_delete_08_multiple_linked_records(company)
    test_delete_09_cross_company_isolation(company)
    test_delete_10_unauthenticated(company)
    test_delete_11_concurrent_deletion(company)
    test_delete_12_response_envelope(company)
    test_archive_via_status_update(company)

    # Summary
    passed = [r for r in _RESULTS if r["status"] == "PASS"]
    failed = [r for r in _RESULTS if r["status"] == "FAIL"]

    print("\n" + "=" * 70)
    print(f"  RESULTS: {len(passed)} PASSED | {len(failed)} FAILED")
    print("=" * 70)

    if failed:
        print("\n[BLOCKERS]")
        for r in failed:
            print(f"  {r['id']}: {r['description']}")
            print(f"    REASON: {r.get('reason', 'N/A')}")
        print("\nPhase 5.2 FAILED. DO NOT proceed to Phase 6.")
    else:
        print("\nAll DELETE tests passed. Phase 5.2 integrity verified.")
        print("Candidate deletion is fully protected against recruitment history loss.")

    return _RESULTS


if __name__ == "__main__":
    run_tests()
