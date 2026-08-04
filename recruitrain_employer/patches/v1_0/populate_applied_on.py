# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

import frappe


def execute():
    """Populate missing applied_on values in Job Application from creation timestamp."""
    frappe.db.sql(
        """
        UPDATE `tabJob Application`
        SET applied_on = DATE(creation)
        WHERE applied_on IS NULL OR applied_on = '' OR applied_on = 'None'
        """
    )
