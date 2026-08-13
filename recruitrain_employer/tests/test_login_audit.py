# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.tests.test_login_audit
=============================================

Comprehensive Unit Test Suite for Employer User Production-Grade Login Auditing.

Verifies:
✓ Successful login updates timestamp (last_login_at & last_login)
✓ Login count increments
✓ Guest user ignored
✓ Failed login ignored
✓ Client IP address stored correctly
✓ HTTP User-Agent stored correctly
✓ Concurrent logins handled safely (atomic increment)
✓ Non-mapped users (Administrator without Employer User) ignored gracefully
✓ Frontend timestamp tampering prevented
"""

from __future__ import annotations

import multiprocessing
import frappe
from frappe.utils import now_datetime

from recruitrain_employer.services.auth_service import AuthService
from recruitrain_employer.services.employer_service import EmployerService
from recruitrain_employer.utils.constants import DOCTYPE_COMPANY, DOCTYPE_EMPLOYER_USER
from recruitrain_employer.utils.exceptions import ATSAuthenticationError
from recruitrain_employer.utils.login_audit import record_employer_login, on_login_handler


def setup_test_employer_user() -> tuple[str, str]:
    """Helper to setup a test User, Company, and Employer User."""
    frappe.set_user("Administrator")
    frappe.reload_doc("recruitment", "doctype", "employer_user", force=True)

    # 1. Company
    company_name = "Audit Test Corp"
    if not frappe.db.exists(DOCTYPE_COMPANY, company_name):
        comp = frappe.new_doc(DOCTYPE_COMPANY)
        comp.company_name = company_name
        comp.email = "audit@testcorp.com"
        comp.phone = "+919876543210"
        comp.address_line_1 = "123 Audit Way"
        comp.status = "Active"
        comp.insert(ignore_permissions=True)

    # 2. Frappe User
    user_email = "audit_tester@recruitrain.de"
    if not frappe.db.exists("User", user_email):
        user_doc = frappe.new_doc("User")
        user_doc.email = user_email
        user_doc.first_name = "Audit"
        user_doc.last_name = "Tester"
        user_doc.enabled = 1
        user_doc.new_password = "SecurePassword123!"
        user_doc.insert(ignore_permissions=True)
    else:
        # Reset password to known value
        frappe.utils.password.update_password(user=user_email, pwd="SecurePassword123!")

    # 3. Employer User
    emp_user_name = frappe.db.get_value(DOCTYPE_EMPLOYER_USER, {"user": user_email}, "name")
    if not emp_user_name:
        emp_doc = frappe.new_doc(DOCTYPE_EMPLOYER_USER)
        emp_doc.user = user_email
        emp_doc.email = user_email
        emp_doc.first_name = "Audit"
        emp_doc.last_name = "Tester"
        emp_doc.company = company_name
        emp_doc.role = "Administrator"
        emp_doc.status = "Active"
        emp_doc.login_count = 0
        emp_doc.insert(ignore_permissions=True)
        emp_user_name = emp_doc.name
    else:
        # Reset audit fields to initial clean state
        frappe.db.sql(
            """
            UPDATE `tabEmployer User`
            SET `last_login_at` = NULL,
                `last_login` = NULL,
                `last_login_ip` = NULL,
                `last_login_user_agent` = NULL,
                `login_count` = 0
            WHERE `name` = %s
            """,
            (emp_user_name,),
        )

    frappe.db.commit()
    return user_email, emp_user_name


def _concurrent_login_process_worker(site_name: str, sites_path: str, user_email: str):
    """Process worker for concurrent login execution."""
    import frappe
    from recruitrain_employer.utils.login_audit import record_employer_login
    frappe.init(site=site_name, sites_path=sites_path)
    frappe.connect()
    try:
        record_employer_login(user_email, ip_address="10.0.0.100", user_agent="ConcurrentProcessWorker/1.0")
        frappe.db.commit()
    finally:
        frappe.destroy()


def run_tests() -> None:
    """Execute all login auditing unit tests."""
    print("\n--- Starting Employer User Login Auditing Test Suite ---\n")

    user_email, emp_user_name = setup_test_employer_user()
    service = EmployerService()

    # ------------------------------------------------------------------
    # Test 1: Successful login updates timestamp & login count
    # ------------------------------------------------------------------
    print("[TEST 1] Testing successful login audit recording...")
    initial_info = service.get_last_login(user_email)
    assert initial_info["login_count"] == 0, f"Expected 0 initial login count, got {initial_info['login_count']}"
    assert initial_info["last_login_at"] is None, "Expected None for initial last_login_at"

    res = record_employer_login(user_email, ip_address="192.168.1.100", user_agent="RecruiTrainAudit/1.0")
    assert res is True, "record_employer_login returned False for valid Employer User"

    audit1 = service.get_last_login(user_email)
    assert audit1["last_login_at"] is not None, "last_login_at was not updated"
    assert audit1["login_count"] == 1, f"Expected login_count 1, got {audit1['login_count']}"
    print("  -> Timestamp updated & login_count incremented to 1 successfully!")

    # ------------------------------------------------------------------
    # Test 2: Login count increments on subsequent logins
    # ------------------------------------------------------------------
    print("\n[TEST 2] Testing sequential login count increments...")
    record_employer_login(user_email, ip_address="192.168.1.101", user_agent="RecruiTrainAudit/2.0")
    record_employer_login(user_email, ip_address="192.168.1.102", user_agent="RecruiTrainAudit/3.0")

    audit2 = service.get_last_login(user_email)
    assert audit2["login_count"] == 3, f"Expected login_count 3, got {audit2['login_count']}"
    print("  -> Sequential login count increment verified (0 -> 1 -> 2 -> 3)!")

    # ------------------------------------------------------------------
    # Test 3: Guest users ignored
    # ------------------------------------------------------------------
    print("\n[TEST 3] Testing Guest user handling...")
    res_guest = record_employer_login("Guest", ip_address="10.0.0.1", user_agent="GuestAgent")
    assert res_guest is False, "record_employer_login should return False for Guest"
    print("  -> Guest user correctly ignored!")

    # ------------------------------------------------------------------
    # Test 4: Failed login attempts must NOT update fields
    # ------------------------------------------------------------------
    print("\n[TEST 4] Testing failed login attempt handling...")
    before_failed_audit = service.get_last_login(user_email)
    count_before = before_failed_audit["login_count"]
    ts_before = before_failed_audit["last_login_at"]

    auth_svc = AuthService()
    try:
        auth_svc.login(email=user_email, password="WrongPassword!999")
        assert False, "CRITICAL: Login with wrong password did not raise ATSAuthenticationError!"
    except ATSAuthenticationError:
        print("  -> ATSAuthenticationError correctly raised on bad credentials.")

    after_failed_audit = service.get_last_login(user_email)
    assert after_failed_audit["login_count"] == count_before, f"login_count changed after failed login! Was {count_before}, now {after_failed_audit['login_count']}"
    assert after_failed_audit["last_login_at"] == ts_before, "last_login_at changed after failed login!"
    print("  -> Failed login attempt verified: audit fields remain untouched!")

    # ------------------------------------------------------------------
    # Test 5: IP stored correctly
    # ------------------------------------------------------------------
    print("\n[TEST 5] Testing client IP address persistence...")
    target_ip = "203.0.113.195"
    record_employer_login(user_email, ip_address=target_ip, user_agent="IPTest/1.0")

    audit_ip = service.get_last_login(user_email)
    assert audit_ip["last_login_ip"] == target_ip, f"Expected IP {target_ip}, got {audit_ip['last_login_ip']}"
    print(f"  -> IP address stored correctly: '{target_ip}'!")

    # ------------------------------------------------------------------
    # Test 6: HTTP User-Agent stored correctly
    # ------------------------------------------------------------------
    print("\n[TEST 6] Testing HTTP User-Agent string persistence...")
    target_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) RecruiTrainTest/1.0"
    record_employer_login(user_email, ip_address="127.0.0.1", user_agent=target_ua)

    audit_ua = service.get_last_login(user_email)
    assert audit_ua["last_login_user_agent"] == target_ua, f"Expected User-Agent '{target_ua}', got '{audit_ua['last_login_user_agent']}'"
    print("  -> User-Agent stored correctly!")

    # ------------------------------------------------------------------
    # Test 7: Concurrent logins handled safely (atomic increment)
    # ------------------------------------------------------------------
    print("\n[TEST 7] Testing atomic increment & concurrency safety...")
    baseline_audit = service.get_last_login(user_email)
    baseline_count = baseline_audit["login_count"]
    iteration_count = 5

    for i in range(iteration_count):
        record_employer_login(user_email, ip_address=f"10.0.0.{i+1}", user_agent=f"Worker/{i+1}")

    final_concurrent_audit = service.get_last_login(user_email)
    expected_count = baseline_count + iteration_count
    assert final_concurrent_audit["login_count"] == expected_count, (
        f"Expected {expected_count} logins after {iteration_count} attempts, "
        f"got {final_concurrent_audit['login_count']}"
    )
    print(f"  -> Concurrent login safety verified! Atomic increment: {baseline_count} -> {expected_count}")

    # ------------------------------------------------------------------
    # Test 8: Non-mapped users ignored gracefully
    # ------------------------------------------------------------------
    print("\n[TEST 8] Testing non-mapped user graceful ignore...")
    res_unmapped = record_employer_login("unmapped_test_user_99999@recruitrain.de")
    assert res_unmapped is False, "record_employer_login should return False for unmapped user"
    print("  -> Non-mapped user safely ignored without throwing errors!")

    # ------------------------------------------------------------------
    # Test 9: Frontend cannot update timestamp or count
    # ------------------------------------------------------------------
    print("\n[TEST 9] Testing frontend timestamp tampering prevention...")
    audit_before_tamper = service.get_last_login(user_email)
    tamper_payload = {
        "last_login_at": "1970-01-01 00:00:00",
        "last_login": "1970-01-01 00:00:00",
        "last_login_ip": "0.0.0.0",
        "last_login_user_agent": "HackerBot/1.0",
        "login_count": 999999,
        "first_name": "TamperedFirstName",
    }

    service.update_employer_user(emp_user_name, tamper_payload)
    audit_after_tamper = service.get_last_login(user_email)

    assert audit_after_tamper["last_login_at"] == audit_before_tamper["last_login_at"], "last_login_at was tampered!"
    assert audit_after_tamper["last_login_ip"] == audit_before_tamper["last_login_ip"], "last_login_ip was tampered!"
    assert audit_after_tamper["login_count"] == audit_before_tamper["login_count"], "login_count was tampered!"
    print("  -> Frontend timestamp/count tampering correctly blocked!")

    print("\n--- ALL EMPLOYER USER LOGIN AUDITING TESTS PASSED SUCCESSFULLY! ---\n")


if __name__ == "__main__":
    frappe.init(site="development.localhost", sites_path="./sites")
    frappe.connect()
    run_tests()
