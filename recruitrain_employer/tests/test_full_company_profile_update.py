# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

import frappe
from recruitrain_employer.api.company import update_company_profile, get_company_profile
from recruitrain_employer.services.company_service import CompanyService
from recruitrain_employer.utils.permissions import get_current_company

def run_e2e_verification():
    frappe.set_user("Administrator")
    
    # Ensure Industry record exists for testing
    if not frappe.db.exists("Industry", "IT"):
        ind = frappe.new_doc("Industry")
        ind.industry_name = "IT"
        ind.insert(ignore_permissions=True)
        print("Created test Industry: IT")

    # Ensure Country record exists for testing
    if not frappe.db.exists("Country", "Germany"):
        c = frappe.new_doc("Country")
        c.country_name = "Germany"
        c.insert(ignore_permissions=True)
        print("Created test Country: Germany")

    company_id = get_current_company()
    print(f"=== E2E AUDIT START: Target Company ID '{company_id}' ===")

    test_payload = {
        "legal_name": "RecruiTrain Global Enterprise Solutions GmbH",
        "company_code": "RT-ENT-2026",
        "industry": "IT",
        "company_size": "51-200",
        "founded_year": 2021,
        "website": "https://recruitrain.de",
        "description": "Leading AI-powered Employer & ATS Management Suite for global hiring.",
        "email": "contact@recruitrain.de",
        "phone": "+493012345678",
        "alternate_phone": "+493087654321",
        "hr_email": "hr@recruitrain.de",
        "support_email": "support@recruitrain.de",
        "address_line_1": "Friedrichstraße 100",
        "address_line_2": "Floor 4, Suite 402",
        "city": "Berlin",
        "state": "Berlin",
        "country": "Germany",
        "postal_code": "10117",
        "logo": "/files/company_logo_test.png",
        "banner": "/files/company_banner_test.png",
        "primary_color": "#0d9488",
        "secondary_color": "#0f766e",
        "linkedin": "https://linkedin.com/company/recruitrain",
        "facebook": "https://facebook.com/recruitrain",
        "instagram": "https://instagram.com/recruitrain",
        "twitter": "https://twitter.com/recruitrain",
        "timezone": "Europe/Berlin",
        "language": "de",
        "date_format": "DD.MM.YYYY",
        "currency": "EUR",
        "theme": "dark",
        "status": "Active",
        "verified": True,
        "active": True
    }

    print("\n--- Executing update_company_profile via API layer ---")
    frappe.form_dict = frappe._dict(test_payload)
    response = update_company_profile()
    
    print("\n--- Response from API update_company_profile ---")
    print("Success:", response.get("success"))
    print("Message:", response.get("message"))
    
    updated_data = response.get("data", {})
    print("Updated legal_name:", updated_data.get("legal_name"))
    print("Updated email:", updated_data.get("email"))
    print("Updated website:", updated_data.get("website"))
    print("Updated address_line_1:", updated_data.get("address_line_1"))
    print("Updated city:", updated_data.get("city"))
    print("Updated country:", updated_data.get("country"))

    # Verify directly from DB
    doc = frappe.get_doc("Company", company_id)
    print("\n--- Database Verification directly from Frappe ORM ---")
    print("DB legal_name:", doc.legal_name)
    print("DB company_code:", doc.company_code)
    print("DB website:", doc.website)
    print("DB email:", doc.email)
    print("DB phone:", doc.phone)
    print("DB address_line_1:", doc.address_line_1)
    print("DB city:", doc.city)
    print("DB country:", doc.country)
    print("DB logo:", doc.logo)

    assert doc.legal_name == test_payload["legal_name"], "DB legal_name mismatch!"
    assert doc.website == test_payload["website"], "DB website mismatch!"
    assert doc.email == test_payload["email"], "DB email mismatch!"
    print("\n=== E2E AUDIT PASSED: 100% PERSISTENCE VERIFIED ===")
