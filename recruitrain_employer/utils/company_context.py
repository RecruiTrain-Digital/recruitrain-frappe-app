# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.utils.company_context
============================================

Utility helper for resolving active company context.
"""

from __future__ import annotations

from recruitrain_employer.utils.permissions import get_current_company, get_current_employer_user

get_authenticated_employer_user = get_current_employer_user

__all__ = ["get_current_company", "get_current_employer_user", "get_authenticated_employer_user"]
