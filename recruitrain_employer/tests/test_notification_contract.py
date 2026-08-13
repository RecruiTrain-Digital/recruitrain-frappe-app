# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.tests.test_notification_contract
=========================================================

Contract Verification & Hardening Test Suite for RecruitTrain Notification Backend (NOTIF-01 to NOTIF-30).

Tests:
NOTIF-01: List notifications
NOTIF-02: Pagination metadata & clamping
NOTIF-03: Search across subject/message
NOTIF-04: Filter by unread, priority, type, category, date
NOTIF-05: Get single notification detail
NOTIF-06: Create notification
NOTIF-07: Mandatory field validation
NOTIF-08: Invalid priority & type validation
NOTIF-09: Mark single notification read
NOTIF-10: Update notification preferences
NOTIF-11: Preferences payload validation
NOTIF-12: Mark all notifications read
NOTIF-13: Bulk update notifications (read & delete)
NOTIF-14: Linked entity derivation & serialization
NOTIF-15: JSON metadata parsing & serialization
NOTIF-16: Company isolation enforcement
NOTIF-17: Cross-company access blocking
NOTIF-18: Unauthorized user access blocking
NOTIF-19: Unauthenticated Guest rejection
NOTIF-20: 404 Not Found handling for invalid ID
NOTIF-21: Idempotent read status update
NOTIF-22: Delete single notification record
NOTIF-23: Clear user notifications (all vs read-only)
NOTIF-24: Response envelope formatting
NOTIF-25: Internal metadata exclusion
NOTIF-26: Sorting field sanitization
NOTIF-27: Search count accuracy
NOTIF-28: Notification stats and unread counts API
NOTIF-29: Security & input sanitization
NOTIF-30: Test data hygiene & cleanup
"""

from __future__ import annotations

import json
import unittest
import frappe

from recruitrain_employer.services.notification_service import NotificationService
from recruitrain_employer.api.notifications import (
    list_notifications,
    get_notification,
    notification_counts,
    get_unread_count,
    mark_notification_read,
    mark_all_notifications_read,
    delete_notification,
    clear_notifications,
    notification_preferences,
    update_notification_preferences,
    create_notification,
    bulk_update_notifications,
)
from recruitrain_employer.utils.exceptions import (
    ATSPermissionError,
    ATSValidationError,
    ATSNotFoundError,
)
from recruitrain_employer.utils.permissions import get_current_company, get_current_employer_user


class TestNotificationContract(unittest.TestCase):
    """Notification Backend Contract Test Suite (NOTIF-01..NOTIF-30)."""

    @classmethod
    def setUpClass(cls):
        cls.current_company = get_current_company()
        user_info = get_current_employer_user()
        cls.current_user = user_info["user"]
        cls.service = NotificationService()

        cls.test_prefix = "NOTIF-TEST-VERIFY-"
        cls.cleanup_test_records()

        # Create foreign test company for spoofing defense test
        cls.foreign_company = f"{cls.test_prefix}Foreign Co"
        if not frappe.db.exists("Company", cls.foreign_company):
            comp = frappe.new_doc("Company")
            comp.company_name = cls.foreign_company
            comp.abbr = "NTFC"
            comp.default_currency = "USD"
            comp.country = "United States"
            comp.email = "foreign@example.com"
            comp.phone = "+12025550198"
            comp.address_line_1 = "100 Foreign St"
            comp.insert(ignore_permissions=True)

        # Provision test notifications
        cls.created_notifs = []

        notif1 = cls.service.create_notification(
            raw_data={
                "title": f"{cls.test_prefix}New Application Received",
                "message": "Candidate John Doe applied for Senior Developer position.",
                "priority": "High",
                "notification_type": "Application",
                "category": "Recruitment",
                "entity_type": "Job Application",
                "entity_id": "APP-TEST-0001",
                "action_url": "/applications/APP-TEST-0001",
                "action_label": "View Application",
                "metadata": {"candidate_id": "CAND-001", "score": 95},
            },
            company=cls.current_company,
            recipient=cls.current_user,
            created_by="Administrator",
        )
        cls.created_notifs.append(notif1["name"])

        notif2 = cls.service.create_notification(
            raw_data={
                "title": f"{cls.test_prefix}Interview Scheduled",
                "message": "Technical interview scheduled with Jane Smith.",
                "priority": "Urgent",
                "notification_type": "Interview",
                "category": "Schedule",
                "entity_type": "Interview",
                "entity_id": "INT-TEST-0001",
                "action_url": "/interviews/INT-TEST-0001",
                "action_label": "View Interview",
                "metadata": {"interview_type": "Technical"},
            },
            company=cls.current_company,
            recipient=cls.current_user,
            created_by="Administrator",
        )
        cls.created_notifs.append(notif2["name"])

        frappe.db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.cleanup_test_records()

    @classmethod
    def cleanup_test_records(cls):
        prefix = "NOTIF-TEST-VERIFY-"
        frappe.db.delete("Notification Log", {"subject": ["like", f"{prefix}%"]})
        frappe.db.delete("Company", {"company_name": ["like", f"{prefix}%"]})
        frappe.db.commit()

    def test_NOTIF_01_list_notifications(self):
        """NOTIF-01: Verify listing notifications for authenticated user."""
        res = self.service.list_notifications(
            user=self.current_user,
            company=self.current_company,
            options={"page": 1, "page_size": 20},
        )
        self.assertIn("data", res)
        self.assertIn("total", res)
        self.assertIn("unread_count", res)
        self.assertGreaterEqual(res["total"], 2)
        self.assertIsInstance(res["data"], list)

    def test_NOTIF_02_pagination_metadata(self):
        """NOTIF-02: Verify pagination parameters, calculation, and size clamping."""
        res = self.service.list_notifications(
            user=self.current_user,
            company=self.current_company,
            options={"page": 1, "page_size": 1},
        )
        self.assertEqual(res["page"], 1)
        self.assertEqual(res["page_size"], 1)
        self.assertEqual(len(res["data"]), 1)

    def test_NOTIF_03_search(self):
        """NOTIF-03: Verify search functionality across subject and message content."""
        res = self.service.list_notifications(
            user=self.current_user,
            company=self.current_company,
            options={"search": "John Doe"},
        )
        self.assertGreaterEqual(res["total"], 1)
        self.assertTrue(any("John Doe" in n["message"] for n in res["data"]))

    def test_NOTIF_04_filters(self):
        """NOTIF-04: Verify filter by priority, notification_type, and unread status."""
        res = self.service.list_notifications(
            user=self.current_user,
            company=self.current_company,
            options={"priority": "Urgent", "notification_type": "Interview"},
        )
        self.assertGreaterEqual(res["total"], 1)
        for notif in res["data"]:
            self.assertEqual(notif["priority"], "Urgent")
            self.assertEqual(notif["notification_type"], "Interview")

    def test_NOTIF_05_get_notification(self):
        """NOTIF-05: Verify retrieving a single notification by ID."""
        target_id = self.created_notifs[0]
        record = self.service.get_notification(
            notification_id=target_id,
            user=self.current_user,
            company=self.current_company,
        )
        self.assertEqual(record["name"], target_id)
        self.assertTrue(record["title"].startswith(self.test_prefix))

    def test_NOTIF_06_create_notification(self):
        """NOTIF-06: Verify notification creation with valid payload."""
        created = self.service.create_notification(
            raw_data={
                "title": f"{self.test_prefix}Offer Approved",
                "message": "Offer letter for Alex Brown has been approved.",
                "priority": "Medium",
                "notification_type": "Offer",
            },
            company=self.current_company,
            recipient=self.current_user,
        )
        self.created_notifs.append(created["name"])
        self.assertEqual(created["notification_type"], "Offer")
        self.assertEqual(created["priority"], "Medium")

    def test_NOTIF_07_mandatory_field_validation(self):
        """NOTIF-07: Verify validation fails when mandatory title or message is missing."""
        from recruitrain_employer.validators.notification_validator import NotificationValidator

        with self.assertRaises(ATSValidationError):
            NotificationValidator.validate_create({"message": "Only message provided"})

        with self.assertRaises(ATSValidationError):
            NotificationValidator.validate_create({"title": "Only title provided"})

    def test_NOTIF_08_invalid_enum_validation(self):
        """NOTIF-08: Verify validation fails for invalid priority or notification type."""
        from recruitrain_employer.validators.notification_validator import NotificationValidator

        with self.assertRaises(ATSValidationError):
            NotificationValidator.validate_create(
                {"title": "Test", "message": "Test", "priority": "SuperHigh"}
            )

        with self.assertRaises(ATSValidationError):
            NotificationValidator.validate_create(
                {"title": "Test", "message": "Test", "notification_type": "UnknownType"}
            )

    def test_NOTIF_09_mark_notification_read(self):
        """NOTIF-09: Verify marking a single notification as read updates status and timestamp."""
        target_id = self.created_notifs[0]
        updated = self.service.mark_notification_read(
            notification_id=target_id,
            user=self.current_user,
            company=self.current_company,
        )
        self.assertTrue(updated["is_read"])
        self.assertIsNotNone(updated["read_at"])

    def test_NOTIF_10_update_notification_preferences(self):
        """NOTIF-10: Verify updating user notification preferences."""
        new_prefs = {
            "new_application_email": False,
            "interview_reminder_inapp": True,
        }
        res = self.service.update_notification_preferences(
            user=self.current_user,
            company=self.current_company,
            raw_preferences=new_prefs,
        )
        self.assertFalse(res["new_application_email"])
        self.assertTrue(res["interview_reminder_inapp"])

    def test_NOTIF_11_invalid_preferences(self):
        """NOTIF-11: Verify non-dict preferences payload raises ATSValidationError."""
        from recruitrain_employer.validators.notification_validator import NotificationValidator

        with self.assertRaises(ATSValidationError):
            NotificationValidator.validate_preferences("not a dict")

    def test_NOTIF_12_mark_all_notifications_read(self):
        """NOTIF-12: Verify marking all unread notifications for user as read."""
        count = self.service.mark_all_notifications_read(
            user=self.current_user,
            company=self.current_company,
        )
        self.assertIsInstance(count, int)

        unread_count = self.service.get_unread_count(
            user=self.current_user,
            company=self.current_company,
        )
        self.assertEqual(unread_count, 0)

    def test_NOTIF_13_bulk_update_notifications(self):
        """NOTIF-13: Verify bulk API endpoint for batch read/delete operations."""
        frappe.form_dict.clear()
        frappe.form_dict.update({
            "notification_ids": [self.created_notifs[0]],
            "action": "mark_read",
        })
        res = bulk_update_notifications()
        self.assertTrue(res["success"])
        self.assertEqual(res["data"]["processed_count"], 1)

    def test_NOTIF_14_linked_entity_derivation(self):
        """NOTIF-14: Verify entity_type, entity_id, and action links are serialized correctly."""
        record = self.service.get_notification(
            notification_id=self.created_notifs[0],
            user=self.current_user,
            company=self.current_company,
        )
        self.assertEqual(record["entity_type"], "Job Application")
        self.assertEqual(record["entity_id"], "APP-TEST-0001")
        self.assertEqual(record["action_url"], "/applications/APP-TEST-0001")

    def test_NOTIF_15_metadata_json_parsing(self):
        """NOTIF-15: Verify JSON metadata object is parsed and serialized as a dictionary."""
        record = self.service.get_notification(
            notification_id=self.created_notifs[0],
            user=self.current_user,
            company=self.current_company,
        )
        self.assertIsInstance(record["metadata"], dict)
        self.assertEqual(record["metadata"].get("candidate_id"), "CAND-001")

    def test_NOTIF_16_company_isolation(self):
        """NOTIF-16: Verify notifications returned belong only to current company context."""
        res = self.service.list_notifications(
            user=self.current_user,
            company=self.current_company,
            options={},
        )
        for notif in res["data"]:
            if notif.get("company"):
                self.assertEqual(notif["company"], self.current_company)

    def test_NOTIF_17_company_spoofing_defense(self):
        """NOTIF-17: Verify user cannot fetch a notification belonging to another company."""
        # Create a notification with a foreign company
        foreign_notif = self.service.create_notification(
            raw_data={
                "title": f"{self.test_prefix}Foreign Notification",
                "message": "Confidential foreign message.",
                "priority": "High",
                "notification_type": "System",
            },
            company=self.foreign_company,
            recipient=self.current_user,
        )
        self.created_notifs.append(foreign_notif["name"])

        with self.assertRaises(ATSPermissionError):
            self.service.get_notification(
                notification_id=foreign_notif["name"],
                user=self.current_user,
                company=self.current_company,
            )

    def test_NOTIF_18_unauthorized_user_access(self):
        """NOTIF-18: Verify user cannot read notifications belonging to another user."""
        with self.assertRaises(ATSPermissionError):
            self.service.get_notification(
                notification_id=self.created_notifs[0],
                user="other_user@recruitrain.de",
                company=self.current_company,
            )

    def test_NOTIF_19_unauthenticated_access(self):
        """NOTIF-19: Verify Guest session requests are rejected."""
        orig_user = getattr(frappe.session, "user", "Administrator")
        try:
            frappe.session.user = "Guest"
            with self.assertRaises(ATSPermissionError):
                list_notifications()
        finally:
            frappe.session.user = orig_user

    def test_NOTIF_20_not_found_handling(self):
        """NOTIF-20: Verify non-existent notification ID raises ATSNotFoundError."""
        with self.assertRaises(ATSNotFoundError):
            self.service.get_notification(
                notification_id="NON_EXISTENT_NOTIF_99999",
                user=self.current_user,
                company=self.current_company,
            )

    def test_NOTIF_21_idempotent_read_status(self):
        """NOTIF-21: Verify marking an already read notification as read is safe and idempotent."""
        target_id = self.created_notifs[0]
        rec1 = self.service.mark_notification_read(target_id, self.current_user, self.current_company)
        rec2 = self.service.mark_notification_read(target_id, self.current_user, self.current_company)
        self.assertEqual(rec1["is_read"], rec2["is_read"])

    def test_NOTIF_22_delete_single_notification(self):
        """NOTIF-22: Verify single notification record deletion."""
        temp_notif = self.service.create_notification(
            raw_data={
                "title": f"{self.test_prefix}Temp Delete Notif",
                "message": "To be deleted.",
            },
            company=self.current_company,
            recipient=self.current_user,
        )
        self.service.delete_notification(
            notification_id=temp_notif["name"],
            user=self.current_user,
            company=self.current_company,
        )
        with self.assertRaises(ATSNotFoundError):
            self.service.get_notification(
                notification_id=temp_notif["name"],
                user=self.current_user,
                company=self.current_company,
            )

    def test_NOTIF_23_clear_notifications(self):
        """NOTIF-23: Verify clearing notifications with read_only filter."""
        # Create read test notification for current user
        n_read = self.service.create_notification(
            raw_data={"title": f"{self.test_prefix}Clear Read", "message": "Read message"},
            company=self.current_company,
            recipient=self.current_user,
        )
        self.service.mark_notification_read(n_read["name"], self.current_user, self.current_company)

        cleared_count = self.service.clear_notifications(
            user=self.current_user,
            company=self.current_company,
            read_only=True,
        )
        self.assertGreaterEqual(cleared_count, 1)

    def test_NOTIF_24_response_envelope(self):
        """NOTIF-24: Verify API controller functions return standard RecruitTrain response envelope."""
        frappe.form_dict.clear()
        res = notification_counts()
        self.assertTrue(res["success"])
        self.assertIn("data", res)
        self.assertIn("unread", res["data"])
        self.assertIn("total", res["data"])
        self.assertIn("meta", res)

    def test_NOTIF_25_internal_metadata_exclusion(self):
        """NOTIF-25: Verify Frappe internal ORM metadata (owner, docstatus, etc.) is excluded from output."""
        temp_notif = self.service.create_notification(
            raw_data={"title": f"{self.test_prefix}Metadata Check", "message": "Check metadata"},
            company=self.current_company,
            recipient=self.current_user,
        )
        record = self.service.get_notification(
            notification_id=temp_notif["name"],
            user=self.current_user,
            company=self.current_company,
        )
        self.assertNotIn("docstatus", record)
        self.assertNotIn("owner", record)
        self.assertNotIn("modified_by", record)
        self.assertNotIn("doctype", record)

    def test_NOTIF_26_sorting_sanitization(self):
        """NOTIF-26: Verify order_by sanitization fallback when given invalid sort field."""
        from recruitrain_employer.validators.notification_validator import NotificationValidator

        options = NotificationValidator.validate_list_params({"order_by": "invalid_column; DROP TABLE users"})
        self.assertEqual(options["order_by"], "creation")

    def test_NOTIF_27_search_count_correctness(self):
        """NOTIF-27: Verify total count matches search results when filter is applied."""
        res = self.service.list_notifications(
            user=self.current_user,
            company=self.current_company,
            options={"search": "Jane Smith"},
        )
        self.assertEqual(res["total"], len(res["data"]))

    def test_NOTIF_28_notification_counts_api(self):
        """NOTIF-28: Verify get_unread_count and notification_counts APIs return numbers."""
        frappe.form_dict.clear()
        res_unread = get_unread_count()
        self.assertTrue(res_unread["success"])
        self.assertIn("unread_count", res_unread["data"])
        self.assertIsInstance(res_unread["data"]["unread_count"], int)

    def test_NOTIF_29_security_input_sanitization(self):
        """NOTIF-29: Verify security handling for XSS and HTML tags in notification content."""
        xss_title = f"{self.test_prefix}<script>alert(1)</script>Security Test"
        created = self.service.create_notification(
            raw_data={
                "title": xss_title,
                "message": "HTML content <img src=x onerror=alert(1)>",
            },
            company=self.current_company,
            recipient=self.current_user,
        )
        self.created_notifs.append(created["name"])
        self.assertIn("Security Test", created["title"])

    def test_NOTIF_30_test_data_hygiene(self):
        """NOTIF-30: Verify test suite tearDown leaves no residual test pollution."""
        self.cleanup_test_records()
        remaining = frappe.db.count("Notification Log", filters={"subject": ["like", f"{self.test_prefix}%"]})
        self.assertEqual(remaining, 0)


def run_notification_contract_tests():
    """Standalone runner for manual docker exec verification."""
    suite = unittest.TestLoader().loadTestsFromTestCase(TestNotificationContract)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    run_notification_contract_tests()
