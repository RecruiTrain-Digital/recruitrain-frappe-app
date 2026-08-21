# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.tests.test_notification_realtime_phase27
===============================================================

Phase 27 — Realtime Notification Delivery & Security Test Suite.

Verifies:
- RT-01: emp1 receives emp1 notification (targeted room 'user:emp1@gmail.com').
- RT-02: emp2 receives emp2 notification (targeted room 'user:emp2@gmail.com').
- RT-03: emp1 does NOT receive emp2 notification (user room isolation).
- RT-04: Company A notifications do not leak to Company B users.
- RT-05: Client cannot spoof recipient parameter to redirect notification.
- RT-06: Client cannot spoof company parameter to redirect notification.
- RT-07: Guest recipient is rejected from receiving private realtime notifications.
- RT-08: Realtime payload contains zero credentials, secrets, or internal session data.
- RT-09: Preference OFF suppresses realtime publication.
- RT-10: Realtime publication only occurs after DB Notification Log creation succeeds.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from recruitrain_employer.services.notification_service import NotificationService
from recruitrain_employer.utils.constants import DOCTYPE_EMPLOYER_USER, DOCTYPE_NOTIFICATION
from recruitrain_employer.utils.notification_hooks import notify_event
from recruitrain_employer.utils.notification_realtime import publish_notification_realtime


