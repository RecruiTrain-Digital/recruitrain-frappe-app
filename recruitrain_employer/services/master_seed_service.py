# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.services.master_seed_service
===================================================

Centralized Master Data Seeding Service for RecruiTrain Employer ATS.

Guarantees that all required production master DocType records (Department,
Profession, Employment Type, Industry) are present in MariaDB before validation
or ORM database transactions take place.
"""

from __future__ import annotations

import frappe

from recruitrain_employer.validators.department_validator import seed_default_departments
from recruitrain_employer.validators.employment_type_validator import (
    seed_default_employment_types,
)
from recruitrain_employer.validators.industry_validator import seed_default_industries
from recruitrain_employer.validators.profession_validator import seed_default_professions


def ensure_master_records_exist() -> dict[str, list[str]]:
    """Seed all missing default production master records into the database.

    Returns
    -------
    dict[str, list[str]]
        Dictionary containing populated master names by DocType.
    """
    seeded: dict[str, list[str]] = {}
    try:
        seeded["Department"] = seed_default_departments()
    except Exception as exc:
        frappe.logger().error(f"[MasterSeedService] Failed to seed Departments: {exc}")

    try:
        seeded["Profession"] = seed_default_professions()
    except Exception as exc:
        frappe.logger().error(f"[MasterSeedService] Failed to seed Professions: {exc}")

    try:
        seeded["Employment Type"] = seed_default_employment_types()
    except Exception as exc:
        frappe.logger().error(f"[MasterSeedService] Failed to seed Employment Types: {exc}")

    try:
        seeded["Industry"] = seed_default_industries()
    except Exception as exc:
        frappe.logger().error(f"[MasterSeedService] Failed to seed Industries: {exc}")

    return seeded
