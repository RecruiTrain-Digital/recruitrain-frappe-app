# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.validators.tariff_group_validator
=========================================================

Tariff Group Seeding, Categorisation, and Master Resolution.
"""

from __future__ import annotations

import frappe

DOCTYPE_TARIFF_GROUP = "Tariff Group"

TARIFF_GROUPS_BY_CATEGORY: dict[str, list[str]] = {
    "Nursing": [
        "TVöD-P",
        "TV-L KR",
        "TV-H KR",
        "AVR Caritas",
        "AVR Diakonie",
        "Haustarifvertrag",
        "außertariflich",
    ],
    "Doctors": [
        "TV-Ärzte/VKA",
        "TV-Ärzte TdL",
        "AVR Caritas",
        "AVR Diakonie",
        "Haustarifvertrag",
        "Außertariflich",
    ],
    "Physio / Ergo / MFA / OTA": [
        "TVöD-P",
        "TVöD",
        "TV-L",
        "TV-H",
        "AVR Caritas",
        "AVR Diakonie",
        "Haustarifvertrag",
        "außertariflich",
    ],
    "IT / Technology": [
        "TVöD",
        "TV-L",
        "TV-H",
        "Haustarifvertrag",
        "außertariflich",
        "andere",
    ],
    "Industry / Trade": [
        "TVöD",
        "TV-L",
        "TV-H",
        "Haustarifvertrag",
        "außertariflich",
        "andere",
    ],
}


def seed_default_tariff_groups() -> list[str]:
    """Ensure standard tariff group master records exist in the database."""
    seeded: list[str] = []
    for cat, items in TARIFF_GROUPS_BY_CATEGORY.items():
        for name in items:
            if not frappe.db.exists(DOCTYPE_TARIFF_GROUP, name):
                try:
                    doc = frappe.new_doc(DOCTYPE_TARIFF_GROUP)
                    doc.tariff_group_name = name
                    doc.category = cat
                    doc.description = f"Tariff Group {name} ({cat})"
                    doc.is_active = 1
                    doc.insert(ignore_permissions=True)
                    seeded.append(name)
                except Exception as exc:
                    frappe.logger().error(f"Failed to seed Tariff Group '{name}': {exc}")

    frappe.db.commit()
    return seeded


def get_tariff_groups_for_category(profession: str | None = None, department: str | None = None) -> list[dict]:
    """Return authoritative tariff groups filtered by profession / department or full list."""
    try:
        seed_default_tariff_groups()
    except Exception:
        pass

    category_match: str | None = None
    if profession or department:
        target = f"{profession or ''} {department or ''}".lower()
        if any(k in target for k in ("nurse", "pflege", "krankenschwester")):
            category_match = "Nursing"
        elif any(k in target for k in ("doctor", "arzt", "ärzte", "physician")):
            category_match = "Doctors"
        elif any(k in target for k in ("physio", "ergo", "mfa", "ota")):
            category_match = "Physio / Ergo / MFA / OTA"
        elif any(k in target for k in ("it", "technology", "developer", "engineer", "software")):
            category_match = "IT / Technology"
        elif any(k in target for k in ("industry", "trade", "manufacturing")):
            category_match = "Industry / Trade"

    filters: dict = {"is_active": 1}
    if category_match:
        filters["category"] = category_match

    records = frappe.get_all(
        DOCTYPE_TARIFF_GROUP,
        filters=filters,
        fields=["tariff_group_name", "category", "description"],
        order_by="tariff_group_name asc",
    )

    if not records:
        records = frappe.get_all(
            DOCTYPE_TARIFF_GROUP,
            filters={"is_active": 1},
            fields=["tariff_group_name", "category", "description"],
            order_by="tariff_group_name asc",
        )

    return [
        {
            "id": r["tariff_group_name"],
            "name": r["tariff_group_name"],
            "display_name": r["tariff_group_name"],
            "category": r.get("category"),
            "description": r.get("description"),
        }
        for r in records
    ]
