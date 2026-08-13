# Copyright (c) 2026, RecruiTrain  and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class Candidate(Document):
	def on_trash(self):
		"""Prevent deletion if Candidate has linked recruitment history."""
		candidate_id = self.name
		blocking_links: dict[str, int] = {}

		linked_apps = frappe.db.count("Job Application", {"candidate": candidate_id})
		if linked_apps > 0:
			blocking_links["job_applications"] = linked_apps

		linked_interviews = frappe.db.count("Interview", {"candidate": candidate_id})
		if linked_interviews > 0:
			blocking_links["interviews"] = linked_interviews

		linked_feedback = frappe.db.count("Interview Feedback", {"candidate": candidate_id})
		if linked_feedback > 0:
			blocking_links["interview_feedback"] = linked_feedback

		linked_offers = frappe.db.count("Offer", {"candidate": candidate_id})
		if linked_offers > 0:
			blocking_links["offers"] = linked_offers

		if frappe.db.exists("DocType", "Candidate Note"):
			linked_notes = frappe.db.count("Candidate Note", {"candidate": candidate_id})
			if linked_notes > 0:
				blocking_links["candidate_notes"] = linked_notes

		if frappe.db.exists("DocType", "Talent Pool Member"):
			linked_pool_members = frappe.db.count("Talent Pool Member", {"candidate": candidate_id})
			if linked_pool_members > 0:
				blocking_links["talent_pool_memberships"] = linked_pool_members

		linked_activity_logs = frappe.db.count("Activity Logs", {"candidate": candidate_id})
		if linked_activity_logs > 0:
			blocking_links["activity_logs"] = linked_activity_logs

		if blocking_links:
			parts = [f"{count} {doctype.replace('_', ' ')}" for doctype, count in blocking_links.items()]
			summary = ", ".join(parts)
			frappe.throw(
				f"Candidate '{candidate_id}' cannot be deleted because they have linked recruitment records: {summary}. Archive the candidate (set status to 'Archived') instead of deleting."
			)

