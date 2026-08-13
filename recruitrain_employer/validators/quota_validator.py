# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.validators.quota_validator
=================================================

Quota and Entitlement Validation Engine for RecruitTrain ATS.

Enforces subscription status, resource quotas, and feature entitlements.
Raises PlanLimitExceededError or SubscriptionExpiredError when limits or status checks fail.
"""

from __future__ import annotations

from typing import Any
import frappe
from frappe.utils import getdate, nowdate, today

from recruitrain_employer.utils.constants import (
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_CANCELLED,
    SUBSCRIPTION_STATUS_EXPIRED,
    SUBSCRIPTION_STATUS_PAST_DUE,
    SUBSCRIPTION_STATUS_PAUSED,
    SUBSCRIPTION_STATUS_TRIAL,
)
from recruitrain_employer.utils.exceptions import (
    PlanLimitExceededError,
    SubscriptionExpiredError,
)


class QuotaValidator:
    """Validates company subscription status, quota usage, and feature entitlements."""

    RESOURCE_MAP = {
        "active_jobs": {
            "plan_field": "max_active_jobs",
            "usage_field": "current_active_jobs",
            "label": "Active Jobs",
        },
        "recruiters": {
            "plan_field": "max_recruiters",
            "usage_field": "current_recruiters",
            "label": "Recruiters",
        },
        "candidates": {
            "plan_field": "max_candidates",
            "usage_field": "current_candidates",
            "label": "Candidates",
        },
        "storage": {
            "plan_field": "storage_gb",
            "usage_field": "storage_used_gb",
            "label": "Storage (GB)",
        },
        "storage_gb": {
            "plan_field": "storage_gb",
            "usage_field": "storage_used_gb",
            "label": "Storage (GB)",
        },
        "email": {
            "plan_field": "monthly_email_limit",
            "usage_field": "email_used",
            "label": "Monthly Emails",
        },
        "sms": {
            "plan_field": "monthly_sms_limit",
            "usage_field": "sms_used",
            "label": "Monthly SMS",
        },
        "ai_credits": {
            "plan_field": "ai_credits",
            "usage_field": "ai_credits_used",
            "label": "AI Credits",
        },
    }

    FEATURE_MAP = {
        "analytics": ["can_use_analytics"],
        "talent_pool": ["can_use_talent_pool"],
        "api": ["can_use_api"],
        "interview_scheduler": ["can_use_interview_scheduler", "can_use_interview_schedulercan_use_interview_scheduler"],
        "custom_pipeline": ["can_use_custom_pipeline", "can_use_custom_pipelinecan_use_custom_pipeline"],
        "branding": ["can_use_branding", "can_use_brandingcan_use_branding"],
        "notes": ["can_use_notes", "can_use_notescan_use_notes"],
        "notifications": ["can_use_notifications"],
        "export_csv": ["can_export_csv", "can_export_csvcan_export_csv"],
        "priority_support": ["priority_support"],
    }

    @classmethod
    def validate_subscription_status(cls, subscription_doc: Any) -> bool:
        """Validate if a subscription is active and unexpired.

        Raises SubscriptionExpiredError if inactive or expired.
        """
        if not subscription_doc:
            raise SubscriptionExpiredError("No active subscription found for company.")

        status = getattr(subscription_doc, "status", None) or subscription_doc.get("status")
        if status in [SUBSCRIPTION_STATUS_CANCELLED, SUBSCRIPTION_STATUS_EXPIRED, SUBSCRIPTION_STATUS_PAST_DUE, SUBSCRIPTION_STATUS_PAUSED]:
            raise SubscriptionExpiredError(
                f"Subscription is {status}. Please upgrade or renew your plan.",
                details={"status": status, "company": getattr(subscription_doc, "company", None)},
            )

        # Check end date / trial expiration
        end_date = getattr(subscription_doc, "end_date", None) or subscription_doc.get("end_date")
        current_date = getdate(today())

        if end_date and getdate(end_date) < current_date:
            # Auto update status to Expired if past end date
            if hasattr(subscription_doc, "status"):
                try:
                    subscription_doc.status = SUBSCRIPTION_STATUS_EXPIRED
                    subscription_doc.save(ignore_permissions=True)
                except Exception:
                    pass
            raise SubscriptionExpiredError(
                f"Subscription expired on {end_date}.",
                details={"end_date": str(end_date), "status": SUBSCRIPTION_STATUS_EXPIRED},
            )

        return True

    @classmethod
    def validate_quota(
        cls,
        subscription_doc: Any,
        plan_doc: Any,
        usage_doc: Any,
        resource: str,
        amount: int | float = 1,
    ) -> bool:
        """Validate whether current usage + amount fits within the subscription plan limit.

        Raises PlanLimitExceededError if limit is reached.
        """
        # First ensure subscription is valid
        cls.validate_subscription_status(subscription_doc)

        resource_key = resource.lower()
        if resource_key not in cls.RESOURCE_MAP:
            # Default fallback for unmapped resources
            return True

        mapping = cls.RESOURCE_MAP[resource_key]
        plan_field = mapping["plan_field"]
        usage_field = mapping["usage_field"]
        label = mapping["label"]

        # Fetch limit from plan
        limit = None
        if hasattr(plan_doc, plan_field):
            limit = getattr(plan_doc, plan_field)
        elif isinstance(plan_doc, dict):
            limit = plan_doc.get(plan_field)

        # Interpret limit <= 0 or None as Unlimited
        if limit is None or (isinstance(limit, (int, float)) and limit <= 0):
            return True

        # Fetch current usage
        current = 0
        if hasattr(usage_doc, usage_field):
            current = getattr(usage_doc, usage_field) or 0
        elif isinstance(usage_doc, dict):
            current = usage_doc.get(usage_field) or 0

        proposed = current + amount
        if proposed > limit:
            raise PlanLimitExceededError(
                message=f"Plan limit exceeded: Maximum allowed {label} is {limit} under your current plan ({plan_doc.get('plan_name') or 'Starter'}). Current: {current}.",
                resource=resource,
                limit=limit,
                current=current,
                details={
                    "resource": resource,
                    "label": label,
                    "limit": limit,
                    "current": current,
                    "proposed": proposed,
                    "plan_name": getattr(plan_doc, "plan_name", "Starter"),
                },
            )

        return True

    @classmethod
    def validate_entitlement(cls, plan_doc: Any, feature: str) -> bool:
        """Validate whether a boolean feature flag is enabled for the plan.

        Raises PlanLimitExceededError if feature is not enabled.
        """
        feature_key = feature.lower()
        field_variants = cls.FEATURE_MAP.get(feature_key, [f"can_use_{feature_key}", feature_key])

        enabled = False
        for field in field_variants:
            val = getattr(plan_doc, field, None) if hasattr(plan_doc, field) else plan_doc.get(field)
            if val in [1, True, "1"]:
                enabled = True
                break

        if not enabled:
            raise PlanLimitExceededError(
                message=f"Feature '{feature}' is not enabled in your current subscription plan ({getattr(plan_doc, 'plan_name', 'Starter')}).",
                resource=feature,
                details={"feature": feature, "enabled": False},
            )

        return True
