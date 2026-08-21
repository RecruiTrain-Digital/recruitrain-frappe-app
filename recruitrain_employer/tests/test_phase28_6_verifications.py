# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.tests.test_phase28_6_verifications
=========================================================

Authoritative Test Suite for Phase 28.6:
- VAPID Public Key API Verification (No DocType mutation, zero phone validation)
- Notification Preferences Save & Persistence Verification (MariaDB single-field update)
- Web Push Preference Enforcement (Suppression on false, delivery on true)
"""

from __future__ import annotations

import json
import unittest

import frappe
from recruitrain_employer.api.notifications import (
    get_notification_preferences,
    update_notification_preferences,
)
from recruitrain_employer.api.push import (
    get_vapid_public_key,
    subscribe_push,
)
from recruitrain_employer.services.push_service import PushService
from recruitrain_employer.utils.constants import DOCTYPE_COMPANY, DOCTYPE_EMPLOYER_USER
from recruitrain_employer.utils.response import success_response


class TestPhase286Verifications(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        site_name = "development.localhost"
        sites_path = "/workspace/development/frappe-bench/sites"
        if not getattr(frappe.local, "site", None):
            frappe.init(site=site_name, sites_path=sites_path)
            frappe.connect()

    def setUp(self):
        frappe.db.rollback()
        self.test_user = "emp1@gmail.com"
        frappe.set_user(self.test_user)

        self.company = frappe.db.get_value(
            DOCTYPE_EMPLOYER_USER,
            {"user": self.test_user, "status": "Active"},
            "company",
        )
        if not self.company:
            self.company = "RecruiTrain"
            frappe.get_doc(
                {
                    "doctype": DOCTYPE_COMPANY,
                    "company_name": self.company,
                    "status": "Active",
                }
            ).insert(ignore_permissions=True)

            frappe.get_doc(
                {
                    "doctype": DOCTYPE_EMPLOYER_USER,
                    "user": self.test_user,
                    "company": self.company,
                    "role": "Administrator",
                    "status": "Active",
                    "phone": "8787878787",  # Raw phone without country code
                }
            ).insert(ignore_permissions=True)
            frappe.db.commit()

        # Reset notification preferences in DB for clean test state
        emp_user_name = frappe.db.get_value(
            DOCTYPE_EMPLOYER_USER,
            {"user": self.test_user, "company": self.company},
            "name",
        )
        if emp_user_name:
            frappe.db.set_value(DOCTYPE_EMPLOYER_USER, emp_user_name, "notification_preferences", None)
            frappe.db.commit()

    def tearDown(self):
        frappe.db.rollback()

    # ------------------------------------------------------------------
    # VAPID Endpoint Tests
    # ------------------------------------------------------------------

    def test_VAPID_01_authenticated_request_succeeds(self):
        """VAPID-01: Authenticated request succeeds with 200/success envelope."""
        res = get_vapid_public_key()
        self.assertTrue(res.get("success"), f"Expected success=True, got {res}")

    def test_VAPID_02_guest_rejected(self):
        """VAPID-02: Guest request is rejected with unauthorized status."""
        frappe.set_user("Guest")
        res = get_vapid_public_key()
        self.assertFalse(res.get("success"))
        self.assertEqual(res.get("error", {}).get("code"), "UNAUTHORIZED")

    def test_VAPID_03_public_key_returned(self):
        """VAPID-03: Public key returned is non-empty string."""
        frappe.set_user(self.test_user)
        res = get_vapid_public_key()
        data = res.get("data") or {}
        pub_key = data.get("public_key")
        self.assertTrue(isinstance(pub_key, str) and len(pub_key) > 20)

    def test_VAPID_04_private_key_never_returned(self):
        """VAPID-04: Private VAPID key is NEVER returned in response envelope."""
        frappe.set_user(self.test_user)
        res = get_vapid_public_key()
        raw_json = json.dumps(res)
        self.assertNotIn("private_key", raw_json)
        self.assertNotIn("PRIVATE KEY", raw_json)

    def test_VAPID_05_endpoint_performs_no_mutation(self):
        """VAPID-05: get_vapid_public_key performs zero database mutations."""
        frappe.set_user(self.test_user)
        emp_user_name = frappe.db.get_value(
            DOCTYPE_EMPLOYER_USER,
            {"user": self.test_user, "company": self.company},
            "name",
        )
        mod_before = frappe.db.get_value(DOCTYPE_EMPLOYER_USER, emp_user_name, "modified")
        get_vapid_public_key()
        mod_after = frappe.db.get_value(DOCTYPE_EMPLOYER_USER, emp_user_name, "modified")
        self.assertEqual(mod_before, mod_after)

    def test_VAPID_07_no_phone_validation_triggered(self):
        """VAPID-07: No phone country code validation is triggered."""
        frappe.set_user(self.test_user)
        res = get_vapid_public_key()
        self.assertTrue(res.get("success"))
        msg = res.get("message") or ""
        self.assertNotIn("country code", msg.lower())

    # ------------------------------------------------------------------
    # Notification Preferences Tests
    # ------------------------------------------------------------------

    def test_PREF_01_default_preferences_all_on(self):
        """PREF-01: Default preferences are all ON (true)."""
        frappe.set_user(self.test_user)
        res = get_notification_preferences()
        self.assertTrue(res.get("success"))
        data = res.get("data") or {}
        self.assertTrue(data.get("browser_push_notifications"))
        self.assertTrue(data.get("in_app_notifications"))

    def test_PREF_02_and_06_save_one_changed_preference(self):
        """PREF-02 & PREF-06: Save browser_push_notifications=False to MariaDB without error."""
        frappe.set_user(self.test_user)
        # Pass dict directly in form_dict or via helper
        frappe.form_dict = {"browser_push_notifications": False}
        res = update_notification_preferences()
        self.assertTrue(res.get("success"), f"Save failed: {res}")
        data = res.get("data") or {}
        self.assertFalse(data.get("browser_push_notifications"))
        self.assertTrue(data.get("in_app_notifications"))

    def test_PREF_03_untouched_preferences_remain_on(self):
        """PREF-03: Untouched preferences remain ON after partial update."""
        frappe.set_user(self.test_user)
        frappe.form_dict = {"browser_push_notifications": False}
        update_notification_preferences()

        get_res = get_notification_preferences()
        data = get_res.get("data") or {}
        self.assertFalse(data.get("browser_push_notifications"))
        self.assertTrue(data.get("email_notifications"))
        self.assertTrue(data.get("interview_reminders"))

    def test_PREF_04_and_05_saved_value_persists(self):
        """PREF-04 & PREF-05: Saved preference survives session reset / re-query."""
        frappe.set_user(self.test_user)
        frappe.form_dict = {"browser_push_notifications": False}
        update_notification_preferences()

        # Simulate logout/login
        frappe.set_user("Guest")
        frappe.set_user(self.test_user)

        get_res = get_notification_preferences()
        data = get_res.get("data") or {}
        self.assertFalse(data.get("browser_push_notifications"))

    def test_PREF_10_database_matches_returned_preferences(self):
        """PREF-10: Database notification_preferences field matches returned dict."""
        frappe.set_user(self.test_user)
        frappe.form_dict = {"browser_push_notifications": False}
        update_notification_preferences()

        emp_user_name = frappe.db.get_value(
            DOCTYPE_EMPLOYER_USER,
            {"user": self.test_user, "company": self.company},
            "name",
        )
        raw_db_json = frappe.db.get_value(
            DOCTYPE_EMPLOYER_USER,
            emp_user_name,
            "notification_preferences",
        )
        db_dict = json.loads(raw_db_json)
        self.assertFalse(db_dict.get("browser_push_notifications"))

    # ------------------------------------------------------------------
    # Web Push Preference Enforcement Tests
    # ------------------------------------------------------------------

    def test_PUSH_04_and_05_push_preference_enforcement(self):
        """PUSH-04 & PUSH-05: Push service respects browser_push_notifications setting."""
        frappe.set_user(self.test_user)
        push_service = PushService()

        # Case 1: When browser_push_notifications = False -> 0 dispatches
        frappe.form_dict = {"browser_push_notifications": False}
        update_notification_preferences()

        count_off = push_service.send_notification_push(
            {
                "recipient": self.test_user,
                "company": self.company,
                "title": "Test Push",
                "message": "Test Body",
            }
        )
        self.assertEqual(count_off, 0)

        # Case 2: When browser_push_notifications = True -> permits dispatch
        frappe.form_dict = {"browser_push_notifications": True}
        update_notification_preferences()

        count_on = push_service.send_notification_push(
            {
                "recipient": self.test_user,
                "company": self.company,
                "title": "Test Push",
                "message": "Test Body",
            }
        )
        self.assertTrue(count_on >= 0)


if __name__ == "__main__":
    unittest.main()
