# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

import frappe
from recruitrain_employer.services.pipeline_service import PipelineService
from recruitrain_employer.utils.permissions import employer_required
from recruitrain_employer.utils.response import success_response, error_response
from recruitrain_employer.utils.exceptions import ATSException

def _handle_ats_exception(exc: Exception) -> dict:
    if isinstance(exc, ATSException):
        return error_response(code=exc.code, message=exc.message, details=exc.details, http_status_code=400)
    return error_response(code="INTERNAL_SERVER_ERROR", message=str(exc), http_status_code=500)

@frappe.whitelist()
@employer_required
def get_default_pipeline() -> dict:
    try:
        service = PipelineService()
        data = service.get_or_create_default_pipeline()
        return success_response(data=data)
    except Exception as exc:
        return _handle_ats_exception(exc)

@frappe.whitelist()
@employer_required
def list_pipelines() -> dict:
    try:
        service = PipelineService()
        data = service.list_pipelines()
        return success_response(data=data)
    except Exception as exc:
        return _handle_ats_exception(exc)

@frappe.whitelist()
@employer_required
def create_pipeline() -> dict:
    try:
        data = frappe.form_dict
        service = PipelineService()
        res = service.create_pipeline(data)
        return success_response(data=res, message="Pipeline created successfully.")
    except Exception as exc:
        return _handle_ats_exception(exc)
