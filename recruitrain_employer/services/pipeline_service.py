# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

import frappe
from recruitrain_employer.utils.exceptions import (
    ATSValidationError,
    ATSNotFoundError,
    ATSPermissionError,
)
from recruitrain_employer.utils.company_context import get_current_company

DOCTYPE_PIPELINE = "Pipeline"

DEFAULT_STAGES = [
    {"stage_name": "Applied", "stage_type": "Applied", "stage_order": 1, "color": "#64748B", "is_terminal": 0},
    {"stage_name": "Screening", "stage_type": "Screening", "stage_order": 2, "color": "#3B82F6", "is_terminal": 0},
    {"stage_name": "Technical Round", "stage_type": "Interview", "stage_order": 3, "color": "#8B5CF6", "is_terminal": 0},
    {"stage_name": "Manager Round", "stage_type": "Interview", "stage_order": 4, "color": "#EC4899", "is_terminal": 0},
    {"stage_name": "Offer Extended", "stage_type": "Offer", "stage_order": 5, "color": "#F59E0B", "is_terminal": 0},
    {"stage_name": "Hired", "stage_type": "Hired", "stage_order": 6, "color": "#10B981", "is_terminal": 1},
    {"stage_name": "Rejected", "stage_type": "Rejected", "stage_order": 7, "color": "#EF4444", "is_terminal": 1},
]

class PipelineService:
    """Enterprise Pipeline Service for custom multi-stage recruitment workflows."""

    def get_or_create_default_pipeline(self, company: str | None = None) -> dict:
        """Get default pipeline for company or seed a default one."""
        comp = company or get_current_company()
        if not comp:
            raise ATSValidationError("Company context is required.")

        pipes = frappe.get_all(
            DOCTYPE_PIPELINE,
            filters={"company": comp, "is_default": 1},
            fields=["name"],
            limit=1,
        )

        if pipes:
            doc = frappe.get_doc(DOCTYPE_PIPELINE, pipes[0]["name"])
            return doc.as_dict()

        # Seed default pipeline
        doc = frappe.new_doc(DOCTYPE_PIPELINE)
        doc.pipeline_name = "Default Recruitment Pipeline"
        doc.company = comp
        doc.is_default = 1
        for stg in DEFAULT_STAGES:
            doc.append("stages", stg)
        doc.insert(ignore_permissions=True)
        return doc.as_dict()

    def list_pipelines(self, company: str | None = None) -> list[dict]:
        """List pipelines for company."""
        comp = company or get_current_company()
        if not comp:
            return []

        pipes = frappe.get_all(
            DOCTYPE_PIPELINE,
            filters={"company": comp},
            fields=["name", "pipeline_name", "company", "is_default", "creation"],
            order_by="is_default desc, creation desc",
        )
        res = []
        for p in pipes:
            d = frappe.get_doc(DOCTYPE_PIPELINE, p["name"])
            res.append(d.as_dict())
        return res

    def create_pipeline(self, data: dict) -> dict:
        """Create a new custom pipeline."""
        comp = data.get("company") or get_current_company()
        if not comp:
            raise ATSValidationError("Company is required.", field="company")
        if not data.get("pipeline_name"):
            raise ATSValidationError("Pipeline name is required.", field="pipeline_name")

        doc = frappe.new_doc(DOCTYPE_PIPELINE)
        doc.pipeline_name = data["pipeline_name"]
        doc.company = comp
        doc.is_default = 1 if data.get("is_default") else 0

        stages = data.get("stages") or DEFAULT_STAGES
        for idx, stg in enumerate(stages, 1):
            doc.append("stages", {
                "stage_name": stg.get("stage_name"),
                "stage_type": stg.get("stage_type", "Custom"),
                "stage_order": stg.get("stage_order", idx),
                "color": stg.get("color", "#3B82F6"),
                "is_terminal": 1 if stg.get("is_terminal") else 0,
            })

        doc.insert(ignore_permissions=True)
        return doc.as_dict()
