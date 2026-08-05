# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

import json
import frappe
from recruitrain_employer.api.company import _extract_company_fields, update_company_profile
from recruitrain_employer.validators.company_validator import COMPANY_UPDATABLE_FIELDS, CompanyValidator
from recruitrain_employer.services.company_service import CompanyService
from recruitrain_employer.utils.permissions import get_current_company

def run_audit():
    frappe.set_user("Administrator")
    print("=== AUDIT 1: Current Company Resolution ===")
    company_id = get_current_company()
    print("Resolved Company ID:", company_id)

    print("\n=== AUDIT 2: Testing _extract_company_fields with different mock inputs ===")
    # Test case A: Direct form_dict (snake_case)
    fd1 = {"legal_name": "Acme Corp", "website": "https://acme.com", "cmd": "update"}
    ext1 = _extract_company_fields(fd1)
    print("Extracted from fd1 (snake_case):", ext1)

    # Test case B: form_dict containing 'data' as JSON string
    fd2 = {"data": json.dumps({"legal_name": "Acme Corp", "website": "https://acme.com"})}
    ext2 = _extract_company_fields(fd2)
    print("Extracted from fd2 (json string in data key):", ext2)

    # Test case C: form_dict containing 'data' as dict
    fd3 = {"data": {"legal_name": "Acme Corp", "website": "https://acme.com"}}
    ext3 = _extract_company_fields(fd3)
    print("Extracted from fd3 (dict in data key):", ext3)

    # Test case D: form_dict containing camelCase keys
    fd4 = {"legalName": "Acme Corp", "companyCode": "ACME-1", "addressLine1": "123 Main St"}
    ext4 = _extract_company_fields(fd4)
    print("Extracted from fd4 (camelCase keys):", ext4)

    print("\n=== AUDIT 3: Backend COMPANY_UPDATABLE_FIELDS vs Validator check ===")
    validator = CompanyValidator()
    print("COMPANY_UPDATABLE_FIELDS count:", len(COMPANY_UPDATABLE_FIELDS))
    print("Updatable fields list:", sorted(list(COMPANY_UPDATABLE_FIELDS)))

    # Test validating ext1
    try:
        validator.validate_update(ext1.copy())
        print("Validation fd1: PASSED")
    except Exception as e:
        print("Validation fd1 FAILED:", e)

    # Test validating ext4 (camelCase)
    try:
        validator.validate_update(ext4.copy())
        print("Validation fd4 (camelCase): PASSED")
    except Exception as e:
        print("Validation fd4 (camelCase) FAILED:", e)

    print("\n=== AUDIT COMPLETE ===")
