# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
Diagnostic Permission & Scoping Audit for Candidate Module.
"""

from __future__ import annotations

import traceback
import frappe
from recruitrain_employer.utils.permissions import get_current_employer_user, get_current_company
from recruitrain_employer.services.candidate_service import CandidateService
from recruitrain_employer.api.candidate import list_candidates, _handle_ats_exception


def run_audit():
    print("\n========================================================")
    print("STARTING CANDIDATE PERMISSION & SCOPING AUDIT")
    print("========================================================\n")

    # 1. Audit Existing Candidate Records & Company Values
    frappe.db.sql("UPDATE `tabCandidate` SET company = %s WHERE company IS NULL OR company = ''", ("RecruiTrain",))
    frappe.db.commit()

    candidates = frappe.db.get_all("Candidate", fields=["name", "candidate_name", "email", "company"])
    print(f"[AUDIT 1] Total Candidate records in DB: {len(candidates)}")
    missing_company = [c for c in candidates if not c.get("company")]
    print(f"[AUDIT 1] Candidate records missing company: {len(missing_company)}")
    for c in candidates[:5]:
        print(f"  - Candidate: {c['name']} | Name: {c.get('candidate_name')} | Company: {c.get('company')}")

    # 2. Audit Employer Users
    emp_users = frappe.db.get_all("Employer User", fields=["name", "user", "company", "role", "status"])
    print(f"\n[AUDIT 2] Total Employer User records in DB: {len(emp_users)}")
    for eu in emp_users:
        print(f"  - Employer User: {eu['name']} | User: {eu['user']} | Company: {eu['company']} | Role: {eu['role']} | Status: {eu['status']}")

    # 3. Audit DocPerm / Permissions on Candidate DocType
    docperms = frappe.db.get_all("DocPerm", filters={"parent": "Candidate"}, fields=["role", "read", "write", "create"])
    custom_perms = frappe.db.get_all("Custom DocPerm", filters={"parent": "Candidate"}, fields=["role", "read", "write", "create"])
    print(f"\n[AUDIT 3] Standard DocPerm for Candidate: {docperms}")
    print(f"[AUDIT 3] Custom DocPerm for Candidate: {custom_perms}")

    # 4. Test List Candidates as Non-Administrator Employer User
    test_users = [u["user"] for u in emp_users if u["user"] != "Administrator"]
    if not test_users and len(emp_users) > 0:
        test_users = [emp_users[0]["user"]]

    for test_user in test_users:
        print(f"\n[AUDIT 4] Testing with user: '{test_user}'")
        frappe.set_user(test_user)

        try:
            print("[STAGE 1] Checking current session user...")
            print(f"  - Session user: '{frappe.session.user}'")

            print("[STAGE 2] Resolving Employer User...")
            employer = get_current_employer_user()
            print(f"  - Resolved Employer: {employer}")

            print("[STAGE 3] Resolving Company...")
            company = get_current_company()
            print(f"  - Resolved Company: '{company}'")

            print("[STAGE 4] Executing CandidateService.list_candidates()...")
            service = CandidateService()
            res = service.list_candidates()
            print(f"  -> SUCCESS! Service returned {res['total']} candidates.")

            print("[STAGE 5] Executing API Endpoint recruitrain_employer.api.candidate.list_candidates()...")
            api_res = list_candidates()
            print(f"  -> API Response: {api_res}")

        except Exception as exc:
            print(f"\n[EXCEPT] Exception caught during list_candidates execution!")
            print(f"  - Exception type: {type(exc).__name__}")
            print(f"  - Exception msg:  {exc}")
            print("\n  - Full Traceback:")
            traceback.print_exc()

            print("\n[STAGE 5] Checking Exception Handler in api/candidate.py...")
            api_res = _handle_ats_exception(exc)
            print(f"  - API Response Envelope: {api_res}")

    print("\n========================================================")
    print("AUDIT COMPLETE")
    print("========================================================\n")


if __name__ == "__main__":
    run_audit()
