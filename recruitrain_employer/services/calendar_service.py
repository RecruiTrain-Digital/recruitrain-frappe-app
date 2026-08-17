# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.services.calendar_service
================================================

Service layer for aggregating real recruitment calendar events from authoritative DocTypes.

DocTypes audited for date fields:
- Interview: scheduled_on (Datetime), duration (Int)
- Offer: joining_date (Date), offer_date (Date), expiry_date (Date)
- Job Opening: closing_date (Date), target_joining_date (Date)
- Job Application: applied_on (Date)
"""

from __future__ import annotations

import datetime
from typing import Any

import frappe
from frappe.utils import get_datetime, getdate

from recruitrain_employer.utils.exceptions import ATSCompanyNotFoundError, ATSPermissionError
from recruitrain_employer.utils.permissions import get_current_company


class CalendarService:
    """Service class for retrieving recruitment calendar events."""

    def get_calendar_events(
        self,
        company: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        event_type: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Fetch real calendar events from MariaDB for the authenticated company.

        :param company: Resolved company name (enforced via session).
        :param from_date: Lower bound date filter (YYYY-MM-DD).
        :param to_date: Upper bound date filter (YYYY-MM-DD).
        :param event_type: Event type filter (e.g. 'interview', 'offer', 'job_closing').
        :param status: Event status filter.
        :return: List of unified calendar event dictionaries.
        """
        # Always resolve authoritative company from current session
        resolved_company = company or get_current_company()
        if not resolved_company:
            raise ATSCompanyNotFoundError("Company name is required to retrieve calendar events.")

        # Pre-fetch candidates and job openings for mapping
        candidates_map = self._get_candidates_map(resolved_company)
        jobs_map = self._get_jobs_map(resolved_company)

        events: list[dict[str, Any]] = []

        # 1. Fetch Interview Events
        events.extend(self._get_interview_events(resolved_company, candidates_map, jobs_map))

        # 2. Fetch Offer Events
        events.extend(self._get_offer_events(resolved_company, candidates_map, jobs_map))

        # 3. Fetch Job Opening Events
        events.extend(self._get_job_opening_events(resolved_company, jobs_map))

        # 4. Fetch Job Application Events
        events.extend(self._get_job_application_events(resolved_company, candidates_map, jobs_map))

        # 5. Apply Filters
        filtered_events = self._filter_events(
            events=events,
            from_date=from_date,
            to_date=to_date,
            event_type=event_type,
            status=status,
        )

        # Sort events chronologically by start date
        filtered_events.sort(key=lambda x: str(x.get("start", "")))

        return filtered_events

    def _get_candidates_map(self, company: str) -> dict[str, str]:
        """Fetch candidate name lookup map for company."""
        candidates = frappe.get_all(
            "Candidate",
            filters={"company": company},
            fields=["name", "candidate_name", "first_name", "last_name"],
        )
        res = {}
        for c in candidates:
            name_parts = [c.get("first_name"), c.get("last_name")]
            full = " ".join([p for p in name_parts if p]).strip()
            res[c["name"]] = full or c.get("candidate_name") or c["name"]
        return res

    def _get_jobs_map(self, company: str) -> dict[str, str]:
        """Fetch job title lookup map for company."""
        jobs = frappe.get_all(
            "Job Opening",
            filters={"company": company},
            fields=["name", "job_title", "job_code"],
        )
        return {j["name"]: j.get("job_title") or j.get("job_code") or j["name"] for j in jobs}

    def _get_interview_events(
        self, company: str, candidates_map: dict[str, str], jobs_map: dict[str, str]
    ) -> list[dict[str, Any]]:
        """Fetch interview events from Interview DocType."""
        interviews = frappe.get_all(
            "Interview",
            filters={"company": company},
            fields=[
                "name",
                "interview_name",
                "candidate",
                "job_opening",
                "job_application",
                "interview_type",
                "scheduled_on",
                "duration",
                "status",
                "interviewer",
                "location",
                "meeting_link",
            ],
        )

        events = []
        for i in interviews:
            scheduled_on = i.get("scheduled_on")
            if not scheduled_on:
                continue

            cand_id = i.get("candidate")
            cand_name = candidates_map.get(cand_id) if cand_id else None

            job_id = i.get("job_opening")
            job_title = jobs_map.get(job_id) if job_id else None

            # Calculate end date if duration exists
            end_val = None
            duration_mins = i.get("duration")
            if duration_mins and isinstance(duration_mins, (int, float)) and duration_mins > 0:
                try:
                    dt_start = get_datetime(scheduled_on)
                    dt_end = dt_start + datetime.timedelta(minutes=int(duration_mins))
                    end_val = dt_end.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    end_val = None

            title_str = f"Interview: {cand_name or cand_id or 'Candidate'}"
            if job_title:
                title_str += f" - {job_title}"
            if i.get("interview_type"):
                title_str += f" ({i.get('interview_type')})"

            events.append(
                {
                    "id": i["name"],
                    "event_type": "interview",
                    "title": title_str,
                    "start": str(scheduled_on),
                    "end": end_val,
                    "status": i.get("status", "Scheduled"),
                    "candidate": {"id": cand_id, "name": cand_name} if cand_id else None,
                    "job": {"id": job_id, "title": job_title} if job_id else None,
                    "source_doctype": "Interview",
                    "source_name": i["name"],
                    "details": {
                        "interview_type": i.get("interview_type"),
                        "duration": duration_mins,
                        "interviewer": i.get("interviewer"),
                        "location": i.get("location"),
                        "meeting_link": i.get("meeting_link"),
                    },
                }
            )

        return events

    def _get_offer_events(
        self, company: str, candidates_map: dict[str, str], jobs_map: dict[str, str]
    ) -> list[dict[str, Any]]:
        """Fetch offer date events from Offer DocType."""
        offers = frappe.get_all(
            "Offer",
            filters={"company": company},
            fields=[
                "name",
                "offer_name",
                "candidate",
                "job_opening",
                "job_application",
                "joining_date",
                "offer_date",
                "expiry_date",
                "offer_status",
            ],
        )

        events = []
        for o in offers:
            cand_id = o.get("candidate")
            cand_name = candidates_map.get(cand_id) if cand_id else None

            job_id = o.get("job_opening")
            job_title = jobs_map.get(job_id) if job_id else None

            st = o.get("offer_status", "Sent")

            # 1. Joining Date Event
            if o.get("joining_date"):
                events.append(
                    {
                        "id": f"{o['name']}_joining",
                        "event_type": "offer_joining",
                        "title": f"Joining Date: {cand_name or cand_id or 'Candidate'}{' - ' + job_title if job_title else ''}",
                        "start": str(o["joining_date"]),
                        "end": None,
                        "status": st,
                        "candidate": {"id": cand_id, "name": cand_name} if cand_id else None,
                        "job": {"id": job_id, "title": job_title} if job_id else None,
                        "source_doctype": "Offer",
                        "source_name": o["name"],
                    }
                )

            # 2. Offer Date Event
            if o.get("offer_date"):
                events.append(
                    {
                        "id": f"{o['name']}_date",
                        "event_type": "offer_date",
                        "title": f"Offer Issued: {cand_name or cand_id or 'Candidate'}{' - ' + job_title if job_title else ''}",
                        "start": str(o["offer_date"]),
                        "end": None,
                        "status": st,
                        "candidate": {"id": cand_id, "name": cand_name} if cand_id else None,
                        "job": {"id": job_id, "title": job_title} if job_id else None,
                        "source_doctype": "Offer",
                        "source_name": o["name"],
                    }
                )

            # 3. Expiry Date Event
            if o.get("expiry_date"):
                events.append(
                    {
                        "id": f"{o['name']}_expiry",
                        "event_type": "offer_expiry",
                        "title": f"Offer Expiry: {cand_name or cand_id or 'Candidate'}{' - ' + job_title if job_title else ''}",
                        "start": str(o["expiry_date"]),
                        "end": None,
                        "status": st,
                        "candidate": {"id": cand_id, "name": cand_name} if cand_id else None,
                        "job": {"id": job_id, "title": job_title} if job_id else None,
                        "source_doctype": "Offer",
                        "source_name": o["name"],
                    }
                )

        return events

    def _get_job_opening_events(
        self, company: str, jobs_map: dict[str, str]
    ) -> list[dict[str, Any]]:
        """Fetch job opening events from Job Opening DocType."""
        jobs = frappe.get_all(
            "Job Opening",
            filters={"company": company},
            fields=["name", "job_code", "job_title", "closing_date", "target_joining_date", "status"],
        )

        events = []
        for j in jobs:
            job_title = j.get("job_title") or j.get("job_code") or j["name"]
            st = j.get("status", "Open")

            # 1. Job Closing Date
            if j.get("closing_date"):
                events.append(
                    {
                        "id": f"{j['name']}_closing",
                        "event_type": "job_closing",
                        "title": f"Job Closing: {job_title}",
                        "start": str(j["closing_date"]),
                        "end": None,
                        "status": st,
                        "candidate": None,
                        "job": {"id": j["name"], "title": job_title},
                        "source_doctype": "Job Opening",
                        "source_name": j["name"],
                    }
                )

            # 2. Target Joining Date
            if j.get("target_joining_date"):
                events.append(
                    {
                        "id": f"{j['name']}_target_joining",
                        "event_type": "job_target_joining",
                        "title": f"Target Joining Date: {job_title}",
                        "start": str(j["target_joining_date"]),
                        "end": None,
                        "status": st,
                        "candidate": None,
                        "job": {"id": j["name"], "title": job_title},
                        "source_doctype": "Job Opening",
                        "source_name": j["name"],
                    }
                )

        return events

    def _get_job_application_events(
        self, company: str, candidates_map: dict[str, str], jobs_map: dict[str, str]
    ) -> list[dict[str, Any]]:
        """Fetch application received events from Job Application DocType."""
        apps = frappe.get_all(
            "Job Application",
            filters={"company": company},
            fields=["name", "candidate", "job_opening", "applied_on", "status", "current_stage"],
        )

        events = []
        for a in apps:
            if not a.get("applied_on"):
                continue

            cand_id = a.get("candidate")
            cand_name = candidates_map.get(cand_id) if cand_id else None

            job_id = a.get("job_opening")
            job_title = jobs_map.get(job_id) if job_id else None

            events.append(
                {
                    "id": f"{a['name']}_applied",
                    "event_type": "application_date",
                    "title": f"Application Received: {cand_name or cand_id or 'Candidate'}{' - ' + job_title if job_title else ''}",
                    "start": str(a["applied_on"]),
                    "end": None,
                    "status": a.get("status") or a.get("current_stage") or "Open",
                    "candidate": {"id": cand_id, "name": cand_name} if cand_id else None,
                    "job": {"id": job_id, "title": job_title} if job_id else None,
                    "source_doctype": "Job Application",
                    "source_name": str(a["name"]),
                }
            )

        return events

    def _filter_events(
        self,
        events: list[dict[str, Any]],
        from_date: str | None,
        to_date: str | None,
        event_type: str | None,
        status: str | None,
    ) -> list[dict[str, Any]]:
        """Apply date range, event_type, and status filters."""
        result = []

        from_str = str(from_date)[:10] if from_date else None
        to_str = str(to_date)[:10] if to_date else None

        # Standardize event_type matching
        types_to_match = set()
        if event_type:
            raw_types = [t.strip().lower() for t in str(event_type).split(",") if t.strip()]
            for t in raw_types:
                if t in ("interview", "interviews"):
                    types_to_match.add("interview")
                elif t in ("offer", "offers"):
                    types_to_match.update(["offer_joining", "offer_date", "offer_expiry", "joining_date"])
                elif t in ("job_opening", "job", "jobs"):
                    types_to_match.update(["job_closing", "job_target_joining"])
                elif t in ("job_application", "application", "applications"):
                    types_to_match.add("application_date")
                else:
                    types_to_match.add(t)

        status_clean = str(status).strip().lower() if status else None

        for ev in events:
            start_date_str = str(ev.get("start", ""))[:10]

            # Date Range Filter
            if from_str and start_date_str < from_str:
                continue
            if to_str and start_date_str > to_str:
                continue

            # Event Type Filter
            if types_to_match:
                ev_type = str(ev.get("event_type", "")).lower()
                src_dt = str(ev.get("source_doctype", "")).lower()
                if ev_type not in types_to_match and src_dt not in types_to_match:
                    continue

            # Status Filter
            if status_clean:
                ev_status = str(ev.get("status", "")).strip().lower()
                if ev_status != status_clean:
                    continue

            result.append(ev)

        return result
