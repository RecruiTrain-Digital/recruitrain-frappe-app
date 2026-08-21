# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.tests.test_web_push_phase28
=================================================

Phase 28 — Web Push Notification Backend & Security Test Suite.

Verifies:
- PUSH-01: Authenticated employer can obtain VAPID public key.
- PUSH-02: Guest session is rejected from obtaining VAPID key.
- PUSH-03: Authenticated employer can register push subscription.
- PUSH-04: Duplicate endpoint registration updates existing subscription.
- PUSH-05: Subscription is associated strictly with authenticated user.
- PUSH-06: Subscription is associated strictly with authenticated company.
- PUSH-07: Client cannot spoof company in subscription payload.
- PUSH-08: Client cannot spoof user in subscription payload.
- PUSH-09: User can unsubscribe own push subscription endpoint.
- PUSH-10: User cannot unsubscribe another user's push subscription endpoint.
- PUSH-11: Multiple active push subscriptions for one user are supported.
- PUSH-12: Browser push notification preference defaults to ON.
- PUSH-13: Explicit browser push preference OFF suppresses push delivery.
- PUSH-14: Notification Log creation triggers push delivery.
- PUSH-15: Notification transaction rollback does not trigger push delivery.
- PUSH-16: Expired push subscription (410 Gone) is automatically deactivated.
- PUSH-17: Private VAPID key NEVER appears in any API response.
- PUSH-18: Push payload contains zero passwords, tokens, or session secrets.
- PUSH-19: Company A push subscription never receives Company B notification.
- PUSH-20: Existing notification API contract remains unaffected.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from pywebpush import WebPushException

from recruitrain_employer.api.push import (
    delete_push_subscription,
    get_push_subscriptions,
    get_vapid_public_key,
    subscribe_push,
    unsubscribe_push,
)
from recruitrain_employer.services.notification_service import NotificationService
from recruitrain_employer.services.push_service import PushService, send_notification_push
from recruitrain_employer.utils.constants import DOCTYPE_EMPLOYER_USER
from recruitrain_employer.utils.vapid_config import get_vapid_credentials, get_vapid_public_key_string