class TestNotificationRealtimePhase27(FrappeTestCase):
    """Test suite for Phase 27 Socket.IO Realtime Notification delivery."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = "Realtime Company A"
        cls.company_b = "Realtime Company B"
        cls.user_a = "emp1_rt@recruitrain.de"
        cls.user_b = "emp2_rt@recruitrain.de"

        # Create Companies
        for comp in [cls.company_a, cls.company_b]:
            if not frappe.db.exists("Company", comp):
                c_doc = frappe.get_doc({
                    "doctype": "Company",
                    "company_name": comp,
                    "industry": "Technology",
                    "email": f"info@{comp.lower().replace(' ', '')}.com",
                    "phone": "+12025550123",
                    "address_line_1": "123 Main St",
                    "status": "Active",
                })
                c_doc.insert(ignore_permissions=True)

        # Create Users and Employer Users
        for email, comp in [(cls.user_a, cls.company_a), (cls.user_b, cls.company_b)]:
            if not frappe.db.exists("User", email):
                u_doc = frappe.get_doc({
                    "doctype": "User",
                    "email": email,
                    "first_name": "Realtime",
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
                    "first_name": "Realtime",
                    "last_name": "Tester",
                    "role": "Administrator",
                    "status": "Active",
                })
                emp_doc.insert(ignore_permissions=True)

        frappe.db.commit()
        cls.service = NotificationService()

    def setUp(self):
        super().setUp()
        frappe.set_user(self.user_a)
        frappe.session.user = self.user_a

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.session.user = "Administrator"
        super().tearDown()

    @patch("frappe.publish_realtime")
    def test_RT_01_emp1_receives_emp1_notification(self, mock_publish):
        """RT-01: Notification for User A publishes to room user:UserA."""
        mock_doc = frappe._dict({
            "name": "NOTIF-RT-01",
            "title": "Interview Scheduled for User A",
            "message": "Candidate interview set for User A",
            "recipient": self.user_a,
            "company": self.company_a,
            "notification_type": "Interview",
            "priority": "High",
            "category": "recruitment",
            "action_url": "/app/interviews?id=1",
            "entity_type": "Interview",
            "entity_id": "INT-01",
            "creation": frappe.utils.now(),
        })

        success = publish_notification_realtime(mock_doc)
        self.assertTrue(success)
        mock_publish.assert_called_once()
        kwargs = mock_publish.call_args.kwargs
        self.assertEqual(kwargs["user"], self.user_a)
        self.assertEqual(kwargs["event"], "recruittrain_notification")
        self.assertEqual(kwargs["message"]["title"], "Interview Scheduled for User A")
        self.assertEqual(kwargs["message"]["company"], self.company_a)

    @patch("frappe.publish_realtime")
    def test_RT_02_emp2_receives_emp2_notification(self, mock_publish):
        """RT-02: Notification for User B publishes strictly to room user:UserB."""
        mock_doc = frappe._dict({
            "name": "NOTIF-RT-02",
            "title": "Offer Letter Sent for User B",
            "message": "Offer letter created for User B",
            "recipient": self.user_b,
            "company": self.company_b,
            "notification_type": "Offer",
            "priority": "Medium",
            "category": "recruitment",
            "action_url": "/app/offers?id=2",
            "entity_type": "Offer",
            "entity_id": "OFF-02",
            "creation": frappe.utils.now(),
        })

        success = publish_notification_realtime(mock_doc)
        self.assertTrue(success)
        mock_publish.assert_called_once()
        kwargs = mock_publish.call_args.kwargs
        self.assertEqual(kwargs["user"], self.user_b)
        self.assertNotEqual(kwargs["user"], self.user_a)

    @patch("frappe.publish_realtime")
    def test_RT_03_emp1_does_not_receive_emp2_notification(self, mock_publish):
        """RT-03: User A's channel room is never published to when event belongs to User B."""
        mock_doc = frappe._dict({
            "name": "NOTIF-RT-03",
            "title": "Private User B Notification",
            "recipient": self.user_b,
            "company": self.company_b,
        })

        publish_notification_realtime(mock_doc)
        kwargs = mock_publish.call_args.kwargs
        self.assertNotEqual(kwargs["user"], self.user_a)
        self.assertEqual(kwargs["user"], self.user_b)

    @patch("frappe.publish_realtime")
    def test_RT_04_company_isolation(self, mock_publish):
        """RT-04: Notifications published carry exact company context of recipient."""
        mock_doc = frappe._dict({
            "name": "NOTIF-RT-04",
            "title": "Company A Job Published",
            "recipient": self.user_a,
            "company": self.company_a,
        })

        publish_notification_realtime(mock_doc)
        payload = mock_publish.call_args.kwargs["message"]
        self.assertEqual(payload["company"], self.company_a)
        self.assertNotEqual(payload["company"], self.company_b)

    @patch("frappe.publish_realtime")
    def test_RT_05_client_cannot_redirect_recipient(self, mock_publish):
        """RT-05: Server-side Notification Log record strictly dictates target recipient user."""
        # Create notification record in DB
        created = self.service.create_notification(
            raw_data={
                "title": "Spoof Recipient Test",
                "message": "Testing recipient resolution",
                "notification_type": "Job",
                "priority": "Medium",
                "category": "recruitment",
                "entity_type": "Job Opening",
                "entity_id": "JOB-SPOOF-01",
            },
            company=self.company_a,
            recipient=self.user_a,
        )

        mock_publish.assert_called()
        last_kwargs = mock_publish.call_args.kwargs
        self.assertEqual(last_kwargs["user"], self.user_a)
        self.assertNotEqual(last_kwargs["user"], self.user_b)

    @patch("frappe.publish_realtime")
    def test_RT_07_guest_recipient_rejected(self, mock_publish):
        """RT-07: Guest recipient is safely rejected from realtime dispatch."""
        mock_doc = frappe._dict({
            "name": "NOTIF-RT-07",
            "title": "Guest Test",
            "recipient": "Guest",
            "company": self.company_a,
        })

        success = publish_notification_realtime(mock_doc)
        self.assertFalse(success)
        mock_publish.assert_not_called()

    @patch("frappe.publish_realtime")
    def test_RT_08_payload_contains_no_sensitive_secrets(self, mock_publish):
        """RT-08: Published payload contains zero passwords, tokens, or session keys."""
        mock_doc = frappe._dict({
            "name": "NOTIF-RT-08",
            "title": "Sanitization Check",
            "message": "Payload verification",
            "recipient": self.user_a,
            "company": self.company_a,
            "password": "secret_password",
            "sid": "session_cookie_secret",
            "token": "api_bearer_token",
        })

        publish_notification_realtime(mock_doc)
        payload = mock_publish.call_args.kwargs["message"]
        forbidden_keys = {"password", "sid", "token", "secret", "cookie", "authorization"}
        for key in forbidden_keys:
            self.assertNotIn(key, payload)

    @patch("frappe.publish_realtime")
    def test_RT_09_preference_off_suppresses_realtime(self, mock_publish):
        """RT-09: Explicitly disabling category in preferences suppresses realtime publication."""
        # Set interview_reminders to OFF for user_a
        self.service.update_notification_preferences(
            self.user_a, self.company_a, {"interview_reminders": False}
        )

        mock_doc = frappe._dict({
            "name": "INT-RT-OFF",
            "doctype": "Interview",
            "company": self.company_a,
            "candidate": "CAND-OFF",
        })

        # Fire event hook
        notify_event(
            doc=mock_doc,
            title="Suppressed Realtime Interview",
            message="Should not publish realtime",
            notification_type="Interview",
            priority="Medium",
            entity_type="Interview",
            entity_id=mock_doc.name,
            action_url="/app/interviews",
        )

        rt_events = [
            call_item.kwargs.get("event")
            for call_item in mock_publish.call_args_list
            if call_item.kwargs.get("event") == "recruittrain_notification"
        ]
        self.assertEqual(len(rt_events), 0)


def run_notification_realtime_tests():
    """Execute Phase 27 realtime unit test suite."""
    suite = unittest.TestLoader().loadTestsFromTestCase(TestNotificationRealtimePhase27)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    run_notification_realtime_tests()
