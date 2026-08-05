# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.api
========================

Public API layer for the RecruiTrain Employer ATS.

This package exposes whitelisted Frappe API endpoints that are consumed by
external clients (mobile apps, web portals, third-party integrations).

Package Layout
--------------
- auth.py           Authentication & session management endpoints
- candidate.py      Candidate profile endpoints
- company.py        Company / organization endpoints
- employer.py       Employer user management endpoints
- jobs.py           Job Opening CRUD & search endpoints
- applications.py   Job Application lifecycle endpoints
- interviews.py     Interview scheduling & feedback endpoints
- offers.py         Offer letter generation & management endpoints
- dashboard.py      Aggregated metrics & dashboard data endpoints
- notifications.py  In-app notification delivery endpoints
- profile.py        Employer profile GET/POST/DELETE endpoints
- settings.py       Employer Settings (general, branding, notification,
                    security, recruitment, integration, audit) endpoints
- common.py         Shared utility endpoints (lookups, file uploads, etc.)

All endpoints MUST be decorated with ``@frappe.whitelist()`` (or the
role-restricted variant) and MUST delegate business logic to the
corresponding service module in ``recruitrain_employer.services``.

Usage
-----
Endpoints are reachable at::

    /api/method/recruitrain_employer.api.<module>.<function_name>
"""
