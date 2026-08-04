# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.services.dashboard_service
=================================================

Dashboard & Analytics Business Logic Service.

Owns all business logic related to:
- KPI metric aggregation for the employer dashboard
- Pipeline stage distribution summaries
- Hiring funnel conversion rate calculations
- Time-series reporting (applications over time, time-to-hire)
- Recent activity feed

All public methods on ``DashboardService`` are called exclusively from the
API layer (``recruitrain_employer.api.dashboard``).

DocTypes Used
-------------
- Job Opening
- Candidate
- Job Application
- Interview
- Offer
- Notification
- Activity Log

Frappe APIs Used
----------------
- frappe.db.count()
- frappe.get_all()
- frappe.get_meta()
"""

from __future__ import annotations

from datetime import date, datetime
import frappe

from recruitrain_employer.utils.constants import (
    APPLICATION_STAGES,
    DOCTYPE_CANDIDATE,
    DOCTYPE_INTERVIEW,
    DOCTYPE_JOB_APPLICATION,
    DOCTYPE_JOB_OPENING,
    DOCTYPE_NOTIFICATION,
    DOCTYPE_OFFER,
    JOB_STATUS_OPEN,
    OFFER_STATUS_DRAFT,
    OFFER_STATUS_SENT,
)
from recruitrain_employer.utils.exceptions import ATSServiceError


class DashboardService:
    """Encapsulates business logic for dashboard metric aggregation.

    Usage
    -----
    ::

        service = DashboardService()
        overview = service.get_overview()
    """

    # ------------------------------------------------------------------
    # Overview Widgets
    # ------------------------------------------------------------------

    def get_overview(self, company: str | None = None) -> dict:
        """Return top-level KPI metrics for the employer's dashboard.

        Parameters
        ----------
        company : str or None, optional
            The Company name to scope metrics to.

        Returns
        -------
        dict
            ``{
                "open_jobs": int,
                "total_candidates": int,
                "total_applications": int,
                "todays_interviews": int,
                "pending_offers": int,
                "unread_notifications": int
            }``
        """
        try:
            # 1. Open Jobs
            job_filters = {"status": JOB_STATUS_OPEN}
            if company:
                job_filters["company"] = company
            open_jobs = frappe.db.count(DOCTYPE_JOB_OPENING, filters=job_filters)

            # 2. Total Candidates
            candidate_filters = {}
            if company and frappe.get_meta(DOCTYPE_CANDIDATE).has_field("company"):
                candidate_filters["company"] = company
            total_candidates = frappe.db.count(DOCTYPE_CANDIDATE, filters=candidate_filters)

            # 3. Total Applications
            app_filters = {}
            if company and frappe.get_meta(DOCTYPE_JOB_APPLICATION).has_field("company"):
                app_filters["company"] = company
            total_applications = frappe.db.count(DOCTYPE_JOB_APPLICATION, filters=app_filters)

            # 4. Today's Interviews
            today_str = str(frappe.utils.today())
            interview_filters = {}
            if company and frappe.get_meta(DOCTYPE_INTERVIEW).has_field("company"):
                interview_filters["company"] = company

            todays_interviews = 0
            try:
                if frappe.get_meta(DOCTYPE_INTERVIEW).has_field("scheduled_on"):
                    interview_filters["scheduled_on"] = ["between", [f"{today_str} 00:00:00", f"{today_str} 23:59:59"]]
                    todays_interviews = frappe.db.count(DOCTYPE_INTERVIEW, filters=interview_filters)
                else:
                    todays_interviews = frappe.db.count(DOCTYPE_INTERVIEW, filters=interview_filters)
            except Exception:
                todays_interviews = 0

            # 5. Pending Offers (Correct field in Offer schema is `offer_status`)
            offer_filters = {"offer_status": ["in", [OFFER_STATUS_SENT, OFFER_STATUS_DRAFT, "Sent", "Draft"]]}
            if company and frappe.get_meta(DOCTYPE_OFFER).has_field("company"):
                offer_filters["company"] = company
            pending_offers = 0
            try:
                pending_offers = frappe.db.count(DOCTYPE_OFFER, filters=offer_filters)
            except Exception:
                pending_offers = 0

            # 6. Unread Notifications
            unread_notifications = 0
            try:
                if frappe.db.exists("DocType", DOCTYPE_NOTIFICATION):
                    notif_filters = {}
                    meta = frappe.get_meta(DOCTYPE_NOTIFICATION)
                    if meta.has_field("is_read"):
                        notif_filters["is_read"] = 0
                    elif meta.has_field("read"):
                        notif_filters["read"] = 0
                    elif meta.has_field("status"):
                        notif_filters["status"] = "Unread"
                    unread_notifications = frappe.db.count(DOCTYPE_NOTIFICATION, filters=notif_filters)
            except Exception:
                unread_notifications = 0

            return {
                "open_jobs": open_jobs,
                "total_candidates": total_candidates,
                "total_applications": total_applications,
                "todays_interviews": todays_interviews,
                "pending_offers": pending_offers,
                "unread_notifications": unread_notifications,
            }
        except Exception as exc:
            raise ATSServiceError(
                f"Failed to aggregate overview metrics: {str(exc)}"
            ) from exc

    def get_pipeline_summary(self, company: str | None = None, job_opening: str | None = None) -> dict:
        """Return application counts grouped by pipeline stage overall and per job.

        Parameters
        ----------
        company : str or None, optional
            The Company name filter.
        job_opening : str or None, optional
            The Job Opening name filter.

        Returns
        -------
        dict
            ``{
                "total_applications": int,
                "by_stage": dict,
                "by_job": list[dict]
            }``
        """
        try:
            filters = {}
            if company:
                filters["company"] = company
            if job_opening:
                filters["job_opening"] = job_opening

            apps = frappe.get_all(
                DOCTYPE_JOB_APPLICATION,
                fields=["name", "job_opening", "status", "current_stage"],
                filters=filters,
                ignore_permissions=True,
            )

            stage_counts = {stage: 0 for stage in APPLICATION_STAGES}
            job_summary_map: dict[str, dict] = {}

            for app in apps:
                stage = app.get("current_stage") or app.get("status") or "Applied"
                if stage in stage_counts:
                    stage_counts[stage] += 1
                else:
                    stage_counts[stage] = stage_counts.get(stage, 0) + 1

                job_id = app.get("job_opening") or "Unassigned"
                if job_id not in job_summary_map:
                    job_summary_map[job_id] = {
                        "job_opening": job_id,
                        "stages": {s: 0 for s in APPLICATION_STAGES},
                        "total": 0,
                    }
                if stage in job_summary_map[job_id]["stages"]:
                    job_summary_map[job_id]["stages"][stage] += 1
                else:
                    job_summary_map[job_id]["stages"][stage] = 1
                job_summary_map[job_id]["total"] += 1

            return {
                "total_applications": len(apps),
                "by_stage": stage_counts,
                "by_job": list(job_summary_map.values()),
            }
        except Exception as exc:
            raise ATSServiceError(
                f"Failed to generate pipeline summary: {str(exc)}"
            ) from exc

    def get_hiring_funnel(
        self,
        company: str | None = None,
        job_opening: str | None = None,
        from_date: date | str | None = None,
        to_date: date | str | None = None,
    ) -> dict:
        """Return hiring funnel conversion rates across pipeline stages.

        Parameters
        ----------
        company : str or None, optional
            Company filter.
        job_opening : str or None, optional
            Job Opening filter.
        from_date : date or str or None, optional
            Reporting period start date.
        to_date : date or str or None, optional
            Reporting period end date.

        Returns
        -------
        dict
            Funnel counts and conversion percentages.
        """
        try:
            filters = {}
            if company:
                filters["company"] = company
            if job_opening:
                filters["job_opening"] = job_opening
            if from_date and to_date:
                filters["creation"] = ["between", [str(from_date), str(to_date)]]

            apps = frappe.get_all(
                DOCTYPE_JOB_APPLICATION,
                fields=["name", "status", "current_stage"],
                filters=filters,
                ignore_permissions=True,
            )

            funnel_stages = ["Applied", "Screening", "Shortlisted", "Interview", "Offer", "Hired", "Rejected"]
            funnel = {s: 0 for s in funnel_stages}

            for app in apps:
                st = app.get("current_stage") or app.get("status") or "Applied"
                if st in ["Applied"]:
                    funnel["Applied"] += 1
                elif st in ["Screening"]:
                    funnel["Screening"] += 1
                elif st in ["Shortlisted", "Shortlist"]:
                    funnel["Shortlisted"] += 1
                elif st in ["Interview", "Assessment", "Technical", "HR"]:
                    funnel["Interview"] += 1
                elif st in ["Offer", "Offered"]:
                    funnel["Offer"] += 1
                elif st in ["Hired"]:
                    funnel["Hired"] += 1
                elif st in ["Rejected"]:
                    funnel["Rejected"] += 1
                else:
                    funnel["Applied"] += 1

            total = len(apps)
            applied_count = funnel["Applied"] or total or 1
            conversion_rates = {
                stage: round((count / applied_count) * 100, 1)
                for stage, count in funnel.items()
            }

            return {
                "funnel": funnel,
                "total": total,
                "conversion_rates": conversion_rates,
            }
        except Exception as exc:
            raise ATSServiceError(
                f"Failed to calculate hiring funnel: {str(exc)}"
            ) from exc

    # ------------------------------------------------------------------
    # Time-Series Reports
    # ------------------------------------------------------------------

    def get_applications_over_time(
        self,
        company: str | None = None,
        job_opening: str | None = None,
        granularity: str = "monthly",
        from_date: date | str | None = None,
        to_date: date | str | None = None,
    ) -> list:
        """Return application submission counts grouped by time period.

        Parameters
        ----------
        company : str or None, optional
            Company filter.
        job_opening : str or None, optional
            Job Opening filter.
        granularity : str, optional
            ``"daily"``, ``"weekly"``, or ``"monthly"`` (default ``"monthly"``).
        from_date : date or str or None, optional
            Date range start.
        to_date : date or str or None, optional
            Date range end.

        Returns
        -------
        list
            List of ``{ "period": str, "count": int }`` dicts.
        """
        try:
            filters = {}
            if company:
                filters["company"] = company
            if job_opening:
                filters["job_opening"] = job_opening
            if from_date and to_date:
                filters["creation"] = ["between", [str(from_date), str(to_date)]]

            apps = frappe.get_all(
                DOCTYPE_JOB_APPLICATION,
                fields=["name", "creation", "applied_on"],
                filters=filters,
                ignore_permissions=True,
            )

            period_counts: dict[str, int] = {}
            for app in apps:
                dt_val = app.get("applied_on") or app.get("creation")
                if not dt_val:
                    continue
                dt_str = str(dt_val)[:10]
                if granularity.lower() in ["daily", "day"]:
                    period = dt_str
                elif granularity.lower() in ["weekly", "week"]:
                    try:
                        dt_obj = datetime.strptime(dt_str, "%Y-%m-%d")
                        period = f"{dt_obj.year}-W{dt_obj.isocalendar()[1]:02d}"
                    except Exception:
                        period = dt_str[:7]
                else:
                    period = dt_str[:7]

                period_counts[period] = period_counts.get(period, 0) + 1

            sorted_periods = sorted(period_counts.keys())
            return [
                {"period": p, "count": period_counts[p]}
                for p in sorted_periods
            ]
        except Exception as exc:
            raise ATSServiceError(
                f"Failed to fetch applications over time: {str(exc)}"
            ) from exc

    def get_time_to_hire(
        self,
        company: str | None = None,
        job_opening: str | None = None,
        department: str | None = None,
        from_date: date | str | None = None,
        to_date: date | str | None = None,
    ) -> dict:
        """Calculate average time-to-hire statistics.

        Parameters
        ----------
        company : str or None, optional
            Company filter.
        job_opening : str or None, optional
            Job Opening filter.
        department : str or None, optional
            Department filter.
        from_date : date or str or None, optional
            Start date.
        to_date : date or str or None, optional
            End date.

        Returns
        -------
        dict
            ``{ "avg_days": float, "min_days": int, "max_days": int, "total_hires": int }``
        """
        try:
            offer_filters = {}
            if company and frappe.get_meta(DOCTYPE_OFFER).has_field("company"):
                offer_filters["company"] = company

            # Schema check for Offer: `job_application`, `joining_date`, `offer_date`, `offer_status`
            offers = frappe.get_all(
                DOCTYPE_OFFER,
                fields=["name", "job_application", "creation", "joining_date", "offer_date", "offer_status"],
                filters=offer_filters,
                ignore_permissions=True,
            )

            if not offers:
                return {
                    "avg_days": 0.0,
                    "min_days": 0,
                    "max_days": 0,
                    "total_hires": 0,
                }

            durations = []
            for offer in offers:
                app_id = offer.get("job_application")
                if not app_id:
                    continue
                app_list = frappe.get_all(
                    DOCTYPE_JOB_APPLICATION,
                    filters={"name": app_id},
                    fields=["creation", "applied_on"],
                    limit_page_length=1,
                    ignore_permissions=True,
                )
                if not app_list:
                    continue
                app = app_list[0]

                app_dt = app.get("applied_on") or app.get("creation")
                offer_dt = offer.get("joining_date") or offer.get("offer_date") or offer.get("creation")

                if app_dt and offer_dt:
                    try:
                        d1 = datetime.strptime(str(app_dt)[:10], "%Y-%m-%d")
                        d2 = datetime.strptime(str(offer_dt)[:10], "%Y-%m-%d")
                        diff = (d2 - d1).days
                        if diff >= 0:
                            durations.append(diff)
                    except Exception:
                        pass

            if not durations:
                return {
                    "avg_days": 0.0,
                    "min_days": 0,
                    "max_days": 0,
                    "total_hires": 0,
                }

            avg_days = round(sum(durations) / len(durations), 1)
            min_days = min(durations)
            max_days = max(durations)

            return {
                "avg_days": avg_days,
                "min_days": min_days,
                "max_days": max_days,
                "total_hires": len(durations),
            }
        except Exception as exc:
            raise ATSServiceError(
                f"Failed to calculate time to hire: {str(exc)}"
            ) from exc

    # ------------------------------------------------------------------
    # Activity Feed
    # ------------------------------------------------------------------

    def get_recent_activity(
        self,
        company: str | None = None,
        entity: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """Return the most recent Activity Log entries across entity types.

        Parameters
        ----------
        company : str or None, optional
            Company filter.
        entity : str or None, optional
            Entity filter (e.g. ``"Candidate"``, ``"Job Application"``, ``"Interview"``, ``"Offer"``).
        page : int, optional
            Page number (1-indexed).
        page_size : int, optional
            Records per page.

        Returns
        -------
        dict
            ``{ "data": list[dict], "total": int, "page": int, "page_size": int }``
        """
        try:
            page = max(1, int(page))
            page_size = max(1, min(int(page_size), 100))

            activities = []

            # 1. Candidates
            if not entity or entity.lower() == "candidate":
                cands = frappe.get_all(
                    DOCTYPE_CANDIDATE,
                    fields=["name", "first_name", "last_name", "modified", "creation"],
                    order_by="modified desc",
                    limit_page_length=10,
                    ignore_permissions=True,
                )
                for c in cands:
                    fn = c.get("first_name") or ""
                    ln = c.get("last_name") or ""
                    name_str = f"{fn} {ln}".strip() or c.get("name")
                    activities.append({
                        "doctype": DOCTYPE_CANDIDATE,
                        "name": c.get("name"),
                        "title": f"Candidate: {name_str}",
                        "action": "Updated candidate record",
                        "modified": str(c.get("modified")),
                    })

            # 2. Applications
            if not entity or entity.lower() in ["job application", "application"]:
                apps = frappe.get_all(
                    DOCTYPE_JOB_APPLICATION,
                    fields=["name", "candidate", "job_opening", "status", "modified", "creation"],
                    order_by="modified desc",
                    limit_page_length=10,
                    ignore_permissions=True,
                )
                for a in apps:
                    activities.append({
                        "doctype": DOCTYPE_JOB_APPLICATION,
                        "name": a.get("name"),
                        "title": f"Application: {a.get('name')}",
                        "action": f"Job: {a.get('job_opening') or 'N/A'} (Status: {a.get('status') or 'Applied'})",
                        "modified": str(a.get("modified")),
                    })

            # 3. Interviews (Schema: `job_application`, NOT `application`)
            if not entity or entity.lower() == "interview":
                interviews = frappe.get_all(
                    DOCTYPE_INTERVIEW,
                    fields=["name", "job_application", "interview_type", "status", "modified", "creation"],
                    order_by="modified desc",
                    limit_page_length=10,
                    ignore_permissions=True,
                )
                for i in interviews:
                    activities.append({
                        "doctype": DOCTYPE_INTERVIEW,
                        "name": i.get("name"),
                        "title": f"Interview: {i.get('interview_type') or 'Screen'}",
                        "action": f"Status: {i.get('status') or 'Scheduled'}",
                        "modified": str(i.get("modified")),
                    })

            # 4. Offers (Schema: `job_application` & `offer_status`, NOT `application` & `status`)
            if not entity or entity.lower() == "offer":
                offers = frappe.get_all(
                    DOCTYPE_OFFER,
                    fields=["name", "job_application", "offer_status", "modified", "creation"],
                    order_by="modified desc",
                    limit_page_length=10,
                    ignore_permissions=True,
                )
                for o in offers:
                    activities.append({
                        "doctype": DOCTYPE_OFFER,
                        "name": o.get("name"),
                        "title": f"Offer: {o.get('name')}",
                        "action": f"Status: {o.get('offer_status') or 'Draft'}",
                        "modified": str(o.get("modified")),
                    })

            # Sort merged activities by modified desc
            activities.sort(key=lambda x: x.get("modified", ""), reverse=True)

            total = len(activities)
            start = (page - 1) * page_size
            end = start + page_size
            paginated_data = activities[start:end]

            return {
                "data": paginated_data,
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        except Exception as exc:
            raise ATSServiceError(
                f"Failed to fetch recent activity: {str(exc)}"
            ) from exc
