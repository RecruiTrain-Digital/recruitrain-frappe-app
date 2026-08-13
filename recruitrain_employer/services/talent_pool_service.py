# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

import frappe
from recruitrain_employer.utils.exceptions import ATSValidationError, ATSNotFoundError
from recruitrain_employer.utils.company_context import get_current_company

DOCTYPE_TALENT_POOL = "Talent Pool"

class TalentPoolService:
    """Enterprise Talent Pool Service (Silver Medalists, Campus, Referrals, etc.)."""

    def create_pool(self, data: dict) -> dict:
        company = data.get("company") or get_current_company()
        if not company:
            raise ATSValidationError("Company context is required.")
        if not data.get("pool_name"):
            raise ATSValidationError("pool_name is required.", field="pool_name")

        doc = frappe.new_doc(DOCTYPE_TALENT_POOL)
        doc.pool_name = data["pool_name"]
        doc.company = company
        doc.category = data.get("category", "Custom")
        doc.description = data.get("description")
        doc.insert(ignore_permissions=True)
        return doc.as_dict()

    def list_pools(self, company: str | None = None) -> list[dict]:
        comp = company or get_current_company()
        filters = {"company": comp} if comp else {}
        pools = frappe.get_all(
            DOCTYPE_TALENT_POOL,
            filters=filters,
            fields=["name", "pool_name", "company", "category", "description", "creation"],
            order_by="creation desc",
        )
        return pools

    def add_candidate_to_pool(self, pool_id: str, candidate_id: str, notes: str | None = None) -> dict:
        doc = frappe.get_doc(DOCTYPE_TALENT_POOL, pool_id)
        cand_doc = frappe.get_doc("Candidate", candidate_id)

        # Check existing member
        for m in doc.members:
            if m.candidate == candidate_id:
                return doc.as_dict()

        doc.append("members", {
            "candidate": candidate_id,
            "candidate_name": cand_doc.full_name or f"{cand_doc.first_name} {cand_doc.last_name}".strip(),
            "candidate_email": cand_doc.email,
            "added_on": frappe.utils.now_datetime(),
            "added_by": frappe.session.user,
            "notes": notes,
        })
        doc.save(ignore_permissions=True)
        return doc.as_dict()

    def remove_candidate_from_pool(self, pool_id: str, candidate_id: str) -> dict:
        doc = frappe.get_doc(DOCTYPE_TALENT_POOL, pool_id)
        doc.members = [m for m in doc.members if m.candidate != candidate_id]
        doc.save(ignore_permissions=True)
        return doc.as_dict()
