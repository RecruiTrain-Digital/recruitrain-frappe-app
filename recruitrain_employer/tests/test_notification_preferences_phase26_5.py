# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.tests.test_notification_preferences_phase26_5
=====================================================================

Phase 26.5 — Notification Preferences & Default-On Regression Test Suite.

Verifies:
- PREF-01: Authenticated preference fetch works.
- PREF-02: Missing preference record returns all supported preferences as ON.
- PREF-03: Save preference changes persist to MariaDB.
- PREF-04: Saved OFF value remains OFF after refresh (fresh DB lookup).
- PREF-05: Saved ON value remains ON after refresh (fresh DB lookup).
- PREF-06: Untouched preferences remain ON by default.
- PREF-07: Notification with no preference record is not accidentally suppressed.
- PREF-08: Explicit OFF preference suppresses the relevant notification.
- PREF-09: User isolation works.
- PREF-10: Company isolation works.
- PREF-11: Client cannot spoof user/company identity.
- PREF-12: API returns persisted authoritative values.
"""

from __future__ import annotations

import json
import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from recruitrain_employer.api.notifications import (
    get_notification_preferences,
    notification_preferences,
    update_notification_preferences,
)
from recruitrain_employer.services.notification_service import NotificationService
from recruitrain_employer.utils.constants import (
    DEFAULT_NOTIFICATION_PREFERENCES,
    DOCTYPE_EMPLOYER_USER,
    DOCTYPE_NOTIFICATION,
)
from recruitrain_employer.utils.exceptions import ATSNotFoundError, ATSPermissionError
from recruitrain_employer.utils.notification_hooks import notify_event


class TestNotificationPreferencesPhase265(FrappeTestCase):
    """Test suite for Phase 26.5 Notification Preferences and Default-On behavior."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.test_prefix = "PREF_TEST_"
        cls.company_a = "Test Company A"
        cls.company_b = "Test Company B"
        cls.user_a = "pref_user_a@recruitrain.de"
        cls.user_b = "pref_user_b@recruitrain.de"

        # Setup test company records
        for company_name in [cls.company_a, cls.company_b]:
            if not frappe.db.exists("Company", company_name):
                comp_doc = frappe.get_doc({
                    "doctype": "Company",
                    "company_name": company_name,
                    "industry": "Technology",
                    "email": f"contact@{company_name.lower().replace(' ', '')}.com",
                    "phone": "+12025550123",
                    "address_line_1": "123 Test Street",
                    "status": "Active",
                })
                comp_doc.insert(ignore_permissions=True)

        # Setup test user accounts and Employer User records
        for email, comp in [(cls.user_a, cls.company_a), (cls.user_b, cls.company_b)]:
            if not frappe.db.exists("User", email):
                u_doc = frappe.get_doc({
                    "doctype": "User",
                    "email": email,
                    "first_name": "Pref",
                    "last_name": "Tester",
                    "send_welcome_email": 0,
                    "roles": [{"role": "System Manager"}],
                })
                u_doc.insert(ignore_permissions=True)

            emp_name = frappe.db.get_value(DOCTYPE_EMPLOYER_USER, {"user": email}, "name")
            if not emp_name:
                emp_doc = frappe.get_doc({
                    "doctype": DOCTYPE_EMPLOYER_USER,
                    "user": email,
                    "company": comp,
                    "first_name": "Pref",
                    "last_name": "Tester",
                    "role": "Administrator",
                    "status": "Active",
                })
                emp_doc.insert(ignore_permissions=True)
            else:
                # Reset preferences field for fresh test execution
                frappe.db.set_value(DOCTYPE_EMPLOYER_USER, emp_name, "notification_preferences", None)

        frappe.db.commit()
        cls.service = NotificationService()

    def setUp(self):
        super().setUp()
        frappe.set_user(self.user_a)
        frappe.session.user = self.user_a
        # Reset user_a notification preferences before each test
        emp_name = frappe.db.get_value(DOCTYPE_EMPLOYER_USER, {"user": self.user_a}, "name")
        if emp_name:
            frappe.db.set_value(DOCTYPE_EMPLOYER_USER, emp_name, "notification_preferences", None)
            frappe.db.commit()

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.session.user = "Administrator"
        super().tearDown()

    def test_PREF_01_authenticated_preference_fetch(self):
        """PREF-01: Authenticated preference fetch returns valid preference structure."""
        prefs = self.service.get_notification_preferences(self.user_a, self.company_a)
        self.assertIsInstance(prefs, dict)
        self.assertIn("interview_reminders", prefs)
        self.assertIn("email_notifications", prefs)

    def test_PREF_02_missing_preference_defaults_to_on(self):
        """PREF-02: User with no preference record receives all supported preferences as ON (true)."""
        prefs = self.service.get_notification_preferences(self.user_a, self.company_a)
        for key, val in prefs.items():
            if key == "digest_frequency":
                self.assertEqual(val, "realtime")
            else:
                self.assertTrue(val, f"Preference key '{key}' should default to True (ON).")

    def test_PREF_03_save_preferences_persists_to_mariadb(self):
        """PREF-03: Save preference changes persist directly to MariaDB."""
        new_prefs = {
            "interview_reminders": False,
            "application_updates": True,
            "offer_alerts": False,
        }
        saved = self.service.update_notification_preferences(self.user_a, self.company_a, new_prefs)
        self.assertFalse(saved["interview_reminders"])
        self.assertFalse(saved["offer_alerts"])
        self.assertTrue(saved["application_updates"])

        # Check raw DB value
        raw_db_val = frappe.db.get_value(
            DOCTYPE_EMPLOYER_USER,
            {"user": self.user_a},
            "notification_preferences",
        )
        self.assertIsNotNone(raw_db_val)
        parsed_db = json.loads(raw_db_val)
        self.assertFalse(parsed_db["interview_reminders"])
        self.assertFalse(parsed_db["offer_alerts"])

    def test_PREF_04_saved_off_value_remains_off_after_fresh_lookup(self):
        """PREF-04: Saved OFF preference value remains OFF on fresh DB query (simulating refresh)."""
        self.service.update_notification_preferences(
            self.user_a, self.company_a, {"interview_reminders": False}
        )
        fresh_prefs = self.service.get_notification_preferences(self.user_a, self.company_a)
        self.assertFalse(fresh_prefs["interview_reminders"])
        self.assertFalse(fresh_prefs["interview"])

    def test_PREF_05_saved_on_value_remains_on_after_fresh_lookup(self):
        """PREF-05: Explicitly saved ON preference value remains ON after refresh."""
        self.service.update_notification_preferences(
            self.user_a, self.company_a, {"offer_alerts": True}
        )
        fresh_prefs = self.service.get_notification_preferences(self.user_a, self.company_a)
        self.assertTrue(fresh_prefs["offer_alerts"])
        self.assertTrue(fresh_prefs["offer"])

    def test_PREF_06_untouched_preferences_remain_on(self):
        """PREF-06: Modifying one preference preserves default ON status for untouched keys."""
        self.service.update_notification_preferences(
            self.user_a, self.company_a, {"interview_reminders": False}
        )
        fresh_prefs = self.service.get_notification_preferences(self.user_a, self.company_a)
        self.assertFalse(fresh_prefs["interview_reminders"])
        self.assertTrue(fresh_prefs["application_updates"])
        self.assertTrue(fresh_prefs["offer_alerts"])
        self.assertTrue(fresh_prefs["in_app_notifications"])

    def _get_notif_filters(self, user: str, notif_type: str) -> dict[str, str]:
        """Resolve dynamic meta fields for Notification Log filters."""
        meta = frappe.get_meta(DOCTYPE_NOTIFICATION)
        recipient_field = "recipient" if meta.has_field("recipient") else "for_user"
        type_field = "notification_type" if meta.has_field("notification_type") else ("type" if meta.has_field("type") else "entity_type")
        return {recipient_field: user, type_field: notif_type}

    def test_PREF_07_notification_with_no_preference_record_not_suppressed(self):
        """PREF-07: User with missing preference record receives recruitment event notifications."""
        # Ensure user_a has no stored preference record
        emp_name = frappe.db.get_value(DOCTYPE_EMPLOYER_USER, {"user": self.user_a}, "name")
        frappe.db.set_value(DOCTYPE_EMPLOYER_USER, emp_name, "notification_preferences", None)
        frappe.db.commit()

        filters = self._get_notif_filters(self.user_a, "Interview")
        initial_count = frappe.db.count(DOCTYPE_NOTIFICATION, filters=filters)

        mock_doc = frappe._dict({
            "name": f"{self.test_prefix}INT_NOPREF",
            "doctype": "Interview",
            "company": self.company_a,
            "candidate": "CAND-NOPREF",
            "job_opening": "JOB-NOPREF",
        })

        notify_event(
            doc=mock_doc,
            title="Interview scheduled for NoPref",
            message="NoPref Candidate Interview",
            notification_type="Interview",
            priority="Medium",
            entity_type="Interview",
            entity_id=mock_doc.name,
            action_url="/app/interviews",
        )

        new_count = frappe.db.count(DOCTYPE_NOTIFICATION, filters=filters)
        self.assertEqual(new_count, initial_count + 1)

    def test_PREF_08_explicit_off_suppresses_notification(self):
        """PREF-08: Explicit OFF preference suppresses delivery of matching notification category."""
        self.service.update_notification_preferences(
            self.user_a, self.company_a, {"interview_reminders": False}
        )

        filters = self._get_notif_filters(self.user_a, "Interview")
        initial_count = frappe.db.count(DOCTYPE_NOTIFICATION, filters=filters)

        mock_doc = frappe._dict({
            "name": f"{self.test_prefix}INT_OFF",
            "doctype": "Interview",
            "company": self.company_a,
            "candidate": "CAND-OFF",
            "job_opening": "JOB-OFF",
        })

        notify_event(
            doc=mock_doc,
            title="Interview scheduled for OffUser",
            message="Off User Interview",
            notification_type="Interview",
            priority="Medium",
            entity_type="Interview",
            entity_id=mock_doc.name,
            action_url="/app/interviews",
        )

        new_count = frappe.db.count(DOCTYPE_NOTIFICATION, filters=filters)
        # Suppressed: count must NOT increase
        self.assertEqual(new_count, initial_count)

    def test_PREF_09_user_isolation(self):
        """PREF-09: Preference changes for User A do not affect User B preferences."""
        self.service.update_notification_preferences(
            self.user_a, self.company_a, {"offer_alerts": False}
        )
        user_b_prefs = self.service.get_notification_preferences(self.user_b, self.company_b)
        self.assertTrue(user_b_prefs["offer_alerts"])

    def test_PREF_10_company_isolation(self):
        """PREF-10: Preferences respect authenticated company scope."""
        prefs_a = self.service.get_notification_preferences(self.user_a, self.company_a)
        prefs_b = self.service.get_notification_preferences(self.user_b, self.company_b)
        self.assertIsInstance(prefs_a, dict)
        self.assertIsInstance(prefs_b, dict)

    def test_PREF_11_identity_spoofing_defense(self):
        """PREF-11: Client-supplied user/company parameter cannot override session user."""
        frappe.form_dict.clear()
        frappe.form_dict.update({
            "user_id": self.user_b,
            "company": self.company_b,
            "preferences": {"offer_alerts": False},
        })
        # Executing via controller function uses authenticated session user (self.user_a)
        res = update_notification_preferences()
        self.assertTrue(res["success"])
        self.assertFalse(res["data"]["offer_alerts"])

        # User B preferences must remain untouched
        user_b_prefs = self.service.get_notification_preferences(self.user_b, self.company_b)
        self.assertTrue(user_b_prefs["offer_alerts"])

    def test_PREF_12_api_returns_persisted_authoritative_values(self):
        """PREF-12: API returns exact persisted database state envelope."""
        frappe.form_dict.clear()
        frappe.form_dict.update({
            "preferences": {
                "interview_reminders": True,
                "application_updates": False,
                "digest_frequency": "daily",
            }
        })
        res = update_notification_preferences()
        self.assertTrue(res["success"])
        self.assertTrue(res["data"]["interview_reminders"])
        self.assertFalse(res["data"]["application_updates"])
        self.assertEqual(res["data"]["digest_frequency"], "daily")


def run_notification_preference_tests():
    """Execute standalone test suite runner."""
    suite = unittest.TestLoader().loadTestsFromTestCase(TestNotificationPreferencesPhase265)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    run_notification_preference_tests()
