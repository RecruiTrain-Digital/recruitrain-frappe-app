# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
Migration patch to seed default master data records (Department, Profession, Employment Type, Industry).
"""

from recruitrain_employer.services.master_seed_service import ensure_master_records_exist


def execute():
    """Execute master data seeding during bench migrate."""
    ensure_master_records_exist()
