# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.services
===============================

Business Logic / Service Layer for the RecruiTrain Employer ATS.

This package sits between the API layer (``recruitrain_employer.api``) and the
Frappe ORM / DocType layer.  Each module owns the business logic for one
domain aggregate.

Package Layout
--------------
- auth_service.py          Authentication, registration, and session logic
- candidate_service.py     Candidate profile and sub-resource operations
- company_service.py       Company profile management
- employer_service.py      Employer user and team management
- profile_service.py       Employer Profile retrieval, partial updates, and avatar uploads
- job_service.py           Job Opening lifecycle (create, publish, close, search)
- application_service.py   Job Application pipeline and stage transitions
- interview_service.py     Interview scheduling, rescheduling, and feedback
- offer_service.py         Offer generation, sending, and response tracking
- dashboard_service.py     Aggregated metrics and reporting queries
- notification_service.py  Notification delivery and preference management
- subscription_service.py   Subscription and entitlement management (quotas, usage, plan limits)

Design Principles
-----------------
1. Services MUST NOT expose themselves directly to HTTP; they are called by
   the API layer only.
2. Services MUST use ``frappe.get_doc()`` / ``frappe.get_list()`` for all
   DocType interactions — never raw SQL except where performance demands it
   and it is clearly documented.
3. Services MUST raise exceptions from ``recruitrain_employer.utils.exceptions``
   rather than raw ``frappe.exceptions`` so the API layer can translate them
   into standardised error responses.
4. Services SHOULD be instantiated per-request (stateless) unless a compelling
   reason for caching exists.
"""

from recruitrain_employer.services.calendar_service import CalendarService
from recruitrain_employer.services.subscription_service import SubscriptionService, check_plan_limit
from recruitrain_employer.services.webhook_service import WebhookService

__all__ = ["CalendarService", "SubscriptionService", "check_plan_limit", "WebhookService"]

