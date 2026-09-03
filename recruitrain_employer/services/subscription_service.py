# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.services.subscription_service
====================================================

Subscription and Entitlement Engine Service for RecruitTrain ATS.

Single source of truth for subscription plans, company subscriptions,
usage tracking, quota validation, and feature entitlement checks.
"""

from __future__ import annotations

from typing import Any
import frappe
from frappe.utils import add_days, getdate, nowdate, today

from recruitrain_employer.utils.constants import (
    DOCTYPE_BILLING_TRANSACTION,
    DOCTYPE_COMPANY,
    DOCTYPE_COMPANY_SUBSCRIPTION,
    DOCTYPE_JOB_OPENING,
    DOCTYPE_SUBSCRIPTION_PLAN,
    DOCTYPE_SUBSCRIPTION_USAGE,
    JOB_STATUS_OPEN,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_EXPIRED,
    SUBSCRIPTION_STATUS_TRIAL,
)
from recruitrain_employer.utils.exceptions import (
    ATSCompanyNotFoundError,
    ATSNotFoundError,
    PlanLimitExceededError,
    SubscriptionExpiredError,
)
from recruitrain_employer.validators.quota_validator import QuotaValidator


class SubscriptionService:
    """Service encapsulating all subscription, usage, and quota business logic."""

    METRIC_FIELD_MAP = {
        "active_jobs": "current_active_jobs",
        "current_active_jobs": "current_active_jobs",
        "recruiters": "current_recruiters",
        "current_recruiters": "current_recruiters",
        "candidates": "current_candidates",
        "current_candidates": "current_candidates",
        "storage": "storage_used_gb",
        "storage_gb": "storage_used_gb",
        "storage_used_gb": "storage_used_gb",
        "email": "email_used",
        "email_used": "email_used",
        "sms": "sms_used",
        "sms_used": "sms_used",
        "ai_credits": "ai_credits_used",
        "ai_credits_used": "ai_credits_used",
    }

    def get_active_subscription(self, company: str) -> Any:
        """Retrieve the active or trial Company Subscription document for a company.

        If no subscription document exists, a default Starter subscription is initialized.
        """
        if not company:
            raise ATSCompanyNotFoundError("Company name is required to fetch active subscription.")

        # Check existing subscription for company
        sub_name = frappe.db.get_value(
            DOCTYPE_COMPANY_SUBSCRIPTION,
            {"company": company, "status": ["in", [SUBSCRIPTION_STATUS_ACTIVE, SUBSCRIPTION_STATUS_TRIAL]]},
            "name",
            order_by="creation desc",
        )

        if not sub_name:
            # Check any subscription for company regardless of status
            sub_name = frappe.db.get_value(
                DOCTYPE_COMPANY_SUBSCRIPTION,
                {"company": company},
                "name",
                order_by="creation desc",
            )

        if sub_name:
            sub_doc = frappe.get_doc(DOCTYPE_COMPANY_SUBSCRIPTION, sub_name)
        else:
            # Automatically provision default Starter trial subscription
            sub_doc = self._create_default_subscription(company)

        return sub_doc

    def get_plan(self, company: str) -> Any:
        """Retrieve the active Subscription Plan document for a company."""
        sub_doc = self.get_active_subscription(company)
        plan_name = getattr(sub_doc, "subscription_plan", None) or "Starter"

        if frappe.db.exists(DOCTYPE_SUBSCRIPTION_PLAN, plan_name):
            return frappe.get_doc(DOCTYPE_SUBSCRIPTION_PLAN, plan_name)

        # Fallback to first available active plan or create Starter plan
        plans = frappe.get_all(DOCTYPE_SUBSCRIPTION_PLAN, filters={"is_active": 1}, limit=1)
        if plans:
            return frappe.get_doc(DOCTYPE_SUBSCRIPTION_PLAN, plans[0].name)
        
        return self._create_default_plan("Starter")

    def get_usage(self, company: str) -> Any:
        """Retrieve or initialize the Subscription Usage document for a company."""
        if not company:
            raise ATSCompanyNotFoundError("Company name is required to fetch usage.")

        usage_name = frappe.db.get_value(DOCTYPE_SUBSCRIPTION_USAGE, {"company": company}, "name")

        if usage_name:
            return frappe.get_doc(DOCTYPE_SUBSCRIPTION_USAGE, usage_name)

        # Provision new Subscription Usage record
        sub_doc = self.get_active_subscription(company)
        usage_doc = frappe.new_doc(DOCTYPE_SUBSCRIPTION_USAGE)
        usage_doc.company = company
        usage_doc.company_subscription = sub_doc.name
        usage_doc.current_active_jobs = 0
        usage_doc.current_recruiters = 0
        usage_doc.current_candidates = 0
        usage_doc.storage_used_gb = 0.0
        usage_doc.email_used = 0
        usage_doc.sms_used = 0
        usage_doc.ai_credits_used = 0
        usage_doc.insert(ignore_permissions=True)
        frappe.db.commit()

        # Recalculate true counts from database
        return self.recalculate_usage(company)

    def increment_usage(self, company: str, metric: str, amount: int | float = 1) -> bool:
        """Atomically increment a usage counter for a company."""
        field_name = self.METRIC_FIELD_MAP.get(metric.lower())
        if not field_name:
            return False

        usage_doc = self.get_usage(company)
        frappe.db.sql(
            f"""
            UPDATE `tabSubscription Usage`
            SET `{field_name}` = `{field_name}` + %s
            WHERE `company` = %s
            """,
            (amount, company),
        )
        return True

    def decrement_usage(self, company: str, metric: str, amount: int | float = 1) -> bool:
        """Atomically decrement a usage counter for a company (floor at 0)."""
        field_name = self.METRIC_FIELD_MAP.get(metric.lower())
        if not field_name:
            return False

        usage_doc = self.get_usage(company)
        frappe.db.sql(
            f"""
            UPDATE `tabSubscription Usage`
            SET `{field_name}` = GREATEST(0, `{field_name}` - %s)
            WHERE `company` = %s
            """,
            (amount, company),
        )
        return True

    def validate_active_subscription(self, company: str) -> Any:
        """Validate that company has an active, valid subscription.

        Raises SubscriptionExpiredError if subscription is Expired, Cancelled, Paused, Past Due, or Trial Expired.
        """
        sub_doc = self.get_active_subscription(company)
        QuotaValidator.validate_subscription_status(sub_doc)
        return sub_doc

    def validate_entitlement(self, company: str, feature: str) -> bool:
        """Validate whether a feature entitlement is enabled for a company's subscription plan.

        Raises PlanLimitExceededError or SubscriptionExpiredError.
        """
        sub_doc = self.get_active_subscription(company)
        QuotaValidator.validate_subscription_status(sub_doc)
        plan_doc = self.get_plan(company)
        return QuotaValidator.validate_entitlement(plan_doc, feature)

    def validate_quota(self, company: str, resource: str, amount: int | float = 1) -> bool:
        """Validate whether a company has sufficient quota for a resource.

        Raises PlanLimitExceededError or SubscriptionExpiredError.
        """
        sub_doc = self.get_active_subscription(company)
        plan_doc = self.get_plan(company)
        usage_doc = self.get_usage(company)

        return QuotaValidator.validate_quota(
            subscription_doc=sub_doc,
            plan_doc=plan_doc,
            usage_doc=usage_doc,
            resource=resource,
            amount=amount,
        )

    def check_plan_limit(self, company: str, resource: str) -> bool:
        """Reusable helper method to check plan limit for a company resource."""
        return self.validate_quota(company, resource)

    def recalculate_usage(self, company: str) -> Any:
        """Recalculate exact usage metrics directly from database state."""
        if not company:
            return None

        # 1. Active Jobs
        active_jobs = frappe.db.count(
            DOCTYPE_JOB_OPENING,
            filters={"company": company, "status": JOB_STATUS_OPEN},
        )

        # 2. Active Recruiters (Employer Users)
        recruiters = frappe.db.count(
            "Employer User",
            filters={"company": company, "status": "Active"},
        )

        # 3. Candidates
        candidates = frappe.db.count(
            "Candidate",
            filters={"company": company},
        )

        # 4. Storage (File attachments in GB)
        storage_bytes = frappe.db.sql(
            """
            SELECT COALESCE(SUM(file_size), 0)
            FROM `tabFile`
            WHERE `attached_to_doctype` IN ('Candidate', 'Candidate Document', 'Job Opening', 'Company')
            """,
            as_list=True,
        )[0][0] or 0
        storage_gb = round(storage_bytes / (1024 * 1024 * 1024), 4)

        usage_doc = self.get_usage(company)
        usage_doc.current_active_jobs = active_jobs
        usage_doc.current_recruiters = recruiters
        usage_doc.current_candidates = candidates
        usage_doc.storage_used_gb = storage_gb
        usage_doc.save(ignore_permissions=True)
        frappe.db.commit()

        return usage_doc

    def get_available_plans(self) -> list[dict]:
        """Fetch all active Subscription Plans available for subscription/upgrade."""
        plans = frappe.get_all(
            DOCTYPE_SUBSCRIPTION_PLAN,
            filters={"is_active": 1},
            fields=[
                "name",
                "plan_name",
                "description",
                "monthly_price",
                "yearly_price",
                "currency",
                "trial_days",
                "display_order",
                "max_active_jobs",
                "max_recruiters",
                "max_candidates",
                "storage_gb",
                "monthly_email_limit",
                "monthly_sms_limit",
                "ai_credits",
                "can_use_analytics",
                "can_use_talent_pool",
                "can_use_api",
                "can_use_notifications",
                "priority_support",
            ],
            order_by="display_order asc, monthly_price asc",
        )
        return plans

    def get_usage_with_limits(self, company: str) -> dict:
        """Return structured usage and quota details for frontend display."""
        sub_doc = self.get_active_subscription(company)
        plan_doc = self.get_plan(company)
        usage_doc = self.get_usage(company)

        return {
            "company": company,
            "subscription": {
                "name": sub_doc.name,
                "company": company,
                "subscription_plan": plan_doc.plan_name,
                "plan": plan_doc.plan_name,
                "status": sub_doc.status,
                "start_date": str(sub_doc.start_date),
                "end_date": str(sub_doc.end_date) if sub_doc.end_date else None,
                "billing_cycle": sub_doc.billing_cycle,
                "auto_renew": sub_doc.auto_renew,
            },
            "limits": {
                "max_active_jobs": plan_doc.max_active_jobs,
                "max_recruiters": plan_doc.max_recruiters,
                "max_candidates": plan_doc.max_candidates,
                "storage_gb": plan_doc.storage_gb,
                "monthly_email_limit": plan_doc.monthly_email_limit,
                "monthly_sms_limit": plan_doc.monthly_sms_limit,
                "ai_credits": plan_doc.ai_credits,
            },
            "usage": {
                "current_active_jobs": usage_doc.current_active_jobs,
                "current_recruiters": usage_doc.current_recruiters,
                "current_candidates": usage_doc.current_candidates,
                "storage_used_gb": usage_doc.storage_used_gb,
                "email_used": usage_doc.email_used,
                "sms_used": usage_doc.sms_used,
                "ai_credits_used": usage_doc.ai_credits_used,
            },
            "quotas": {
                "active_jobs": {
                    "used": usage_doc.current_active_jobs,
                    "limit": plan_doc.max_active_jobs,
                    "unlimited": plan_doc.max_active_jobs <= 0 if plan_doc.max_active_jobs is not None else True,
                },
                "recruiters": {
                    "used": usage_doc.current_recruiters,
                    "limit": plan_doc.max_recruiters,
                    "unlimited": plan_doc.max_recruiters <= 0 if plan_doc.max_recruiters is not None else True,
                },
                "candidates": {
                    "used": usage_doc.current_candidates,
                    "limit": plan_doc.max_candidates,
                    "unlimited": plan_doc.max_candidates <= 0 if plan_doc.max_candidates is not None else True,
                },
                "storage_gb": {
                    "used": usage_doc.storage_used_gb,
                    "limit": plan_doc.storage_gb,
                    "unlimited": plan_doc.storage_gb <= 0 if plan_doc.storage_gb is not None else True,
                },
                "email": {
                    "used": usage_doc.email_used,
                    "limit": plan_doc.monthly_email_limit,
                    "unlimited": plan_doc.monthly_email_limit <= 0 if plan_doc.monthly_email_limit is not None else True,
                },
                "sms": {
                    "used": usage_doc.sms_used,
                    "limit": plan_doc.monthly_sms_limit,
                    "unlimited": plan_doc.monthly_sms_limit <= 0 if plan_doc.monthly_sms_limit is not None else True,
                },
                "ai_credits": {
                    "used": usage_doc.ai_credits_used,
                    "limit": plan_doc.ai_credits,
                    "unlimited": plan_doc.ai_credits <= 0 if plan_doc.ai_credits is not None else True,
                },
            },
            "features": {
                "analytics": plan_doc.can_use_analytics == 1,
                "talent_pool": plan_doc.can_use_talent_pool == 1,
                "api": plan_doc.can_use_api == 1,
                "notifications": plan_doc.can_use_notifications == 1,
                "priority_support": plan_doc.priority_support == 1,
            },
        }

    def preview_upgrade(self, company: str, new_plan_name: str) -> dict:
        """Preview limits and pricing changes when switching to new_plan_name.

        Includes downgrade safety check if current usage exceeds new plan limits.
        """
        if not frappe.db.exists(DOCTYPE_SUBSCRIPTION_PLAN, new_plan_name):
            raise ATSNotFoundError(f"Subscription plan '{new_plan_name}' not found.", doctype=DOCTYPE_SUBSCRIPTION_PLAN, name=new_plan_name)

        current_sub = self.get_active_subscription(company)
        current_plan = self.get_plan(company)
        target_plan = frappe.get_doc(DOCTYPE_SUBSCRIPTION_PLAN, new_plan_name)
        usage_doc = self.get_usage(company)

        # Check downgrade safety (whether current usage fits within target plan)
        violations = []
        if target_plan.max_active_jobs > 0 and usage_doc.current_active_jobs > target_plan.max_active_jobs:
            violations.append(f"Active jobs count ({usage_doc.current_active_jobs}) exceeds target plan limit ({target_plan.max_active_jobs}).")
        if target_plan.max_recruiters > 0 and usage_doc.current_recruiters > target_plan.max_recruiters:
            violations.append(f"Recruiter count ({usage_doc.current_recruiters}) exceeds target plan limit ({target_plan.max_recruiters}).")
        if target_plan.max_candidates > 0 and usage_doc.current_candidates > target_plan.max_candidates:
            violations.append(f"Candidate count ({usage_doc.current_candidates}) exceeds target plan limit ({target_plan.max_candidates}).")

        is_downgrade = target_plan.monthly_price < current_plan.monthly_price
        can_change = len(violations) == 0

        return {
            "company": company,
            "current_plan": current_plan.plan_name,
            "target_plan": target_plan.plan_name,
            "is_downgrade": is_downgrade,
            "can_change": can_change,
            "downgrade_violations": violations,
            "price_difference": {
                "monthly": target_plan.monthly_price - current_plan.monthly_price,
                "yearly": target_plan.yearly_price - current_plan.yearly_price,
                "currency": target_plan.currency or current_plan.currency,
            },
            "limit_changes": {
                "max_active_jobs": {"current": current_plan.max_active_jobs, "target": target_plan.max_active_jobs},
                "max_recruiters": {"current": current_plan.max_recruiters, "target": target_plan.max_recruiters},
                "max_candidates": {"current": current_plan.max_candidates, "target": target_plan.max_candidates},
                "storage_gb": {"current": current_plan.storage_gb, "target": target_plan.storage_gb},
            },
        }

    def get_invoices(self, company: str, limit: int = 50) -> list[dict]:
        """Fetch billing invoices (Billing Transactions) for the company."""
        if not company:
            raise ATSCompanyNotFoundError("Company name is required to fetch invoices.")

        txns = frappe.get_all(
            DOCTYPE_BILLING_TRANSACTION,
            filters={"company": company},
            fields=[
                "name",
                "invoice_number",
                "amount",
                "currency",
                "payment_status",
                "stripe_payment_intent",
                "receipt_url",
                "paid_at",
                "creation",
            ],
            order_by="creation desc",
            limit_page_length=limit,
        )
        return txns

    def get_payment_history(self, company: str, limit: int = 50) -> list[dict]:
        """Fetch payment transaction history for the company."""
        return self.get_invoices(company, limit=limit)

    def get_billing_overview(self, company: str) -> dict:
        """Fetch complete billing overview including subscription, limits, and recent invoices."""
        usage_limits = self.get_usage_with_limits(company)
        recent_invoices = self.get_invoices(company, limit=10)
        return {
            **usage_limits,
            "recent_invoices": recent_invoices,
            "payment_history": recent_invoices,
        }

    def cancel_subscription(self, company: str, at_period_end: bool = True) -> dict:
        """Cancel subscription for company by interacting with Stripe server-side."""
        from recruitrain_employer.services.stripe_service import StripeService
        sub_doc = self.get_active_subscription(company)
        stripe_sub_id = getattr(sub_doc, "stripe_subscription_id", None)

        if stripe_sub_id:
            StripeService().cancel_subscription(stripe_sub_id, at_period_end=at_period_end)

        sub_doc.cancel_at_period_end = 1 if at_period_end else 0
        if not at_period_end:
            sub_doc.status = "Cancelled"
            sub_doc.cancelled_at = frappe.utils.now_datetime()
        sub_doc.save(ignore_permissions=True)
        frappe.db.commit()

        return {
            "company": company,
            "subscription": sub_doc.name,
            "status": sub_doc.status,
            "cancel_at_period_end": sub_doc.cancel_at_period_end,
            "message": "Subscription cancelled successfully."
        }

    def resume_subscription(self, company: str) -> dict:
        """Resume a pending cancelled subscription for company by interacting with Stripe server-side."""
        from recruitrain_employer.services.stripe_service import StripeService
        sub_doc = self.get_active_subscription(company)
        stripe_sub_id = getattr(sub_doc, "stripe_subscription_id", None)

        if stripe_sub_id:
            StripeService().resume_subscription(stripe_sub_id)

        sub_doc.cancel_at_period_end = 0
        if sub_doc.status == "Cancelled":
            sub_doc.status = "Active"
        sub_doc.save(ignore_permissions=True)
        frappe.db.commit()

        return {
            "company": company,
            "subscription": sub_doc.name,
            "status": sub_doc.status,
            "cancel_at_period_end": sub_doc.cancel_at_period_end,
            "message": "Subscription resumed successfully."
        }

    def can_create_job(self, company: str) -> bool:
        """Check if company can create a new job opening based on plan limits."""
        return self.validate_quota(company, "active_jobs")

    def can_add_candidate(self, company: str) -> bool:
        """Check if company can add a candidate based on plan limits."""
        return self.validate_quota(company, "candidates")

    def can_add_employer_user(self, company: str) -> bool:
        """Check if company can add an employer recruiter user based on plan limits."""
        return self.validate_quota(company, "recruiters")

    # ------------------------------------------------------------------
    # Private Helper Methods
    # ------------------------------------------------------------------

    def _create_default_plan(self, plan_name: str = "Starter") -> Any:
        """Create a default Subscription_Plan_Recruitrain record if none exists."""
        if frappe.db.exists(DOCTYPE_SUBSCRIPTION_PLAN, plan_name):
            return frappe.get_doc(DOCTYPE_SUBSCRIPTION_PLAN, plan_name)

        plan_doc = frappe.new_doc(DOCTYPE_SUBSCRIPTION_PLAN)
        plan_doc.plan_name = plan_name
        plan_doc.description = f"Default {plan_name} Plan"
        plan_doc.monthly_price = 0.0 if plan_name == "Free" else (999.0 if plan_name == "Starter" else 4999.0)
        plan_doc.yearly_price = plan_doc.monthly_price * 10
        plan_doc.currency = "INR"
        plan_doc.trial_days = 14
        plan_doc.is_active = 1
        plan_doc.display_order = 1
        plan_doc.max_active_jobs = 5 if plan_name == "Starter" else (20 if plan_name == "Professional" else -1)
        plan_doc.max_recruiters = 2 if plan_name == "Starter" else (10 if plan_name == "Professional" else -1)
        plan_doc.max_candidates = 200 if plan_name == "Starter" else (5000 if plan_name == "Professional" else -1)
        plan_doc.storage_gb = 2.0 if plan_name == "Starter" else (20.0 if plan_name == "Professional" else -1)
        plan_doc.monthly_email_limit = 500
        plan_doc.monthly_sms_limit = 100
        plan_doc.ai_credits = 50
        plan_doc.can_use_analytics = 1
        plan_doc.can_use_talent_pool = 1 if plan_name != "Starter" else 0
        plan_doc.can_use_api = 1 if plan_name == "Enterprise" else 0
        plan_doc.can_use_notifications = 1
        plan_doc.stripe_product_id = f"prod_{plan_name.lower()}"
        plan_doc.insert(ignore_permissions=True)
        frappe.db.commit()

        return plan_doc

    def _create_default_subscription(self, company: str) -> Any:
        """Create a default 14-day trial subscription for a company."""
        plan_doc = self._create_default_plan("Starter")

        start = getdate(today())
        end = add_days(start, plan_doc.trial_days or 14)

        sub_doc = frappe.new_doc(DOCTYPE_COMPANY_SUBSCRIPTION)
        sub_doc.company = company
        sub_doc.subscription_plan = plan_doc.name
        sub_doc.status = SUBSCRIPTION_STATUS_TRIAL
        sub_doc.auto_renew = 0
        sub_doc.start_date = start
        sub_doc.end_date = end
        sub_doc.renewal_date = end
        sub_doc.billing_cycle = "Trial"
        sub_doc.insert(ignore_permissions=True)
        frappe.db.commit()

        return sub_doc


def check_plan_limit(company: str, resource: str) -> bool:
    """Standalone helper function to check whether a company has available quota for a resource.

    Raises PlanLimitExceededError or SubscriptionExpiredError if limit is reached or subscription is invalid.
    """
    return SubscriptionService().check_plan_limit(company, resource)
