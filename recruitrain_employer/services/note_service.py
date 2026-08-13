# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

import json
import frappe
from recruitrain_employer.utils.exceptions import ATSValidationError, ATSNotFoundError
from recruitrain_employer.utils.company_context import get_current_company
from recruitrain_employer.utils.activity_logger import log_activity

DOCTYPE_NOTE = "Candidate Note"

class CandidateNoteService:
    """Enterprise Candidate Notes Service supporting rich text, @mentions, & pinned notes."""

    def add_note(self, data: dict) -> dict:
        candidate_id = data.get("candidate")
        if not candidate_id:
            raise ATSValidationError("candidate is required.", field="candidate")
        if not data.get("content"):
            raise ATSValidationError("content is required.", field="content")

        company = data.get("company") or get_current_company()
        if not company:
            raise ATSValidationError("Company context is required.")

        author = frappe.session.user
        author_doc = frappe.db.get_value("User", author, ["first_name", "last_name"], as_dict=True) or {}
        author_name = f"{author_doc.get('first_name', '')} {author_doc.get('last_name', '')}".strip() or author

        doc = frappe.new_doc(DOCTYPE_NOTE)
        doc.candidate = candidate_id
        doc.job_application = data.get("job_application")
        doc.company = company
        doc.author = author
        doc.author_name = author_name
        doc.content = data["content"]
        doc.is_pinned = 1 if data.get("is_pinned") else 0
        doc.is_private = 1 if data.get("is_private") else 0
        doc.mentions = json.dumps(data.get("mentions", [])) if isinstance(data.get("mentions"), list) else data.get("mentions")

        doc.insert(ignore_permissions=True)

        log_activity(
            action="Note Added",
            candidate=candidate_id,
            job_application=doc.job_application,
            company=company,
            details=f"Added note: {doc.content[:50]}..."
        )

        return doc.as_dict()

    def list_notes(self, candidate_id: str) -> list[dict]:
        company = get_current_company()
        filters = {"candidate": candidate_id}
        if company:
            filters["company"] = company

        notes = frappe.get_all(
            DOCTYPE_NOTE,
            filters=filters,
            fields=["name", "candidate", "job_application", "author", "author_name", "content", "is_pinned", "is_private", "mentions", "creation"],
            order_by="is_pinned desc, creation desc",
        )
        return notes

    def toggle_pin(self, note_id: str) -> dict:
        doc = frappe.get_doc(DOCTYPE_NOTE, note_id)
        doc.is_pinned = 0 if doc.is_pinned else 1
        doc.save(ignore_permissions=True)
        return doc.as_dict()

    def delete_note(self, note_id: str) -> None:
        if not frappe.db.exists(DOCTYPE_NOTE, note_id):
            raise ATSNotFoundError(f"Note '{note_id}' not found.")
        frappe.delete_doc(DOCTYPE_NOTE, note_id, ignore_permissions=True)
