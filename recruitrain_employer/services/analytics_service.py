# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.services.analytics_service
==================================================

Authoritative Analytics Business Logic Engine for RecruitTrain ATS.

Backend First + Thin Client + Single Source of Truth

Owns all business logic for:
- Overview KPI metrics aggregation
- Recruitment Funnel conversion analysis
- Time-series application and hiring trends
- Job Opening performance metrics
- Job Application pipeline and source metrics
- Interview scheduling and outcome metrics
- Offer acceptance and compensation metrics
- Time-to-hire and time-to-fill calculations
- Recent Activity feeds

All queries strictly enforce:
- Authenticated employer context
- Server-side Company scoping via ``get_current_company()``
- Input parameter sanitisation and date range validation
- Parameterised SQL / Frappe ORM execution without raw input string concatenation
- Zero side-effects (100% read-only operations)
"""

from __future__ import annotations

from datetime import date, datetime
import frappe

from recruitrain_employer.utils.constants import (
    APPLICATION_STAGES,
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    DOCTYPE_CANDIDATE,
    DOCTYPE_INTERVIEW,
    DOCTYPE_JOB_APPLICATION,
    DOCTYPE_JOB_OPENING,
    DOCTYPE_NOTIFICATION,
    DOCTYPE_OFFER,
    JOB_STATUS_OPEN,
    MAX_PAGE_SIZE,
    OFFER_STATUS_DRAFT,
    OFFER_STATUS_SENT,
)
from recruitrain_employer.utils.exceptions import (
    ATSPermissionError,
    ATSServiceError,
    ATSValidationError,
)
from recruitrain_employer.utils.permissions import (
    get_current_company,
    get_current_employer_user,
)


class AnalyticsService:
    """Encapsulates authoritative business logic for Analytics and Reporting."""

    # ------------------------------------------------------------------
    # Company & Permission Scoping
    # ------------------------------------------------------------------

    def _resolve_company(self, company_param: str | None = None) -> str:
        """Resolve and validate active company context for the authenticated employer user.

        Raises ATSPermissionError if a non-Admin user requests a different company.
        """
        current_company = get_current_company()
        user = getattr(frappe.session, "user", "")

        if user == "Administrator":
            if company_param and company_param.strip():
                if not frappe.db.exists("Company", company_param):
                    raise ATSValidationError(
                        f"Company '{company_param}' does not exist.",
                        field="company",
                    )
                return company_param
            return current_company

        if company_param and company_param.strip() and company_param != current_company:
            raise ATSPermissionError(
                f"Cross-company access prohibited. Requested '{company_param}', but active user belongs to '{current_company}'.",
                details={"requested_company": company_param, "user_company": current_company},
            )

        return current_company

    # ------------------------------------------------------------------
    # Date Range Handling
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_date(date_val: date | str | None, field_name: str) -> str | None:
        """Parse and format a date value into YYYY-MM-DD ISO format."""
        if not date_val:
            return None

        if isinstance(date_val, date):
            return date_val.strftime("%Y-%m-%d")

        d_str = str(date_val).strip()
        if not d_str:
            return None

        try:
            parsed = datetime.strptime(d_str[:10], "%Y-%m-%d")
            return parsed.strftime("%Y-%m-%d")
        except ValueError as exc:
            raise ATSValidationError(
                f"Invalid date format for '{field_name}'. Expected YYYY-MM-DD.",
                field=field_name,
                details={"value": d_str},
            ) from exc

    def _validate_date_range(
        self,
        from_date: date | str | None = None,
        to_date: date | str | None = None,
    ) -> tuple[str | None, str | None]:
        """Validate and return sanitized (from_date, to_date) strings."""
        start_str = self._parse_date(from_date, "from_date")
        end_str = self._parse_date(to_date, "to_date")

        if start_str and end_str:
            if start_str > end_str:
                raise ATSValidationError(
                    "from_date cannot be after to_date.",
                    field="from_date",
                    details={"from_date": start_str, "to_date": end_str},
                )

        return start_str, end_str

    # ------------------------------------------------------------------
    # 1. Overview KPIs
    # ------------------------------------------------------------------

    def get_overview(
        self,
        company: str | None = None,
        from_date: date | str | None = None,
        to_date: date | str | None = None,
    ) -> dict:
        """Return aggregate overview KPI metrics for the specified company.

        Returns
        -------
        dict
            {
                "open_jobs": int,
                "total_jobs": int,
                "total_candidates": int,
                "total_applications": int,
                "active_applications": int,
                "todays_interviews": int,
                "total_interviews": int,
                "pending_offers": int,
                "accepted_offers": int,
                "total_hires": int,
                "rejected_applications": int
            }
        """
        try:
            target_company = self._resolve_company(company)
            start_date, end_date = self._validate_date_range(from_date, to_date)

            # 1. Jobs
            job_filters = {"company": target_company}
            total_jobs = frappe.db.count(DOCTYPE_JOB_OPENING, filters=job_filters)
            job_filters["status"] = JOB_STATUS_OPEN
            open_jobs = frappe.db.count(DOCTYPE_JOB_OPENING, filters=job_filters)

            # 2. Candidates
            cand_filters = {"company": target_company}
            total_candidates = frappe.db.count(DOCTYPE_CANDIDATE, filters=cand_filters)

            # 3. Job Applications
            app_filters = {"company": target_company}
            if start_date and end_date:
                app_filters["creation"] = ["between", [f"{start_date} 00:00:00", f"{end_date} 23:59:59"]]

            total_applications = frappe.db.count(DOCTYPE_JOB_APPLICATION, filters=app_filters)

            active_app_filters = dict(app_filters)
            active_app_filters["status"] = "Open"
            active_applications = frappe.db.count(DOCTYPE_JOB_APPLICATION, filters=active_app_filters)

            rejected_app_filters = dict(app_filters)
            rejected_app_filters["status"] = "Rejected"
            rejected_applications = frappe.db.count(DOCTYPE_JOB_APPLICATION, filters=rejected_app_filters)

            # 4. Interviews
            today_str = str(frappe.utils.today())
            interview_filters = {"company": target_company}
            total_interviews = frappe.db.count(DOCTYPE_INTERVIEW, filters=interview_filters)

            todays_interview_filters = dict(interview_filters)
            todays_interview_filters["scheduled_on"] = ["between", [f"{today_str} 00:00:00", f"{today_str} 23:59:59"]]
            todays_interviews = 0
            try:
                todays_interviews = frappe.db.count(DOCTYPE_INTERVIEW, filters=todays_interview_filters)
            except Exception:
                todays_interviews = 0

            # 5. Offers
            pending_offer_filters = {
                "company": target_company,
                "offer_status": ["in", [OFFER_STATUS_DRAFT, OFFER_STATUS_SENT, "Pending Approval", "Approved", "Draft", "Sent"]],
            }
            pending_offers = frappe.db.count(DOCTYPE_OFFER, filters=pending_offer_filters)

            accepted_offer_filters = {
                "company": target_company,
                "offer_status": "Accepted",
            }
            accepted_offers = frappe.db.count(DOCTYPE_OFFER, filters=accepted_offer_filters)

            return {
                "open_jobs": open_jobs,
                "total_jobs": total_jobs,
                "total_candidates": total_candidates,
                "total_applications": total_applications,
                "active_applications": active_applications,
                "todays_interviews": todays_interviews,
                "total_interviews": total_interviews,
                "pending_offers": pending_offers,
                "accepted_offers": accepted_offers,
                "total_hires": accepted_offers,
                "rejected_applications": rejected_applications,
            }
        except (ATSValidationError, ATSPermissionError):
            raise
        except Exception as exc:
            raise ATSServiceError(f"Failed to calculate overview metrics: {str(exc)}") from exc

    def get_analytics(
        self,
        company: str | None = None,
        job_opening: str | None = None,
        from_date: date | str | None = None,
        to_date: date | str | None = None,
    ) -> dict:
        """Return unified aggregate analytics payload covering all dashboard categories."""
        overview = self.get_overview(company=company, from_date=from_date, to_date=to_date)
        funnel = self.get_funnel(company=company, job_opening=job_opening, from_date=from_date, to_date=to_date)
        trends = self.get_trends(company=company, job_opening=job_opening, from_date=from_date, to_date=to_date)
        jobs = self.get_job_metrics(company=company, from_date=from_date, to_date=to_date)
        applications = self.get_application_metrics(company=company, job_opening=job_opening, from_date=from_date, to_date=to_date)
        interviews = self.get_interview_metrics(company=company, job_opening=job_opening, from_date=from_date, to_date=to_date)
        offers = self.get_offer_metrics(company=company, job_opening=job_opening, from_date=from_date, to_date=to_date)
        time_to_hire = self.get_time_to_hire(company=company, job_opening=job_opening, from_date=from_date, to_date=to_date)

        return {
            "overview": overview,
            "funnel": funnel,
            "trends": trends,
            "jobs": jobs,
            "applications": applications,
            "interviews": interviews,
            "offers": offers,
            "time_to_hire": time_to_hire,
        }

    # ------------------------------------------------------------------
    # 2. Recruitment Funnel
    # ------------------------------------------------------------------

    def get_funnel(
        self,
        company: str | None = None,
        job_opening: str | None = None,
        from_date: date | str | None = None,
        to_date: date | str | None = None,
    ) -> dict:
        """Return recruitment funnel breakdown and conversion rates."""
        try:
            target_company = self._resolve_company(company)
            start_date, end_date = self._validate_date_range(from_date, to_date)

            filters: dict = {"company": target_company}

            if job_opening and job_opening.strip():
                # Validate job_opening belongs to target_company
                job_exists = frappe.db.exists(DOCTYPE_JOB_OPENING, {"name": job_opening.strip(), "company": target_company})
                if not job_exists:
                    raise ATSValidationError(
                        f"Job Opening '{job_opening}' does not exist or does not belong to company '{target_company}'.",
                        field="job_opening",
                    )
                filters["job_opening"] = job_opening.strip()

            if start_date and end_date:
                filters["creation"] = ["between", [f"{start_date} 00:00:00", f"{end_date} 23:59:59"]]

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
            base_count = funnel["Applied"] or total or 1
            conversion_rates = {
                stage: round((count / base_count) * 100, 1)
                for stage, count in funnel.items()
            }

            return {
                "funnel": funnel,
                "total": total,
                "conversion_rates": conversion_rates,
            }
        except (ATSValidationError, ATSPermissionError):
            raise
        except Exception as exc:
            raise ATSServiceError(f"Failed to calculate recruitment funnel: {str(exc)}") from exc

    # ------------------------------------------------------------------
    # 3. Trends (Applications Over Time)
    # ------------------------------------------------------------------

    def get_trends(
        self,
        company: str | None = None,
        job_opening: str | None = None,
        granularity: str = "monthly",
        from_date: date | str | None = None,
        to_date: date | str | None = None,
    ) -> list:
        """Return application volume trends grouped by time granularity."""
        try:
            target_company = self._resolve_company(company)
            start_date, end_date = self._validate_date_range(from_date, to_date)

            valid_granularities = {"daily": "daily", "day": "daily", "weekly": "weekly", "week": "weekly", "monthly": "monthly", "month": "monthly"}
            gran = valid_granularities.get(str(granularity).lower())
            if not gran:
                raise ATSValidationError(
                    "Invalid granularity. Expected 'daily', 'weekly', or 'monthly'.",
                    field="granularity",
                    details={"provided": granularity},
                )

            filters: dict = {"company": target_company}
            if job_opening and job_opening.strip():
                if not frappe.db.exists(DOCTYPE_JOB_OPENING, {"name": job_opening.strip(), "company": target_company}):
                    raise ATSValidationError(
                        f"Job Opening '{job_opening}' does not exist or belong to company '{target_company}'.",
                        field="job_opening",
                    )
                filters["job_opening"] = job_opening.strip()

            if start_date and end_date:
                filters["creation"] = ["between", [f"{start_date} 00:00:00", f"{end_date} 23:59:59"]]

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
                if gran == "daily":
                    period = dt_str
                elif gran == "weekly":
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
        except (ATSValidationError, ATSPermissionError):
            raise
        except Exception as exc:
            raise ATSServiceError(f"Failed to fetch application trends: {str(exc)}") from exc

    # ------------------------------------------------------------------
    # 4. Job Opening Metrics
    # ------------------------------------------------------------------

    def get_job_metrics(
        self,
        company: str | None = None,
        from_date: date | str | None = None,
        to_date: date | str | None = None,
    ) -> dict:
        """Return Job Opening distribution and performance metrics."""
        try:
            target_company = self._resolve_company(company)
            start_date, end_date = self._validate_date_range(from_date, to_date)

            filters: dict = {"company": target_company}
            if start_date and end_date:
                filters["creation"] = ["between", [f"{start_date} 00:00:00", f"{end_date} 23:59:59"]]

            jobs = frappe.get_all(
                DOCTYPE_JOB_OPENING,
                fields=["name", "job_title", "job_code", "status", "number_of_openings", "department", "employment_type"],
                filters=filters,
                ignore_permissions=True,
            )

            status_counts: dict[str, int] = {
                "Draft": 0,
                "Open": 0,
                "Paused": 0,
                "Closed": 0,
                "Filled": 0,
                "Cancelled": 0,
            }
            total_openings = 0

            for j in jobs:
                st = j.get("status") or "Draft"
                status_counts[st] = status_counts.get(st, 0) + 1
                total_openings += int(j.get("number_of_openings") or 0)

            # Applications per job
            apps = frappe.get_all(
                DOCTYPE_JOB_APPLICATION,
                fields=["job_opening"],
                filters={"company": target_company},
                ignore_permissions=True,
            )
            app_count_by_job: dict[str, int] = {}
            for a in apps:
                job_id = a.get("job_opening")
                if job_id:
                    app_count_by_job[job_id] = app_count_by_job.get(job_id, 0) + 1

            applications_per_job = [
                {
                    "job_opening": j["name"],
                    "job_title": j.get("job_title"),
                    "job_code": j.get("job_code"),
                    "status": j.get("status"),
                    "openings": j.get("number_of_openings") or 0,
                    "applications_count": app_count_by_job.get(j["name"], 0),
                }
                for j in jobs
            ]

            applications_per_job.sort(key=lambda x: x["applications_count"], reverse=True)

            return {
                "by_status": status_counts,
                "total_jobs": len(jobs),
                "open_jobs": status_counts.get("Open", 0),
                "filled_jobs": status_counts.get("Filled", 0),
                "closed_jobs": status_counts.get("Closed", 0),
                "total_openings": total_openings,
                "applications_per_job": applications_per_job,
            }
        except (ATSValidationError, ATSPermissionError):
            raise
        except Exception as exc:
            raise ATSServiceError(f"Failed to calculate job metrics: {str(exc)}") from exc

    # ------------------------------------------------------------------
    # 5. Application Metrics
    # ------------------------------------------------------------------

    def get_application_metrics(
        self,
        company: str | None = None,
        job_opening: str | None = None,
        from_date: date | str | None = None,
        to_date: date | str | None = None,
    ) -> dict:
        """Return Job Application metrics grouped by status, stage, source, priority."""
        try:
            target_company = self._resolve_company(company)
            start_date, end_date = self._validate_date_range(from_date, to_date)

            filters: dict = {"company": target_company}
            if job_opening and job_opening.strip():
                if not frappe.db.exists(DOCTYPE_JOB_OPENING, {"name": job_opening.strip(), "company": target_company}):
                    raise ATSValidationError(
                        f"Job Opening '{job_opening}' does not exist or belong to company '{target_company}'.",
                        field="job_opening",
                    )
                filters["job_opening"] = job_opening.strip()

            if start_date and end_date:
                filters["creation"] = ["between", [f"{start_date} 00:00:00", f"{end_date} 23:59:59"]]

            apps = frappe.get_all(
                DOCTYPE_JOB_APPLICATION,
                fields=["name", "status", "current_stage", "source", "priority"],
                filters=filters,
                ignore_permissions=True,
            )

            by_status: dict[str, int] = {}
            by_stage: dict[str, int] = {}
            by_source: dict[str, int] = {}
            by_priority: dict[str, int] = {}

            for a in apps:
                st = a.get("status") or "Open"
                by_status[st] = by_status.get(st, 0) + 1

                stage = a.get("current_stage") or "Applied"
                by_stage[stage] = by_stage.get(stage, 0) + 1

                src = a.get("source") or "Manual"
                by_source[src] = by_source.get(src, 0) + 1

                prio = a.get("priority") or "Medium"
                by_priority[prio] = by_priority.get(prio, 0) + 1

            return {
                "by_status": by_status,
                "by_stage": by_stage,
                "by_source": by_source,
                "by_priority": by_priority,
                "total_applications": len(apps),
            }
        except (ATSValidationError, ATSPermissionError):
            raise
        except Exception as exc:
            raise ATSServiceError(f"Failed to calculate application metrics: {str(exc)}") from exc

    # ------------------------------------------------------------------
    # 6. Interview Metrics
    # ------------------------------------------------------------------

    def get_interview_metrics(
        self,
        company: str | None = None,
        job_opening: str | None = None,
        from_date: date | str | None = None,
        to_date: date | str | None = None,
    ) -> dict:
        """Return Interview metrics grouped by status, type, and result."""
        try:
            target_company = self._resolve_company(company)
            start_date, end_date = self._validate_date_range(from_date, to_date)

            filters: dict = {"company": target_company}
            if job_opening and job_opening.strip():
                if not frappe.db.exists(DOCTYPE_JOB_OPENING, {"name": job_opening.strip(), "company": target_company}):
                    raise ATSValidationError(
                        f"Job Opening '{job_opening}' does not exist or belong to company '{target_company}'.",
                        field="job_opening",
                    )
                filters["job_opening"] = job_opening.strip()

            if start_date and end_date:
                filters["scheduled_on"] = ["between", [f"{start_date} 00:00:00", f"{end_date} 23:59:59"]]

            interviews = frappe.get_all(
                DOCTYPE_INTERVIEW,
                fields=["name", "status", "interview_type", "result"],
                filters=filters,
                ignore_permissions=True,
            )

            by_status: dict[str, int] = {}
            by_type: dict[str, int] = {}
            by_result: dict[str, int] = {}

            for i in interviews:
                st = i.get("status") or "Scheduled"
                by_status[st] = by_status.get(st, 0) + 1

                itype = i.get("interview_type") or "General"
                by_type[itype] = by_type.get(itype, 0) + 1

                res = i.get("result") or "Pending"
                by_result[res] = by_result.get(res, 0) + 1

            return {
                "by_status": by_status,
                "by_type": by_type,
                "by_result": by_result,
                "total_interviews": len(interviews),
            }
        except (ATSValidationError, ATSPermissionError):
            raise
        except Exception as exc:
            raise ATSServiceError(f"Failed to calculate interview metrics: {str(exc)}") from exc

    # ------------------------------------------------------------------
    # 7. Offer Metrics
    # ------------------------------------------------------------------

    def get_offer_metrics(
        self,
        company: str | None = None,
        job_opening: str | None = None,
        from_date: date | str | None = None,
        to_date: date | str | None = None,
    ) -> dict:
        """Return Offer metrics including status distribution and acceptance rates."""
        try:
            target_company = self._resolve_company(company)
            start_date, end_date = self._validate_date_range(from_date, to_date)

            filters: dict = {"company": target_company}
            if job_opening and job_opening.strip():
                if not frappe.db.exists(DOCTYPE_JOB_OPENING, {"name": job_opening.strip(), "company": target_company}):
                    raise ATSValidationError(
                        f"Job Opening '{job_opening}' does not exist or belong to company '{target_company}'.",
                        field="job_opening",
                    )
                filters["job_opening"] = job_opening.strip()

            if start_date and end_date:
                filters["offer_date"] = ["between", [start_date, end_date]]

            offers = frappe.get_all(
                DOCTYPE_OFFER,
                fields=["name", "offer_status", "offered_salary"],
                filters=filters,
                ignore_permissions=True,
            )

            by_status: dict[str, int] = {
                "Draft": 0,
                "Sent": 0,
                "Accepted": 0,
                "Rejected": 0,
                "Expired": 0,
                "Withdrawn": 0,
            }
            total_salary = 0.0

            for o in offers:
                st = o.get("offer_status") or "Draft"
                by_status[st] = by_status.get(st, 0) + 1
                total_salary += float(o.get("offered_salary") or 0.0)

            total_offers = len(offers)
            accepted_offers = by_status.get("Accepted", 0)
            acceptance_rate = round((accepted_offers / total_offers) * 100, 1) if total_offers > 0 else 0.0

            return {
                "by_status": by_status,
                "total_offers": total_offers,
                "accepted_offers": accepted_offers,
                "acceptance_rate": acceptance_rate,
                "total_offered_salary": round(total_salary, 2),
            }
        except (ATSValidationError, ATSPermissionError):
            raise
        except Exception as exc:
            raise ATSServiceError(f"Failed to calculate offer metrics: {str(exc)}") from exc

    # ------------------------------------------------------------------
    # 8. Time to Hire
    # ------------------------------------------------------------------

    def get_time_to_hire(
        self,
        company: str | None = None,
        job_opening: str | None = None,
        department: str | None = None,
        from_date: date | str | None = None,
        to_date: date | str | None = None,
    ) -> dict:
        """Calculate average time-to-hire in days between application date and offer/joining date."""
        try:
            target_company = self._resolve_company(company)
            start_date, end_date = self._validate_date_range(from_date, to_date)

            offer_filters: dict = {"company": target_company}
            if job_opening and job_opening.strip():
                if not frappe.db.exists(DOCTYPE_JOB_OPENING, {"name": job_opening.strip(), "company": target_company}):
                    raise ATSValidationError(
                        f"Job Opening '{job_opening}' does not exist or belong to company '{target_company}'.",
                        field="job_opening",
                    )
                offer_filters["job_opening"] = job_opening.strip()

            if start_date and end_date:
                offer_filters["offer_date"] = ["between", [start_date, end_date]]

            offers = frappe.get_all(
                DOCTYPE_OFFER,
                fields=["name", "job_application", "creation", "joining_date", "offer_date", "offer_status"],
                filters=offer_filters,
                ignore_permissions=True,
            )

            durations: list[int] = []
            for offer in offers:
                app_id = offer.get("job_application")
                if not app_id:
                    continue
                app_list = frappe.get_all(
                    DOCTYPE_JOB_APPLICATION,
                    filters={"name": app_id, "company": target_company},
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

            return {
                "avg_days": round(sum(durations) / len(durations), 1),
                "min_days": min(durations),
                "max_days": max(durations),
                "total_hires": len(durations),
            }
        except (ATSValidationError, ATSPermissionError):
            raise
        except Exception as exc:
            raise ATSServiceError(f"Failed to calculate time to hire: {str(exc)}") from exc

    # ------------------------------------------------------------------
    # 9. Recent Activity Stream
    # ------------------------------------------------------------------

    def get_recent_activity(
        self,
        company: str | None = None,
        entity: str | None = None,
        page: int = DEFAULT_PAGE,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict:
        """Return paginated recent activity feed scoped strictly to company."""
        try:
            target_company = self._resolve_company(company)

            page = max(1, int(page or DEFAULT_PAGE))
            page_size = max(1, min(int(page_size or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))

            if entity and entity.strip():
                valid_entities = {"candidate", "job application", "application", "interview", "offer"}
                if entity.strip().lower() not in valid_entities:
                    raise ATSValidationError(
                        f"Invalid entity '{entity}'. Expected Candidate, Job Application, Interview, or Offer.",
                        field="entity",
                    )

            activities: list[dict] = []
            ent_lower = (entity or "").strip().lower()

            # 1. Candidate Activity
            if not ent_lower or ent_lower == "candidate":
                cands = frappe.get_all(
                    DOCTYPE_CANDIDATE,
                    filters={"company": target_company},
                    fields=["name", "first_name", "last_name", "modified", "creation"],
                    order_by="modified desc",
                    limit_page_length=20,
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
                        "action": "Updated candidate profile",
                        "modified": str(c.get("modified")),
                    })

            # 2. Application Activity
            if not ent_lower or ent_lower in ["job application", "application"]:
                apps = frappe.get_all(
                    DOCTYPE_JOB_APPLICATION,
                    filters={"company": target_company},
                    fields=["name", "candidate", "job_opening", "status", "modified", "creation"],
                    order_by="modified desc",
                    limit_page_length=20,
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

            # 3. Interview Activity
            if not ent_lower or ent_lower == "interview":
                interviews = frappe.get_all(
                    DOCTYPE_INTERVIEW,
                    filters={"company": target_company},
                    fields=["name", "job_application", "interview_type", "status", "modified", "creation"],
                    order_by="modified desc",
                    limit_page_length=20,
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

            # 4. Offer Activity
            if not ent_lower or ent_lower == "offer":
                offers = frappe.get_all(
                    DOCTYPE_OFFER,
                    filters={"company": target_company},
                    fields=["name", "job_application", "offer_status", "modified", "creation"],
                    order_by="modified desc",
                    limit_page_length=20,
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
        except (ATSValidationError, ATSPermissionError):
            raise
        except Exception as exc:
            raise ATSServiceError(f"Failed to fetch recent activity: {str(exc)}") from exc
