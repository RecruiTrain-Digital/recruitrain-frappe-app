# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.utils.subscription_hooks
===============================================

DocType event hooks for automatic usage updating and plan limit validation.
"""

from __future__ import annotations

import frappe
from recruitrain_employer.services.subscription_service import SubscriptionService, check_plan_limit
from recruitrain_employer.utils.constants import JOB_STATUS_OPEN


# ------------------------------------------------------------------
# Job Opening Hooks
# ------------------------------------------------------------------

def on_job_opening_before_insert(doc, method=None):
    """Validate active jobs quota before creating a new Job Opening."""
    company = getattr(doc, "company", None)
    if company:
        status = getattr(doc, "status", None) or JOB_STATUS_OPEN
        if status == JOB_STATUS_OPEN:
            check_plan_limit(company, "active_jobs")


def on_job_opening_after_insert(doc, method=None):
    """Increment active jobs counter after creating a new Open job."""
    company = getattr(doc, "company", None)
    status = getattr(doc, "status", None)
    if company and status == JOB_STATUS_OPEN:
        SubscriptionService().increment_usage(company, "active_jobs")


def on_job_opening_on_update(doc, method=None):
    """Handle status changes on existing Job Opening (Open <-> Non-Open)."""
    # Ignore insert cycle (handled by after_insert)
    if getattr(doc.flags, "in_insert", False) or not doc.get_doc_before_save():
        return

    company = getattr(doc, "company", None)
    if not company:
        return

    if doc.has_value_changed("status"):
        old_doc = doc.get_doc_before_save()
        old_status = old_doc.get("status") if old_doc else None
        new_status = doc.get("status")

        if old_status != JOB_STATUS_OPEN and new_status == JOB_STATUS_OPEN:
            check_plan_limit(company, "active_jobs")
            SubscriptionService().increment_usage(company, "active_jobs")
        elif old_status == JOB_STATUS_OPEN and new_status != JOB_STATUS_OPEN:
            SubscriptionService().decrement_usage(company, "active_jobs")


def on_job_opening_on_trash(doc, method=None):
    """Decrement active jobs counter when an open job is deleted."""
    company = getattr(doc, "company", None)
    status = getattr(doc, "status", None)
    if company and status == JOB_STATUS_OPEN:
        SubscriptionService().decrement_usage(company, "active_jobs")


# ------------------------------------------------------------------
# Employer User Hooks
# ------------------------------------------------------------------

def on_employer_user_before_insert(doc, method=None):
    """Validate recruiters quota before adding an Employer User."""
    company = getattr(doc, "company", None)
    if company:
        check_plan_limit(company, "recruiters")


def on_employer_user_after_insert(doc, method=None):
    """Increment recruiters counter after adding an Employer User."""
    company = getattr(doc, "company", None)
    if company:
        SubscriptionService().increment_usage(company, "recruiters")


def on_employer_user_on_update(doc, method=None):
    """Handle recruiter activation / deactivation on existing Employer User."""
    if getattr(doc.flags, "in_insert", False) or not doc.get_doc_before_save():
        return

    company = getattr(doc, "company", None)
    if not company:
        return

    if doc.has_value_changed("status"):
        old_doc = doc.get_doc_before_save()
        old_status = old_doc.get("status") if old_doc else None
        new_status = doc.get("status")

        if old_status != "Active" and new_status == "Active":
            check_plan_limit(company, "recruiters")
            SubscriptionService().increment_usage(company, "recruiters")
        elif old_status == "Active" and new_status != "Active":
            SubscriptionService().decrement_usage(company, "recruiters")


def on_employer_user_on_trash(doc, method=None):
    """Decrement recruiters counter when an Employer User is deleted."""
    company = getattr(doc, "company", None)
    if company:
        SubscriptionService().decrement_usage(company, "recruiters")


# ------------------------------------------------------------------
# Candidate Hooks
# ------------------------------------------------------------------

def on_candidate_before_insert(doc, method=None):
    """Validate candidate quota before importing / creating a Candidate."""
    company = getattr(doc, "company", None)
    if company:
        check_plan_limit(company, "candidates")


def on_candidate_after_insert(doc, method=None):
    """Increment candidates counter after creating / importing a Candidate."""
    company = getattr(doc, "company", None)
    if company:
        SubscriptionService().increment_usage(company, "candidates")


def on_candidate_on_trash(doc, method=None):
    """Decrement candidates counter when a Candidate is deleted."""
    company = getattr(doc, "company", None)
    if company:
        SubscriptionService().decrement_usage(company, "candidates")
