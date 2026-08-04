# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

import frappe

def execute():
    """Ensure Notification Log custom fields and Employer User notification_preferences column exist."""
    # 1. Ensure columns exist in MariaDB for tabEmployer User
    frappe.db.sql("""
        ALTER TABLE `tabEmployer User` 
        ADD COLUMN IF NOT EXISTS `notification_preferences` LONGTEXT;
    """)
    
    # Ensure custom field in DocType meta for Employer User
    if not frappe.db.exists("Custom Field", "Employer User-notification_preferences"):
        frappe.get_doc({
            "doctype": "Custom Field",
            "dt": "Employer User",
            "fieldname": "notification_preferences",
            "label": "Notification Preferences",
            "fieldtype": "Code",
            "options": "JSON",
            "insert_after": "status"
        }).insert(ignore_permissions=True)

    # 2. Ensure columns exist in MariaDB for tabNotification Log
    frappe.db.sql("""
        ALTER TABLE `tabNotification Log` 
        ADD COLUMN IF NOT EXISTS `company` VARCHAR(140),
        ADD COLUMN IF NOT EXISTS `priority` VARCHAR(50) DEFAULT 'Medium',
        ADD COLUMN IF NOT EXISTS `category` VARCHAR(140) DEFAULT 'General',
        ADD COLUMN IF NOT EXISTS `recipient_type` VARCHAR(50) DEFAULT 'Employer User',
        ADD COLUMN IF NOT EXISTS `read_at` DATETIME(6),
        ADD COLUMN IF NOT EXISTS `metadata` LONGTEXT;
    """)

    # Ensure custom fields for Notification Log in Frappe
    custom_fields = [
        {"fieldname": "company", "label": "Company", "fieldtype": "Link", "options": "Company"},
        {"fieldname": "priority", "label": "Priority", "fieldtype": "Select", "options": "Low\nMedium\nHigh\nUrgent"},
        {"fieldname": "category", "label": "Category", "fieldtype": "Data"},
        {"fieldname": "recipient_type", "label": "Recipient Type", "fieldtype": "Data"},
        {"fieldname": "read_at", "label": "Read At", "fieldtype": "Datetime"},
        {"fieldname": "metadata", "label": "Metadata", "fieldtype": "Code", "options": "JSON"}
    ]

    for cf in custom_fields:
        cf_name = f"Notification Log-{cf['fieldname']}"
        if not frappe.db.exists("Custom Field", cf_name):
            doc = {
                "doctype": "Custom Field",
                "dt": "Notification Log",
                "fieldname": cf["fieldname"],
                "label": cf["label"],
                "fieldtype": cf["fieldtype"],
                "insert_after": "read"
            }
            if "options" in cf:
                doc["options"] = cf["options"]
            frappe.get_doc(doc).insert(ignore_permissions=True)

    # 3. Property Setter for type options
    new_options = "Mention\nEnergy Point\nAssignment\nShare\nAlert\nSystem\nApplication\nInterview\nOffer\nCandidate\nJob\nGeneral"
    ps_name = frappe.db.get_value("Property Setter", {"doc_type": "Notification Log", "field_name": "type", "property": "options"}, "name")
    if ps_name:
        frappe.db.set_value("Property Setter", ps_name, "value", new_options)
    else:
        frappe.make_property_setter({
            "doctype": "Notification Log",
            "fieldname": "type",
            "property": "options",
            "value": new_options,
            "property_type": "Small Text"
        })

    frappe.clear_cache(doctype="Notification Log")
    frappe.db.commit()

