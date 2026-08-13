# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.validators.profession_validator
=====================================================

Profession Resolver, Seeding, Normalization, and Validation.

Objectives & Business Logic:
1. Seed default canonical professions automatically if missing.
2. Link every Profession strictly to a parent Department taxonomy.
3. Implement ProfessionResolver:
   - Case-insensitive
   - Hyphen-agnostic
   - Underscore-agnostic
   - Multiple space agnostic
   - Synonym / alias resolution
   - Returns canonical DB record `name`
"""

from __future__ import annotations

import re
from typing import Any

import frappe

from recruitrain_employer.utils.constants import DOCTYPE_PROFESSION
from recruitrain_employer.utils.exceptions import ATSValidationError
from recruitrain_employer.validators.department_validator import DepartmentResolver, seed_default_departments

#: Complete mapping of production professions to their parent Department taxonomy
DEFAULT_PROFESSION_DEPARTMENT_MAP: dict[str, str] = {
    # Healthcare
    "Nurse": "Healthcare",
    "Staff Nurse": "Healthcare",
    "Registered Nurse": "Healthcare",
    "ICU Nurse": "Healthcare",
    "Operation Theatre Nurse": "Healthcare",
    "Healthcare Assistant": "Healthcare",
    "Doctor": "Healthcare",
    "Physician": "Healthcare",
    "Radiologist": "Healthcare",
    "Pharmacist": "Healthcare",
    "Lab Technician": "Healthcare",
    "Physiotherapist": "Healthcare",
    "Pflegefachkraft": "Healthcare",
    "Care Assistant": "Healthcare",
    "Medizinische/r Fachangestellte/r (MFA)": "Healthcare",
    "Zahnmedizinische/r Fachangestellte/r (ZFA)": "Healthcare",
    "Operationstechnische Assistency (OTA)": "Healthcare",
    "Physiotherapeut/in": "Healthcare",
    "Ergotherapeut/in": "Healthcare",
    "Exam. Gesundheits- und Krankenpfleger/in": "Healthcare",
    "Exam. Gesundheits- und Kinderkrankenpfleger/in": "Healthcare",
    "Exam. Altenpfleger/in": "Healthcare",
    "Exam. Altenpflegehelfer/in": "Healthcare",
    "Exam. Gesundheits- und Krankenpfleger/in mit Fachweiterbildung": "Healthcare",
    "Exam. Krankenpflegehelfer/in": "Healthcare",
    "Pflegehelfer/in": "Healthcare",
    "Wohnbereichsleitung": "Healthcare",

    # Information Technology
    "Software Engineer": "Information Technology",
    "Frontend Developer": "Information Technology",
    "Backend Developer": "Information Technology",
    "Full Stack Developer": "Information Technology",
    "DevOps Engineer": "Information Technology",
    "QA Engineer": "Information Technology",
    "Cloud Engineer": "Information Technology",
    "Mobile Developer": "Information Technology",
    "Data Engineer": "Information Technology",
    "Data Scientist": "Information Technology",
    "AI Engineer": "Information Technology",
    "Project Manager": "Information Technology",
    "UI UX Designer": "Information Technology",
    "Product Manager": "Information Technology",
    "Business Analyst": "Information Technology",

    # Engineering
    "Mechanical Engineer": "Engineering",
    "Civil Engineer": "Engineering",
    "Electrical Engineer": "Engineering",
    "Design Engineer": "Engineering",
    "Production Engineer": "Engineering",
    "Architect": "Engineering",
    "Electrician": "Engineering",

    # Finance
    "Accountant": "Finance",
    "Auditor": "Finance",
    "Finance Manager": "Finance",
    "Tax Consultant": "Finance",

    # Human Resources
    "HR Executive": "Human Resources",
    "Recruiter": "Human Resources",
    "Talent Acquisition Specialist": "Human Resources",
    "HR Manager": "Human Resources",

    # Marketing
    "Marketing Executive": "Marketing",
    "Digital Marketing Specialist": "Marketing",
    "SEO Specialist": "Marketing",
    "Content Writer": "Marketing",
    "Marketing Specialist": "Marketing",

    # Sales
    "Sales Executive": "Sales",
    "Business Development Executive": "Sales",
    "Sales Manager": "Sales",

    # Customer Support
    "Customer Support Executive": "Customer Support",
    "Technical Support Engineer": "Customer Support",

    # Legal
    "Legal Advisor": "Legal",
    "Compliance Officer": "Legal",

    # Operations
    "Operations Executive": "Operations",
    "Operations Manager": "Operations",

    # Administration
    "Office Administrator": "Administration",
    "Admin Executive": "Administration",

    # Manufacturing
    "Production Operator": "Manufacturing",
    "Plant Supervisor": "Manufacturing",

    # Logistics
    "Logistics Coordinator": "Logistics",
    "Warehouse Executive": "Logistics",
    "Warehouse Operator": "Logistics",

    # Procurement
    "Procurement Executive": "Procurement",
    "Purchase Manager": "Procurement",

    # Quality Assurance
    "QA Inspector": "Quality Assurance",
    "QA Lead": "Quality Assurance",

    # Research & Development
    "Research Scientist": "Research & Development",
    "R&D Engineer": "Research & Development",
    "Lab Researcher": "Research & Development",
}

DEFAULT_PRODUCTION_PROFESSIONS: tuple[str, ...] = tuple(DEFAULT_PROFESSION_DEPARTMENT_MAP.keys())

#: Synonym & alias mapping -> canonical master name
PROFESSION_SYNONYM_MAP: dict[str, str] = {
    # Healthcare
    "nurse": "Nurse",
    "staff nurse": "Staff Nurse",
    "registered nurse": "Registered Nurse",
    "rn": "Registered Nurse",
    "icu nurse": "ICU Nurse",
    "ot nurse": "Operation Theatre Nurse",
    "operation theatre nurse": "Operation Theatre Nurse",
    "healthcare assistant": "Healthcare Assistant",
    "nursing assistant": "Healthcare Assistant",
    "doctor": "Doctor",
    "arzt": "Doctor",
    "physician": "Physician",
    "radiologist": "Radiologist",
    "pharmacist": "Pharmacist",
    "lab technician": "Lab Technician",
    "laboratory technician": "Lab Technician",
    "physiotherapist": "Physiotherapist",
    "physical therapist": "Physiotherapist",
    "pflegefachkraft": "Pflegefachkraft",
    "krankenschwester": "Pflegefachkraft",
    "krankenpfleger": "Pflegefachkraft",
    "altenpfleger": "Pflegefachkraft",
    "care assistant": "Care Assistant",
    "mfa": "Medizinische/r Fachangestellte/r (MFA)",
    "zfa": "Zahnmedizinische/r Fachangestellte/r (ZFA)",
    "ota": "Operationstechnische Assistency (OTA)",
    "ergotherapeut": "Ergotherapeut/in",
    "pflegehelfer": "Pflegehelfer/in",
    "wohnbereichsleitung": "Wohnbereichsleitung",

    # IT
    "software engineer": "Software Engineer",
    "software developer": "Software Engineer",
    "programmer": "Software Engineer",
    "developer": "Software Engineer",
    "frontend developer": "Frontend Developer",
    "frontend engineer": "Frontend Developer",
    "react developer": "Frontend Developer",
    "backend developer": "Backend Developer",
    "backend engineer": "Backend Developer",
    "python developer": "Backend Developer",
    "node developer": "Backend Developer",
    "full stack developer": "Full Stack Developer",
    "fullstack developer": "Full Stack Developer",
    "fullstack engineer": "Full Stack Developer",
    "devops engineer": "DevOps Engineer",
    "devops": "DevOps Engineer",
    "sre": "DevOps Engineer",
    "qa engineer": "QA Engineer",
    "qa tester": "QA Engineer",
    "test engineer": "QA Engineer",
    "cloud engineer": "Cloud Engineer",
    "aws engineer": "Cloud Engineer",
    "azure engineer": "Cloud Engineer",
    "mobile developer": "Mobile Developer",
    "ios developer": "Mobile Developer",
    "android developer": "Mobile Developer",
    "data engineer": "Data Engineer",
    "data scientist": "Data Scientist",
    "ai engineer": "AI Engineer",
    "ml engineer": "AI Engineer",
    "project manager": "Project Manager",
    "pm": "Project Manager",
    "ui/ux designer": "UI UX Designer",
    "ui ux designer": "UI UX Designer",
    "ux designer": "UI UX Designer",
    "product manager": "Product Manager",
    "business analyst": "Business Analyst",

    # Engineering
    "mechanical engineer": "Mechanical Engineer",
    "civil engineer": "Civil Engineer",
    "electrical engineer": "Electrical Engineer",
    "design engineer": "Design Engineer",
    "production engineer": "Production Engineer",
    "architect": "Architect",
    "electrician": "Electrician",

    # Finance
    "accountant": "Accountant",
    "bookkeeper": "Accountant",
    "auditor": "Auditor",
    "finance manager": "Finance Manager",
    "tax consultant": "Tax Consultant",

    # HR
    "hr executive": "HR Executive",
    "recruiter": "Recruiter",
    "talent acquisition specialist": "Talent Acquisition Specialist",
    "ta specialist": "Talent Acquisition Specialist",
    "hr manager": "HR Manager",

    # Marketing
    "marketing executive": "Marketing Executive",
    "digital marketing specialist": "Digital Marketing Specialist",
    "digital marketing": "Digital Marketing Specialist",
    "seo specialist": "SEO Specialist",
    "content writer": "Content Writer",
    "copywriter": "Content Writer",

    # Sales
    "sales executive": "Sales Executive",
    "sales rep": "Sales Executive",
    "business development executive": "Business Development Executive",
    "bde": "Business Development Executive",
    "sales manager": "Sales Manager",

    # Support
    "customer support executive": "Customer Support Executive",
    "support agent": "Customer Support Executive",
    "technical support engineer": "Technical Support Engineer",
    "tech support": "Technical Support Engineer",

    # Legal
    "legal advisor": "Legal Advisor",
    "legal counsel": "Legal Advisor",
    "compliance officer": "Compliance Officer",

    # Operations
    "operations executive": "Operations Executive",
    "operations manager": "Operations Manager",

    # Admin
    "office administrator": "Office Administrator",
    "office manager": "Office Administrator",
    "admin executive": "Admin Executive",

    # Manufacturing
    "production operator": "Production Operator",
    "plant supervisor": "Plant Supervisor",

    # Logistics
    "logistics coordinator": "Logistics Coordinator",
    "warehouse executive": "Warehouse Executive",
    "warehouse operator": "Warehouse Operator",

    # Procurement
    "procurement executive": "Procurement Executive",
    "purchase manager": "Purchase Manager",

    # QA
    "qa inspector": "QA Inspector",
    "quality inspector": "QA Inspector",
    "qa lead": "QA Lead",

    # R&D
    "research scientist": "Research Scientist",
    "r&d engineer": "R&D Engineer",
    "lab researcher": "Lab Researcher",
}


def normalize_profession_string(s: str) -> str:
    """Normalize string by replacing hyphens, underscores, slashes with spaces, collapsing whitespace, and lowercasing."""
    if not s:
        return ""
    cleaned = re.sub(r"[-_/]+", " ", str(s))
    return " ".join(cleaned.split()).lower()


def seed_default_professions() -> list[str]:
    """Ensure default production profession master records exist in the database and link to parent Department."""
    seed_default_departments()

    existing = frappe.get_all(DOCTYPE_PROFESSION, fields=["name", "profession_name", "department"])
    existing_map = {}
    for r in existing:
        if r.get("name"):
            existing_map[r["name"]] = r
        if r.get("profession_name"):
            existing_map[r["profession_name"]] = r

    order_counter = 10
    for prof, dept_raw in DEFAULT_PROFESSION_DEPARTMENT_MAP.items():
        canonical_dept = ""
        try:
            canonical_dept = DepartmentResolver.resolve(dept_raw)
        except Exception:
            canonical_dept = dept_raw

        if prof not in existing_map:
            try:
                doc = frappe.new_doc(DOCTYPE_PROFESSION)
                doc.profession_name = prof
                doc.department = canonical_dept
                doc.description = f"{prof} in {canonical_dept}"
                doc.is_active = 1
                doc.display_order = order_counter
                doc.insert(ignore_permissions=True)
            except Exception as exc:
                frappe.logger().error(f"Failed to create default Profession '{prof}': {exc}")
        else:
            rec = existing_map[prof]
            if rec.get("department") != canonical_dept:
                try:
                    p_doc = frappe.get_doc(DOCTYPE_PROFESSION, rec.get("name"))
                    p_doc.department = canonical_dept
                    p_doc.is_active = 1
                    p_doc.save(ignore_permissions=True)
                except Exception:
                    pass

        order_counter += 10

    all_recs = frappe.get_all(DOCTYPE_PROFESSION, fields=["name"])
    return [r["name"] for r in all_recs]


class ProfessionResolver:
    """Robust resolver for Profession master records."""

    @classmethod
    def resolve(cls, raw_value: str, department: str | None = None) -> str:
        """Resolve raw input string to canonical database Profession primary key name.

        If department is supplied, validates that the profession belongs to that Department.
        """
        if not raw_value or not str(raw_value).strip():
            return ""

        raw_str = str(raw_value).strip()
        norm_input = normalize_profession_string(raw_str)

        records = frappe.get_all(DOCTYPE_PROFESSION, fields=["name", "profession_name", "department"])

        existing_keys = {r.get("name") for r in records if r.get("name")} | {
            r.get("profession_name") for r in records if r.get("profession_name")
        }
        if not records or not any(p in existing_keys for p in DEFAULT_PRODUCTION_PROFESSIONS):
            seed_default_professions()
            records = frappe.get_all(DOCTYPE_PROFESSION, fields=["name", "profession_name", "department"])

        norm_map: dict[str, dict] = {}
        for r in records:
            db_name = r.get("name")
            prof_label = r.get("profession_name")
            if db_name:
                norm_map[normalize_profession_string(db_name)] = r
            if prof_label:
                norm_map[normalize_profession_string(prof_label)] = r

        matched_rec = None
        if norm_input in norm_map:
            matched_rec = norm_map[norm_input]
        elif norm_input in PROFESSION_SYNONYM_MAP:
            target = PROFESSION_SYNONYM_MAP[norm_input]
            norm_target = normalize_profession_string(target)
            if norm_target in norm_map:
                matched_rec = norm_map[norm_target]

        if not matched_rec:
            for r in records:
                db_name = r.get("name")
                prof_label = r.get("profession_name")
                if (db_name and db_name.strip().lower() == raw_str.lower()) or (
                    prof_label and prof_label.strip().lower() == raw_str.lower()
                ):
                    matched_rec = r
                    break

        if not matched_rec:
            raise ATSValidationError(
                f"Profession '{raw_str}' does not exist.",
                field="profession",
                details={"profession": raw_str},
            )

        canonical_prof = matched_rec["name"]
        prof_dept = matched_rec.get("department")

        if department and department.strip():
            canonical_dept = DepartmentResolver.resolve(department)
            if prof_dept and prof_dept != canonical_dept:
                raise ATSValidationError(
                    f"Profession '{canonical_prof}' does not belong to Department '{canonical_dept}'. (It belongs to '{prof_dept}').",
                    field="profession",
                    details={
                        "profession": canonical_prof,
                        "department": canonical_dept,
                        "actual_department": prof_dept,
                    },
                )

        return canonical_prof


def get_canonical_profession(raw_value: str, department: str | None = None) -> str:
    """Wrapper around ProfessionResolver.resolve."""
    return ProfessionResolver.resolve(raw_value, department=department)


def validate_and_normalize_profession(data: dict | str, department: str | None = None) -> str | None:
    """Validate and normalize Profession in a payload dictionary or raw string."""
    if isinstance(data, dict):
        raw_val = data.get("profession")
        if not raw_val:
            return None
        dept_val = department or data.get("department")
        canonical = ProfessionResolver.resolve(raw_val, department=dept_val)
        data["profession"] = canonical
        return canonical
    elif isinstance(data, str):
        if not data.strip():
            return None
        return ProfessionResolver.resolve(data, department=department)
    return None
