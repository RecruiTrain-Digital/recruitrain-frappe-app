# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.tests.test_notification_events_phase26_2
===============================================================

Notification Event Generation & Trigger Verification Suite (NOTIF-EVENT-01 to NOTIF-EVENT-20).

Validates end-to-end event flow:
Real Business Event -> DocType Hook -> NotificationService -> Notification Log -> list_notifications API
"""

from __future__ import annotations

import unittest
import frappe
from frappe.utils import now_datetime

from recruitrain_employer.api.notifications import list_notifications, get_unread_count
from recruitrain_employer.services.notification_service import NotificationService
from recruitrain_employer.utils.constants import DOCTYPE_NOTIFICATION
from recruitrain_employer.utils.permissions import get_current_company, get_current_employer_user


class TestNotificationEventsPhase262(unittest.TestCase):
    """Notification Event Triggers Test Suite (NOTIF-EVENT-01..20)."""

    @classmethod
    def setUpClass(cls):
        cls.current_company = get_current_company()
        user_info = get_current_employer_user()
        cls.current_user = user_info["user"]
        cls.service = NotificationService()

        cls.prefix = "EVENT-TEST-VERIFY-"
        cls.cleanup_test_records()

        # Provision Foreign Company for isolation tests
        cls.foreign_company = f"{cls.prefix}Foreign Corp"
        if not frappe.db.exists("Company", cls.foreign_company):
            c = frappe.new_doc("Company")
            c.company_name = cls.foreign_company
            c.abbr = "ETFC"
            c.default_currency = "USD"
            c.country = "United States"
            c.email = "eventforeign@example.com"
            c.phone = "+12025550999"
            c.address_line_1 = "999 Foreign Ave"
            c.insert(ignore_permissions=True)

        # Ensure Employment Type exists for testing
        if not frappe.db.exists("Employment Type", "Full-time"):
            try:
                frappe.get_doc({"doctype": "Employment Type", "employment_type_name": "Full-time"}).insert(ignore_permissions=True)
            except Exception:
                pass

        # Ensure active subscriptions for testing and reset usage counters
        for comp_name in (cls.current_company, cls.foreign_company):
            sub_name = frappe.db.get_value("Company Subscription", {"company": comp_name}, "name")
            if sub_name:
                frappe.db.set_value("Company Subscription", sub_name, "status", "Active")
                frappe.db.set_value("Company Subscription", sub_name, "end_date", "2030-12-31")

        if frappe.db.exists("DocType", "Subscription Usage"):
            frappe.db.sql(
                "UPDATE `tabSubscription Usage` SET current_active_jobs = 0, current_candidates = 0 WHERE company IN (%s, %s)",
                (cls.current_company, cls.foreign_company),
            )
            frappe.db.commit()

        # Create prerequisite candidate & job
        cls.cand_name = f"{cls.prefix}Candidate John"
        cls.cand_doc = frappe.get_doc({
            "doctype": "Candidate",
            "candidate_name": cls.cand_name,
            "first_name": "John",
            "last_name": "Doe",
            "email": f"john.doe.{frappe.generate_hash(length=6)}@example.com",
            "company": cls.current_company,
            "status": "Active",
            "date_of_birth": "1990-01-01",
            "mobile_no": "+12025550199",
            "address_line_1": "123 Main St",
            "city": "Berlin",
            "state": "Berlin",
        }).insert(ignore_permissions=True)

        cls.job_title = f"{cls.prefix}Senior Software Engineer"
        cls.job_doc = frappe.get_doc({
            "doctype": "Job Opening",
            "job_code": f"JOB-CODE-{frappe.generate_hash(length=6)}",
            "job_title": cls.job_title,
            "company": cls.current_company,
            "status": "Open",
            "employment_type": "Full-time",
            "number_of_openings": 1,
            "job_summary": "Sample summary",
            "responsibilities": "Sample responsibilities",
            "requirements": "Sample requirements",
        }).insert(ignore_permissions=True)

        cls.app_doc = frappe.get_doc({
            "doctype": "Job Application",
            "candidate": cls.cand_doc.name,
            "job_opening": cls.job_doc.name,
            "company": cls.current_company,
            "current_stage": "Screening",
            "status": "Open",
            "resume": "/files/sample_resume.pdf",
        }).insert(ignore_permissions=True)

        frappe.db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.cleanup_test_records()

    @classmethod
    def cleanup_test_records(cls):
        prefix = "EVENT-TEST-VERIFY-"
        frappe.db.delete("Candidate", {"candidate_name": ["like", f"{prefix}%"]})
        frappe.db.delete("Job Opening", {"job_title": ["like", f"{prefix}%"]})
        frappe.db.delete("Job Application", {"company": ["like", f"{prefix}%"]})
        frappe.db.delete("Interview", {"interview_name": ["like", f"{prefix}%"]})
        frappe.db.delete("Offer", {"offer_name": ["like", f"{prefix}%"]})
        frappe.db.delete("Company", {"company_name": ["like", f"{prefix}%"]})

        meta = frappe.get_meta(DOCTYPE_NOTIFICATION)
        subj_field = "subject" if meta.has_field("subject") else "title"
        frappe.db.delete(DOCTYPE_NOTIFICATION, {subj_field: ["like", "%scheduled%"]})
        frappe.db.delete(DOCTYPE_NOTIFICATION, {subj_field: ["like", "%rescheduled%"]})
        frappe.db.delete(DOCTYPE_NOTIFICATION, {subj_field: ["like", "%cancelled%"]})
        frappe.db.delete(DOCTYPE_NOTIFICATION, {subj_field: ["like", "%created%"]})
        frappe.db.delete(DOCTYPE_NOTIFICATION, {subj_field: ["like", "%published%"]})
        frappe.db.delete(DOCTYPE_NOTIFICATION, {subj_field: ["like", "%received%"]})
        frappe.db.delete(DOCTYPE_NOTIFICATION, {subj_field: ["like", "%stage%"]})
        frappe.db.delete(DOCTYPE_NOTIFICATION, {subj_field: ["like", "%updated%"]})
        frappe.db.commit()

    def test_NOTIF_EVENT_01_interview_creation(self):
        """NOTIF-EVENT-01: Interview creation generates persistent notification."""
        int_doc = frappe.get_doc({
            "doctype": "Interview",
            "interview_name": f"{self.prefix}INT-001",
            "job_application": self.app_doc.name,
            "candidate": self.cand_doc.name,
            "job_opening": self.job_doc.name,
            "company": self.current_company,
            "interview_type": "Technical",
            "interviewer": self.current_user,
            "status": "Scheduled",
            "scheduled_on": now_datetime(),
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        notifs = self.service.list_notifications(
            user=self.current_user,
            company=self.current_company,
            options={"search": int_doc.name},
        )
        self.assertGreaterEqual(notifs["total"], 1)

    def test_NOTIF_EVENT_02_interview_id(self):
        """NOTIF-EVENT-02: Notification contains correct Interview entity ID."""
        int_id = f"{self.prefix}INT-ID-CHECK"
        int_doc = frappe.get_doc({
            "doctype": "Interview",
            "interview_name": int_id,
            "job_application": self.app_doc.name,
            "candidate": self.cand_doc.name,
            "job_opening": self.job_doc.name,
            "company": self.current_company,
            "interview_type": "HR",
            "interviewer": self.current_user,
            "status": "Scheduled",
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        record = self.service.list_notifications(
            user=self.current_user,
            company=self.current_company,
            options={"search": int_id},
        )
        self.assertEqual(record["data"][0]["entity_id"], int_id)

    def test_NOTIF_EVENT_03_candidate_name_in_message(self):
        """NOTIF-EVENT-03: Notification contains candidate name in message body."""
        int_id = f"{self.prefix}INT-CAND-CHECK"
        frappe.get_doc({
            "doctype": "Interview",
            "interview_name": int_id,
            "job_application": self.app_doc.name,
            "candidate": self.cand_doc.name,
            "job_opening": self.job_doc.name,
            "company": self.current_company,
            "interview_type": "Phone",
            "interviewer": self.current_user,
            "status": "Scheduled",
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        record = self.service.list_notifications(
            user=self.current_user,
            company=self.current_company,
            options={"search": int_id},
        )
        self.assertIn("John Doe", record["data"][0]["message"])

    def test_NOTIF_EVENT_04_job_title_in_message(self):
        """NOTIF-EVENT-04: Notification contains job title in message body."""
        int_id = f"{self.prefix}INT-JOB-CHECK"
        frappe.get_doc({
            "doctype": "Interview",
            "interview_name": int_id,
            "job_application": self.app_doc.name,
            "candidate": self.cand_doc.name,
            "job_opening": self.job_doc.name,
            "company": self.current_company,
            "interview_type": "Managerial",
            "interviewer": self.current_user,
            "status": "Scheduled",
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        record = self.service.list_notifications(
            user=self.current_user,
            company=self.current_company,
            options={"search": int_id},
        )
        self.assertIn(self.job_title, record["data"][0]["message"])

    def test_NOTIF_EVENT_05_company_isolation_on_event(self):
        """NOTIF-EVENT-05: Generated notification is scoped to the document's company."""
        int_id = f"{self.prefix}INT-COMP-CHECK"
        frappe.get_doc({
            "doctype": "Interview",
            "interview_name": int_id,
            "job_application": self.app_doc.name,
            "candidate": self.cand_doc.name,
            "job_opening": self.job_doc.name,
            "company": self.current_company,
            "interview_type": "Final",
            "interviewer": self.current_user,
            "status": "Scheduled",
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        record = self.service.list_notifications(
            user=self.current_user,
            company=self.current_company,
            options={"search": int_id},
        )
        self.assertEqual(record["data"][0]["company"], self.current_company)

    def test_NOTIF_EVENT_06_recipient_resolution(self):
        """NOTIF-EVENT-06: Notification recipient is correctly set to active employer user."""
        int_id = f"{self.prefix}INT-RECIP-CHECK"
        frappe.get_doc({
            "doctype": "Interview",
            "interview_name": int_id,
            "job_application": self.app_doc.name,
            "candidate": self.cand_doc.name,
            "job_opening": self.job_doc.name,
            "company": self.current_company,
            "interview_type": "Technical",
            "interviewer": self.current_user,
            "status": "Scheduled",
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        record = self.service.list_notifications(
            user=self.current_user,
            company=self.current_company,
            options={"search": int_id},
        )
        self.assertEqual(record["data"][0]["recipient"], self.current_user)

    def test_NOTIF_EVENT_07_interview_reschedule(self):
        """NOTIF-EVENT-07: Rescheduling an interview triggers a notification."""
        int_doc = frappe.get_doc({
            "doctype": "Interview",
            "interview_name": f"{self.prefix}INT-RESCHED",
            "job_application": self.app_doc.name,
            "candidate": self.cand_doc.name,
            "job_opening": self.job_doc.name,
            "company": self.current_company,
            "interview_type": "Technical",
            "interviewer": self.current_user,
            "status": "Scheduled",
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        # Update scheduled_on date
        int_doc.scheduled_on = now_datetime()
        int_doc.status = "Rescheduled"
        int_doc.save(ignore_permissions=True)
        frappe.db.commit()

        record = self.service.list_notifications(
            user=self.current_user,
            company=self.current_company,
            options={"search": int_doc.name},
        )
        has_rescheduled = any("rescheduled" in n["title"].lower() or "rescheduled" in n["message"].lower() for n in record["data"])
        self.assertTrue(has_rescheduled)

    def test_NOTIF_EVENT_08_interview_cancellation(self):
        """NOTIF-EVENT-08: Cancelling an interview triggers a notification."""
        int_doc = frappe.get_doc({
            "doctype": "Interview",
            "interview_name": f"{self.prefix}INT-CANCEL",
            "job_application": self.app_doc.name,
            "candidate": self.cand_doc.name,
            "job_opening": self.job_doc.name,
            "company": self.current_company,
            "interview_type": "HR",
            "interviewer": self.current_user,
            "status": "Scheduled",
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        int_doc.status = "Cancelled"
        int_doc.save(ignore_permissions=True)
        frappe.db.commit()

        record = self.service.list_notifications(
            user=self.current_user,
            company=self.current_company,
            options={"search": int_doc.name},
        )
        has_cancelled = any("cancelled" in n["title"].lower() or "cancelled" in n["message"].lower() for n in record["data"])
        self.assertTrue(has_cancelled)

    def test_NOTIF_EVENT_09_job_creation(self):
        """NOTIF-EVENT-09: Creating a job opening triggers a notification."""
        j_title = f"{self.prefix}Backend Lead Engineer"
        j_doc = frappe.get_doc({
            "doctype": "Job Opening",
            "job_code": f"JOB-TEST-{frappe.generate_hash(length=6)}",
            "job_title": j_title,
            "company": self.current_company,
            "status": "Draft",
            "employment_type": "Full-time",
            "number_of_openings": 1,
            "job_summary": "Sample summary",
            "responsibilities": "Sample responsibilities",
            "requirements": "Sample requirements",
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        record = self.service.list_notifications(
            user=self.current_user,
            company=self.current_company,
            options={"search": j_doc.name},
        )
        self.assertGreaterEqual(record["total"], 1)

    def test_NOTIF_EVENT_10_application_creation(self):
        """NOTIF-EVENT-10: Creating a job application triggers a notification."""
        app = frappe.get_doc({
            "doctype": "Job Application",
            "candidate": self.cand_doc.name,
            "job_opening": self.job_doc.name,
            "company": self.current_company,
            "current_stage": "Applied",
            "status": "Open",
            "resume": "/files/sample_resume.pdf",
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        record = self.service.list_notifications(
            user=self.current_user,
            company=self.current_company,
            options={"search": str(app.name)},
        )
        self.assertGreaterEqual(record["total"], 1)

    def test_NOTIF_EVENT_11_application_stage_change(self):
        """NOTIF-EVENT-11: Changing job application stage triggers a notification."""
        app = frappe.get_doc({
            "doctype": "Job Application",
            "candidate": self.cand_doc.name,
            "job_opening": self.job_doc.name,
            "company": self.current_company,
            "current_stage": "Screening",
            "status": "Open",
            "resume": "/files/sample_resume.pdf",
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        app.current_stage = "Interview"
        app.save(ignore_permissions=True)
        frappe.db.commit()

        record = self.service.list_notifications(
            user=self.current_user,
            company=self.current_company,
            options={"search": str(app.name)},
        )
        has_stage_update = any("stage" in n["title"].lower() or "stage" in n["message"].lower() for n in record["data"])
        self.assertTrue(has_stage_update)

    def test_NOTIF_EVENT_12_offer_creation(self):
        """NOTIF-EVENT-12: Creating an offer triggers a notification."""
        off_name = f"{self.prefix}OFF-001"
        off = frappe.get_doc({
            "doctype": "Offer",
            "offer_name": off_name,
            "candidate": self.cand_doc.name,
            "job_application": self.app_doc.name,
            "job_opening": self.job_doc.name,
            "company": self.current_company,
            "offered_salary": 90000,
            "offer_status": "Draft",
            "offer_date": "2026-08-17",
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        record = self.service.list_notifications(
            user=self.current_user,
            company=self.current_company,
            options={"search": off.name},
        )
        self.assertGreaterEqual(record["total"], 1)

    def test_NOTIF_EVENT_13_offer_status_change(self):
        """NOTIF-EVENT-13: Changing offer status triggers a notification."""
        off_name = f"{self.prefix}OFF-STATUS-CHG"
        off = frappe.get_doc({
            "doctype": "Offer",
            "offer_name": off_name,
            "candidate": self.cand_doc.name,
            "job_application": self.app_doc.name,
            "job_opening": self.job_doc.name,
            "company": self.current_company,
            "offered_salary": 95000,
            "offer_status": "Draft",
            "offer_date": "2026-08-17",
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        off.offer_status = "Sent"
        off.save(ignore_permissions=True)
        frappe.db.commit()

        record = self.service.list_notifications(
            user=self.current_user,
            company=self.current_company,
            options={"search": off.name},
        )
        has_offer_status = any("status" in n["title"].lower() or "offer" in n["title"].lower() for n in record["data"])
        self.assertTrue(has_offer_status)

    def test_NOTIF_EVENT_14_unrelated_update_no_duplicate(self):
        """NOTIF-EVENT-14: Updating unrelated field (e.g. remarks) does not trigger duplicate event notification."""
        int_id = f"{self.prefix}INT-NO-DUP"
        int_doc = frappe.get_doc({
            "doctype": "Interview",
            "interview_name": int_id,
            "job_application": self.app_doc.name,
            "candidate": self.cand_doc.name,
            "job_opening": self.job_doc.name,
            "company": self.current_company,
            "interview_type": "HR",
            "interviewer": self.current_user,
            "status": "Scheduled",
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        count_before = len(self.service.list_notifications(
            user=self.current_user,
            company=self.current_company,
            options={"search": int_id},
        )["data"])

        # Edit unrelated field
        int_doc.remarks = "Interviewer updated private notes"
        int_doc.save(ignore_permissions=True)
        frappe.db.commit()

        count_after = len(self.service.list_notifications(
            user=self.current_user,
            company=self.current_company,
            options={"search": int_id},
        )["data"])

        self.assertEqual(count_before, count_after)

    def test_NOTIF_EVENT_15_repeated_event_idempotency(self):
        """NOTIF-EVENT-15: Re-saving the same document state does not duplicate notification."""
        int_id = f"{self.prefix}INT-IDEMPOTENT"
        int_doc = frappe.get_doc({
            "doctype": "Interview",
            "interview_name": int_id,
            "job_application": self.app_doc.name,
            "candidate": self.cand_doc.name,
            "job_opening": self.job_doc.name,
            "company": self.current_company,
            "interview_type": "Technical",
            "interviewer": self.current_user,
            "status": "Scheduled",
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        # Re-save document without changing anything
        int_doc.save(ignore_permissions=True)
        frappe.db.commit()

        record = self.service.list_notifications(
            user=self.current_user,
            company=self.current_company,
            options={"search": int_id},
        )
        self.assertEqual(len(record["data"]), 1)

    def test_NOTIF_EVENT_16_cross_company_isolation(self):
        """NOTIF-EVENT-16: Event created for foreign company is NOT returned to current user."""
        foreign_job = f"{self.prefix}Foreign Job"
        frappe.get_doc({
            "doctype": "Job Opening",
            "job_code": f"JOB-FOR-{frappe.generate_hash(length=6)}",
            "job_title": foreign_job,
            "company": self.foreign_company,
            "status": "Open",
            "employment_type": "Full-time",
            "number_of_openings": 1,
            "job_summary": "Sample summary",
            "responsibilities": "Sample responsibilities",
            "requirements": "Sample requirements",
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        record = self.service.list_notifications(
            user=self.current_user,
            company=self.current_company,
            options={"search": foreign_job},
        )
        self.assertEqual(record["total"], 0)

    def test_NOTIF_EVENT_17_notification_persistence(self):
        """NOTIF-EVENT-17: Generated notification persists in MariaDB database."""
        int_id = f"{self.prefix}INT-PERSIST"
        frappe.get_doc({
            "doctype": "Interview",
            "interview_name": int_id,
            "job_application": self.app_doc.name,
            "candidate": self.cand_doc.name,
            "job_opening": self.job_doc.name,
            "company": self.current_company,
            "interview_type": "Video",
            "interviewer": self.current_user,
            "status": "Scheduled",
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        meta = frappe.get_meta(DOCTYPE_NOTIFICATION)
        doc_id_field = "entity_id" if meta.has_field("entity_id") else "document_name"
        count_in_db = frappe.db.count(DOCTYPE_NOTIFICATION, {doc_id_field: int_id})
        self.assertGreaterEqual(count_in_db, 1)

    def test_NOTIF_EVENT_18_list_notifications_parity(self):
        """NOTIF-EVENT-18: Generated notification appears via list_notifications REST API."""
        int_id = f"{self.prefix}INT-API-LIST"
        frappe.get_doc({
            "doctype": "Interview",
            "interview_name": int_id,
            "job_application": self.app_doc.name,
            "candidate": self.cand_doc.name,
            "job_opening": self.job_doc.name,
            "company": self.current_company,
            "interview_type": "Technical",
            "interviewer": self.current_user,
            "status": "Scheduled",
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        frappe.form_dict.clear()
        frappe.form_dict.update({"search": int_id})
        res = list_notifications()
        self.assertTrue(res["success"])
        total = res.get("meta", {}).get("total", len(res.get("data", [])))
        self.assertGreaterEqual(total, 1)

    def test_NOTIF_EVENT_19_unread_count_increase(self):
        """NOTIF-EVENT-19: Creating a new recruitment event increases unread count."""
        unread_before = get_unread_count()["data"]["unread_count"]

        int_id = f"{self.prefix}INT-UNREAD-COUNT"
        frappe.get_doc({
            "doctype": "Interview",
            "interview_name": int_id,
            "job_application": self.app_doc.name,
            "candidate": self.cand_doc.name,
            "job_opening": self.job_doc.name,
            "company": self.current_company,
            "interview_type": "HR",
            "interviewer": self.current_user,
            "status": "Scheduled",
        }).insert(ignore_permissions=True)
        frappe.db.commit()

        unread_after = get_unread_count()["data"]["unread_count"]
        self.assertEqual(unread_after, unread_before + 1)

    def test_NOTIF_EVENT_20_no_mock_data(self):
        """NOTIF-EVENT-20: Confirm all notifications returned are authentic database records."""
        res = list_notifications()
        self.assertTrue(res["success"])
        items = res.get("data", [])
        for notif in items:
            self.assertNotIn("mock", str(notif.get("name", "")).lower())
            self.assertNotIn("demo", str(notif.get("title", "")).lower())


def run_notification_event_tests():
    """Standalone runner for manual docker exec verification."""
    suite = unittest.TestLoader().loadTestsFromTestCase(TestNotificationEventsPhase262)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    run_notification_event_tests()