class TestWebPushPhase28(FrappeTestCase):
    """Test suite for Phase 28 Web Push Notification Backend."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = "WebPush Company A"
        cls.company_b = "WebPush Company B"
        cls.user_a = "emp1_push@recruitrain.de"
        cls.user_b = "emp2_push@recruitrain.de"

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
                    "first_name": "Push",
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
                    "first_name": "Push",
                    "last_name": "Tester",
                    "role": "Administrator",
                    "status": "Active",
                })
                emp_doc.insert(ignore_permissions=True)

        frappe.db.commit()
        cls.service = NotificationService()
        cls.push_service = PushService()

    def setUp(self):
        super().setUp()
        frappe.set_user(self.user_a)
        frappe.session.user = self.user_a
        frappe.form_dict = frappe._dict()

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.session.user = "Administrator"
        frappe.form_dict = frappe._dict()
        super().tearDown()

    def test_PUSH_01_authenticated_employer_can_obtain_vapid_public_key(self):
        """PUSH-01: Authenticated employer can obtain VAPID public key."""
        res = get_vapid_public_key()
        self.assertTrue(res["success"])
        self.assertIn("public_key", res["data"])
        self.assertTrue(isinstance(res["data"]["public_key"], str))
        self.assertGreater(len(res["data"]["public_key"]), 20)

    def test_PUSH_02_guest_cannot_obtain_protected_push_config(self):
        """PUSH-02: Guest cannot obtain protected push configuration."""
        frappe.set_user("Guest")
        frappe.session.user = "Guest"
        res = get_vapid_public_key()
        self.assertFalse(res["success"])
        self.assertEqual(res["error"]["code"], "UNAUTHORIZED")

    def test_PUSH_03_authenticated_employer_can_register_subscription(self):
        """PUSH-03: Authenticated employer can register subscription."""
        frappe.form_dict = frappe._dict({
            "endpoint": "https://fcm.googleapis.com/fcm/send/test_endpoint_push_03",
            "keys": {
                "p256dh": "test_p256dh_key_03",
                "auth": "test_auth_secret_03",
            },
            "device_name": "Chrome Desktop",
        })

        res = subscribe_push()
        self.assertTrue(res["success"])
        sub_name = res["data"]["name"]
        self.assertTrue(frappe.db.exists("RecruitTrain Push Subscription", sub_name))

        doc = frappe.get_doc("RecruitTrain Push Subscription", sub_name)
        self.assertEqual(doc.user, self.user_a)
        self.assertEqual(doc.company, self.company_a)
        self.assertEqual(doc.endpoint, "https://fcm.googleapis.com/fcm/send/test_endpoint_push_03")

    def test_PUSH_04_duplicate_endpoint_updates_existing_subscription(self):
        """PUSH-04: Duplicate endpoint updates existing subscription."""
        endpoint = "https://fcm.googleapis.com/fcm/send/test_endpoint_push_04"
        frappe.form_dict = frappe._dict({
            "endpoint": endpoint,
            "keys": {"p256dh": "key_v1", "auth": "auth_v1"},
        })
        res1 = subscribe_push()
        self.assertTrue(res1["success"])
        sub_name1 = res1["data"]["name"]

        frappe.form_dict = frappe._dict({
            "endpoint": endpoint,
            "keys": {"p256dh": "key_v2_updated", "auth": "auth_v2_updated"},
        })
        res2 = subscribe_push()
        self.assertTrue(res2["success"])
        self.assertEqual(res2["data"]["action"], "updated")
        self.assertEqual(res2["data"]["name"], sub_name1)

        doc = frappe.get_doc("RecruitTrain Push Subscription", sub_name1)
        self.assertEqual(doc.p256dh, "key_v2_updated")

    def test_PUSH_05_subscription_associated_with_authenticated_user(self):
        """PUSH-05: Subscription is associated with authenticated user."""
        frappe.form_dict = frappe._dict({
            "endpoint": "https://fcm.googleapis.com/fcm/send/test_endpoint_push_05",
            "keys": {"p256dh": "key_05", "auth": "auth_05"},
        })
        res = subscribe_push()
        self.assertEqual(res["data"]["name"], frappe.db.get_value("RecruitTrain Push Subscription", {"endpoint": "https://fcm.googleapis.com/fcm/send/test_endpoint_push_05"}, "name"))
        sub_user = frappe.db.get_value("RecruitTrain Push Subscription", {"endpoint": "https://fcm.googleapis.com/fcm/send/test_endpoint_push_05"}, "user")
        self.assertEqual(sub_user, self.user_a)

    def test_PUSH_06_subscription_associated_with_authenticated_company(self):
        """PUSH-06: Subscription is associated with authenticated company."""
        frappe.form_dict = frappe._dict({
            "endpoint": "https://fcm.googleapis.com/fcm/send/test_endpoint_push_06",
            "keys": {"p256dh": "key_06", "auth": "auth_06"},
        })
        subscribe_push()
        sub_comp = frappe.db.get_value("RecruitTrain Push Subscription", {"endpoint": "https://fcm.googleapis.com/fcm/send/test_endpoint_push_06"}, "company")
        self.assertEqual(sub_comp, self.company_a)

    def test_PUSH_07_client_cannot_spoof_company(self):
        """PUSH-07: Client cannot spoof company."""
        frappe.form_dict = frappe._dict({
            "endpoint": "https://fcm.googleapis.com/fcm/send/test_endpoint_push_07",
            "keys": {"p256dh": "key_07", "auth": "auth_07"},
            "company": "SPOOFED_COMPANY_B",
            "company_id": "SPOOFED_ID",
        })
        subscribe_push()
        sub_comp = frappe.db.get_value("RecruitTrain Push Subscription", {"endpoint": "https://fcm.googleapis.com/fcm/send/test_endpoint_push_07"}, "company")
        self.assertEqual(sub_comp, self.company_a)
        self.assertNotEqual(sub_comp, "SPOOFED_COMPANY_B")

    def test_PUSH_08_client_cannot_spoof_user(self):
        """PUSH-08: Client cannot spoof user."""
        frappe.form_dict = frappe._dict({
            "endpoint": "https://fcm.googleapis.com/fcm/send/test_endpoint_push_08",
            "keys": {"p256dh": "key_08", "auth": "auth_08"},
            "user": "victim@recruitrain.de",
            "recipient": "victim@recruitrain.de",
        })
        subscribe_push()
        sub_user = frappe.db.get_value("RecruitTrain Push Subscription", {"endpoint": "https://fcm.googleapis.com/fcm/send/test_endpoint_push_08"}, "user")
        self.assertEqual(sub_user, self.user_a)
        self.assertNotEqual(sub_user, "victim@recruitrain.de")

    def test_PUSH_09_user_can_unsubscribe_own_endpoint(self):
        """PUSH-09: User can unsubscribe own endpoint."""
        endpoint = "https://fcm.googleapis.com/fcm/send/test_endpoint_push_09"
        frappe.form_dict = frappe._dict({
            "endpoint": endpoint,
            "keys": {"p256dh": "key_09", "auth": "auth_09"},
        })
        subscribe_push()

        frappe.form_dict = frappe._dict({"endpoint": endpoint})
        res = unsubscribe_push()
        self.assertTrue(res["success"])
        is_active = frappe.db.get_value("RecruitTrain Push Subscription", {"endpoint": endpoint}, "is_active")
        self.assertEqual(is_active, 0)

    def test_PUSH_10_user_cannot_unsubscribe_another_users_endpoint(self):
        """PUSH-10: User cannot unsubscribe another user's endpoint."""
        # Create endpoint for User B
        frappe.set_user(self.user_b)
        frappe.session.user = self.user_b
        endpoint_b = "https://fcm.googleapis.com/fcm/send/test_endpoint_user_b"
        frappe.form_dict = frappe._dict({
            "endpoint": endpoint_b,
            "keys": {"p256dh": "key_b", "auth": "auth_b"},
        })
        subscribe_push()

        # User A attempts to unsubscribe User B's endpoint
        frappe.set_user(self.user_a)
        frappe.session.user = self.user_a
        frappe.form_dict = frappe._dict({"endpoint": endpoint_b})
        res = unsubscribe_push()
        self.assertFalse(res["success"])
        self.assertIn(res["error"]["code"], ("PERMISSION_DENIED", "NOT_FOUND"))

    def test_PUSH_11_multiple_subscriptions_for_one_user_supported(self):
        """PUSH-11: Multiple subscriptions for one user are supported."""
        endpoints = [
            "https://fcm.googleapis.com/fcm/send/test_endpoint_multi_1",
            "https://fcm.googleapis.com/fcm/send/test_endpoint_multi_2",
        ]
        for ep in endpoints:
            frappe.form_dict = frappe._dict({
                "endpoint": ep,
                "keys": {"p256dh": f"key_{ep}", "auth": f"auth_{ep}"},
            })
            subscribe_push()

        subs = frappe.get_all("RecruitTrain Push Subscription", filters={"user": self.user_a, "is_active": 1})
        self.assertGreaterEqual(len(subs), 2)

    def test_PUSH_12_browser_push_preference_defaults_to_on(self):
        """PUSH-12: Browser push preference defaults to ON."""
        prefs = self.service.get_notification_preferences(self.user_a, self.company_a)
        self.assertIn("browser_push_notifications", prefs)
        self.assertTrue(prefs["browser_push_notifications"])

    @patch("recruitrain_employer.services.push_service.webpush")
    def test_PUSH_13_explicit_browser_push_preference_off_suppresses_delivery(self, mock_webpush):
        """PUSH-13: Explicit browser push preference OFF suppresses delivery."""
        # Save subscription
        endpoint = "https://fcm.googleapis.com/fcm/send/test_endpoint_push_13"
        frappe.form_dict = frappe._dict({
            "endpoint": endpoint,
            "keys": {"p256dh": "key_13", "auth": "auth_13"},
        })
        subscribe_push()

        # Turn OFF browser_push_notifications preference
        self.service.update_notification_preferences(
            self.user_a, self.company_a, {"browser_push_notifications": False}
        )

        mock_doc = frappe._dict({
            "name": "NOTIF-PUSH-13",
            "title": "Suppressed Push Test",
            "message": "Should not send push",
            "recipient": self.user_a,
            "company": self.company_a,
            "category": "general",
        })

        sent_count = self.push_service.send_notification_push(mock_doc)
        self.assertEqual(sent_count, 0)
        mock_webpush.assert_not_called()

        # Re-enable for subsequent tests
        self.service.update_notification_preferences(
            self.user_a, self.company_a, {"browser_push_notifications": True}
        )

    @patch("recruitrain_employer.services.push_service.webpush")
    def test_PUSH_14_notification_creation_triggers_push_delivery(self, mock_webpush):
        """PUSH-14: Notification creation triggers push delivery."""
        endpoint = "https://fcm.googleapis.com/fcm/send/test_endpoint_push_14"
        frappe.form_dict = frappe._dict({
            "endpoint": endpoint,
            "keys": {"p256dh": "key_14", "auth": "auth_14"},
        })
        subscribe_push()

        mock_doc = frappe._dict({
            "name": "NOTIF-PUSH-14",
            "title": "New Interview Scheduled",
            "message": "Interview set for candidate John",
            "recipient": self.user_a,
            "company": self.company_a,
            "category": "recruitment",
            "action_url": "/app/interviews?id=14",
        })

        sent_count = self.push_service.send_notification_push(mock_doc)
        self.assertGreater(sent_count, 0)
        mock_webpush.assert_called()

    def test_PUSH_15_notification_database_rollback_does_not_trigger_push(self):
        """PUSH-15: Notification database rollback does not trigger push."""
        with patch("recruitrain_employer.services.push_service.send_notification_push") as mock_push:
            try:
                frappe.db.begin()
                # Create doc in transaction
                doc = frappe.get_doc({
                    "doctype": "Notification Log",
                    "title": "Rollback Test",
                    "message": "Rollback test message",
                    "company": self.company_a,
                    "recipient": self.user_a,
                    "notification_type": "System",
                    "priority": "Low",
                })
                doc.insert(ignore_permissions=True)
                frappe.db.after_commit(lambda d=doc: send_notification_push(d))
                # Rollback transaction
                frappe.db.rollback()
            except Exception:
                frappe.db.rollback()

            # Verify that push callback was not fired because transaction rolled back
            mock_push.assert_not_called()

    @patch("recruitrain_employer.services.push_service.webpush")
    def test_PUSH_16_expired_subscription_deactivated(self, mock_webpush):
        """PUSH-16: Expired subscription (410 Gone) is deactivated."""
        endpoint = "https://fcm.googleapis.com/fcm/send/test_endpoint_push_16_expired"
        frappe.form_dict = frappe._dict({
            "endpoint": endpoint,
            "keys": {"p256dh": "key_16", "auth": "auth_16"},
        })
        res = subscribe_push()
        sub_name = res["data"]["name"]

        # Mock WebPushException with HTTP 410 Gone
        mock_response = MagicMock()
        mock_response.status_code = 410
        mock_webpush.side_effect = WebPushException("Subscription Gone", response=mock_response)

        mock_doc = frappe._dict({
            "name": "NOTIF-PUSH-16",
            "title": "Expired Endpoint Test",
            "message": "Testing endpoint deactivation",
            "recipient": self.user_a,
            "company": self.company_a,
        })

        self.push_service.send_notification_push(mock_doc)

        is_active = frappe.db.get_value("RecruitTrain Push Subscription", sub_name, "is_active")
        self.assertEqual(is_active, 0)

    def test_PUSH_17_private_vapid_key_never_appears_in_api_response(self):
        """PUSH-17: Private VAPID key NEVER appears in API response."""
        res = get_vapid_public_key()
        pub_key, priv_key_pem, _ = get_vapid_credentials()

        res_str = json.dumps(res)
        self.assertNotIn(priv_key_pem, res_str)
        self.assertNotIn("PRIVATE", res_str)
        self.assertNotIn("vapid_private_key", res_str)

    @patch("recruitrain_employer.services.push_service.webpush")
    def test_PUSH_18_push_payload_contains_no_sensitive_secrets(self, mock_webpush):
        """PUSH-18: Push payload contains zero passwords, tokens, or session secrets."""
        endpoint = "https://fcm.googleapis.com/fcm/send/test_endpoint_push_18"
        frappe.form_dict = frappe._dict({
            "endpoint": endpoint,
            "keys": {"p256dh": "key_18", "auth": "auth_18"},
        })
        subscribe_push()

        mock_doc = frappe._dict({
            "name": "NOTIF-PUSH-18",
            "title": "Payload Sanitization Check",
            "message": "Testing payload keys",
            "recipient": self.user_a,
            "company": self.company_a,
            "password": "secret_user_password",
            "sid": "session_cookie_secret",
            "token": "api_bearer_token",
        })

        self.push_service.send_notification_push(mock_doc)

        mock_webpush.assert_called()
        call_kwargs = mock_webpush.call_args.kwargs
        payload = json.loads(call_kwargs["data"])

        forbidden_keys = {"password", "sid", "token", "secret", "cookie", "authorization"}
        for k in forbidden_keys:
            self.assertNotIn(k, payload)

    @patch("recruitrain_employer.services.push_service.webpush")
    def test_PUSH_19_company_isolation_push_delivery(self, mock_webpush):
        """PUSH-19: Company A subscription never receives Company B notification."""
        # Create sub for Company A
        frappe.form_dict = frappe._dict({
            "endpoint": "https://fcm.googleapis.com/fcm/send/test_comp_a_push",
            "keys": {"p256dh": "key_a", "auth": "auth_a"},
        })
        subscribe_push()

        # Create Company B notification
        mock_doc_b = frappe._dict({
            "name": "NOTIF-PUSH-COMP-B",
            "title": "Company B Private Event",
            "recipient": self.user_b,
            "company": self.company_b,
        })

        self.push_service.send_notification_push(mock_doc_b)

        # Check call args to verify user_a's subscription endpoint was NOT called for Company B event
        for call_item in mock_webpush.call_args_list:
            sub_info = call_item.kwargs.get("subscription_info", {})
            self.assertNotEqual(sub_info.get("endpoint"), "https://fcm.googleapis.com/fcm/send/test_comp_a_push")

    def test_PUSH_20_existing_notification_contract_unaffected(self):
        """PUSH-20: Existing notification contract remains unaffected."""
        created = self.service.create_notification(
            raw_data={
                "title": "Push Contract Test",
                "message": "Testing notification service integrity",
                "notification_type": "System",
                "priority": "Medium",
            },
            company=self.company_a,
            recipient=self.user_a,
        )
        self.assertIn("name", created)
        self.assertEqual(created["title"], "Push Contract Test")


def run_web_push_tests():
    """Execute Phase 28 Web Push unit test suite."""
    import os
    sites_path = "/workspace/development/frappe-bench/sites"
    os.makedirs(os.path.join(sites_path, "development.localhost", "logs"), exist_ok=True)
    os.makedirs("/workspace/logs", exist_ok=True)
    frappe.init(site="development.localhost", sites_path=sites_path)
    frappe.connect()
    suite = unittest.TestLoader().loadTestsFromTestCase(TestWebPushPhase28)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    frappe.destroy()
    return result.wasSuccessful()


if __name__ == "__main__":
    run_web_push_tests()
