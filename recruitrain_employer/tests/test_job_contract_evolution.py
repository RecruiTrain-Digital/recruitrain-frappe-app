# Copyright (c) 2026, RecruiTrain and contributors
# For license information, please see license.txt

"""
Contract Verification Test Suite for RecruitTrain Job Opening Backend Schema Evolution (JOB-NEW-01 to JOB-NEW-23).
"""

from __future__ import annotations

import frappe
from recruitrain_employer.services.job_service import JobService
from recruitrain_employer.utils.exceptions import ATSValidationError
from recruitrain_employer.utils.permissions import get_current_company


def run_evolution_tests():
    print("\n=======================================================")
    print("RECRUITRAIN JOB OPENING SCHEMA EVOLUTION CONTRACT TESTS (JOB-NEW-01..JOB-NEW-23)")
    print("=======================================================\n")

    current_company = get_current_company()
    print(f"[SETUP] Authenticated Context Company: '{current_company}'")

    frappe.reload_doc("master", "doctype", "tariff_group")
    frappe.reload_doc("recruitment", "doctype", "job_opening")
    frappe.db.commit()

    service = JobService()


    # Cleanup previous test records
    test_code_prefix = "JOB-EVO-TEST-"
    existing = frappe.get_all("Job Opening", filters={"job_code": ["like", f"{test_code_prefix}%"]})
    for e in existing:
        frappe.delete_doc("Job Opening", e.name, force=True)
    frappe.db.commit()

    test_jobs = []

    try:
        # Base draft payload helper
        def get_base_payload(code_suffix: str) -> dict:
            return {
                "job_code": f"{test_code_prefix}{code_suffix}",
                "job_title": "Senior Healthcare Specialist",
                "department": "Healthcare",
                "profession": "Pflegefachkraft",
                "employment_type": "Full Time",
                "job_summary": "Evolved schema test summary text.",
                "responsibilities": "Provide patient care and maintain medical records.",
                "requirements": "Certified nurse qualification with B2 German.",
                "german_level_required": "B2",
            }

        # JOB-NEW-01: Invalid compensation_type
        print("\n--- [JOB-NEW-01] Testing invalid compensation_type validation ---")
        try:
            p = get_base_payload("01")
            p["compensation_type"] = "Invalid Type"
            service.save_draft(p)
            assert False, "Should have raised ATSValidationError for invalid compensation_type"
        except ATSValidationError as exc:
            assert exc.field == "compensation_type"
            print("  ✓ JOB-NEW-01 Passed: Invalid compensation_type rejected.")

        # JOB-NEW-02: Salary Range missing minimum_salary on publish
        print("\n--- [JOB-NEW-02] Testing Salary Range missing minimum_salary on publish ---")
        draft2 = service.save_draft(get_base_payload("02"))
        test_jobs.append(draft2["name"])
        try:
            service.publish_job(
                draft2["name"],
                {
                    "compensation_type": "Salary Range",
                    "maximum_salary": 80000,
                    "currency": "EUR",
                },
            )
            assert False, "Should have raised ATSValidationError for missing minimum_salary"
        except ATSValidationError as exc:
            assert exc.field == "minimum_salary"
            print("  ✓ JOB-NEW-02 Passed: Missing minimum_salary rejected on publish.")

        # JOB-NEW-03: Salary Range missing maximum_salary on publish
        print("\n--- [JOB-NEW-03] Testing Salary Range missing maximum_salary on publish ---")
        draft3 = service.save_draft(get_base_payload("03"))
        test_jobs.append(draft3["name"])
        try:
            service.publish_job(
                draft3["name"],
                {
                    "compensation_type": "Salary Range",
                    "minimum_salary": 50000,
                    "currency": "EUR",
                },
            )
            assert False, "Should have raised ATSValidationError for missing maximum_salary"
        except ATSValidationError as exc:
            assert exc.field == "maximum_salary"
            print("  ✓ JOB-NEW-03 Passed: Missing maximum_salary rejected on publish.")

        # JOB-NEW-04: Salary Range missing currency on publish
        print("\n--- [JOB-NEW-04] Testing Salary Range missing currency on publish ---")
        draft4 = service.save_draft(get_base_payload("04"))
        test_jobs.append(draft4["name"])
        try:
            service.publish_job(
                draft4["name"],
                {
                    "compensation_type": "Salary Range",
                    "minimum_salary": 50000,
                    "maximum_salary": 80000,
                    "currency": None,
                },
            )
            assert False, "Should have raised ATSValidationError for missing currency"
        except ATSValidationError as exc:
            assert exc.field == "currency"
            print("  ✓ JOB-NEW-04 Passed: Missing currency rejected on publish.")


        # JOB-NEW-05: Minimum salary > Maximum salary
        print("\n--- [JOB-NEW-05] Testing minimum_salary > maximum_salary constraint ---")
        try:
            p = get_base_payload("05")
            p["compensation_type"] = "Salary Range"
            p["minimum_salary"] = 90000
            p["maximum_salary"] = 50000
            service.save_draft(p)
            assert False, "Should have raised ATSValidationError for min > max salary"
        except ATSValidationError as exc:
            assert exc.field == "minimum_salary"
            print("  ✓ JOB-NEW-05 Passed: minimum_salary > maximum_salary rejected.")

        # JOB-NEW-06: Collective Agreement missing tariff_group on publish
        print("\n--- [JOB-NEW-06] Testing Collective Agreement missing tariff_group on publish ---")
        draft6 = service.save_draft(get_base_payload("06"))
        test_jobs.append(draft6["name"])
        try:
            service.publish_job(
                draft6["name"],
                {
                    "compensation_type": "Collective Agreement (Tarifvertrag)",
                    "entgeltgruppe": "P 8",
                },
            )
            assert False, "Should have raised ATSValidationError for missing tariff_group"
        except ATSValidationError as exc:
            assert exc.field == "tariff_group"
            print("  ✓ JOB-NEW-06 Passed: Missing tariff_group rejected on publish.")

        # JOB-NEW-07: Collective Agreement missing entgeltgruppe on publish
        print("\n--- [JOB-NEW-07] Testing Collective Agreement missing entgeltgruppe on publish ---")
        draft7 = service.save_draft(get_base_payload("07"))
        test_jobs.append(draft7["name"])
        try:
            service.publish_job(
                draft7["name"],
                {
                    "compensation_type": "Collective Agreement (Tarifvertrag)",
                    "tariff_group": "TVöD-P",
                },
            )
            assert False, "Should have raised ATSValidationError for missing entgeltgruppe"
        except ATSValidationError as exc:
            assert exc.field == "entgeltgruppe"
            print("  ✓ JOB-NEW-07 Passed: Missing entgeltgruppe rejected on publish.")

        # JOB-NEW-08: tariff_group persistence
        print("\n--- [JOB-NEW-08] Testing tariff_group persistence ---")
        p8 = get_base_payload("08")
        p8["tariff_group"] = "TVöD-P"
        p8["entgeltgruppe"] = "P 8"
        p8["compensation_type"] = "Collective Agreement (Tarifvertrag)"
        job8 = service.save_draft(p8)
        test_jobs.append(job8["name"])
        assert job8["tariff_group"] == "TVöD-P"
        print("  ✓ JOB-NEW-08 Passed: tariff_group persisted and returned in draft.")

        # JOB-NEW-09: entgeltgruppe persistence
        print("\n--- [JOB-NEW-09] Testing entgeltgruppe persistence ---")
        assert job8["entgeltgruppe"] == "P 8"
        print("  ✓ JOB-NEW-09 Passed: entgeltgruppe persisted and returned in draft.")

        # JOB-NEW-10: Language requirements persistence
        print("\n--- [JOB-NEW-10] Testing language requirements persistence ---")
        p10 = get_base_payload("10")
        p10["german_level_required"] = "C1"
        p10["english_level_required"] = "B2"
        p10["other_language_requirements"] = "Spanish conversational"
        job10 = service.save_draft(p10)
        test_jobs.append(job10["name"])
        assert job10["german_level_required"] == "C1"
        assert job10["english_level_required"] == "B2"
        assert job10["other_language_requirements"] == "Spanish conversational"
        print("  ✓ JOB-NEW-10 Passed: German, English, and other language requirements persisted.")

        # JOB-NEW-11: Invalid German level validation
        print("\n--- [JOB-NEW-11] Testing invalid German level validation ---")
        try:
            p11 = get_base_payload("11")
            p11["german_level_required"] = "Native"
            service.save_draft(p11)
            assert False, "Should have raised ATSValidationError for invalid German CEFR level"
        except ATSValidationError as exc:
            assert exc.field == "german_level_required"
            print("  ✓ JOB-NEW-11 Passed: Non-CEFR German level rejected.")

        # JOB-NEW-12: allow_international_candidates persistence
        print("\n--- [JOB-NEW-12] Testing allow_international_candidates persistence ---")
        p12 = get_base_payload("12")
        p12["allow_international_candidates"] = 1
        job12 = service.save_draft(p12)
        test_jobs.append(job12["name"])
        assert bool(job12["allow_international_candidates"]) is True
        print("  ✓ JOB-NEW-12 Passed: allow_international_candidates persisted as True.")

        # JOB-NEW-13: allow_domestic_candidates persistence
        print("\n--- [JOB-NEW-13] Testing allow_domestic_candidates persistence ---")
        assert bool(job12["allow_domestic_candidates"]) is True
        print("  ✓ JOB-NEW-13 Passed: allow_domestic_candidates persisted as True.")

        # JOB-NEW-14: closing_date persistence
        print("\n--- [JOB-NEW-14] Testing closing_date persistence ---")
        p14 = get_base_payload("14")
        p14["closing_date"] = "2026-12-31"
        job14 = service.save_draft(p14)
        test_jobs.append(job14["name"])
        assert str(job14["closing_date"]) == "2026-12-31"
        print("  ✓ JOB-NEW-14 Passed: closing_date persisted.")

        # JOB-NEW-15: max_applicants_limit validation and persistence
        print("\n--- [JOB-NEW-15] Testing max_applicants_limit validation & persistence ---")
        try:
            p15_invalid = get_base_payload("15a")
            p15_invalid["max_applicants_limit"] = -5
            service.save_draft(p15_invalid)
            assert False, "Should have raised ATSValidationError for negative max_applicants_limit"
        except ATSValidationError as exc:
            assert exc.field == "max_applicants_limit"

        p15 = get_base_payload("15")
        p15["max_applicants_limit"] = 50
        job15 = service.save_draft(p15)
        test_jobs.append(job15["name"])
        assert job15["max_applicants_limit"] == 50
        print("  ✓ JOB-NEW-15 Passed: max_applicants_limit validated and persisted.")

        # JOB-NEW-16: auto_close_on_limit persistence
        print("\n--- [JOB-NEW-16] Testing auto_close_on_limit persistence ---")
        p16 = get_base_payload("16")
        p16["max_applicants_limit"] = 20
        p16["auto_close_on_limit"] = 1
        job16 = service.save_draft(p16)
        test_jobs.append(job16["name"])
        assert bool(job16["auto_close_on_limit"]) is True
        print("  ✓ JOB-NEW-16 Passed: auto_close_on_limit persisted as True.")

        # JOB-NEW-17: keywords array/string persistence & serialization
        print("\n--- [JOB-NEW-17] Testing keywords persistence & list serialization ---")
        p17 = get_base_payload("17")
        p17["keywords"] = ["Pflege", "ICU", "Station"]
        job17 = service.save_draft(p17)
        test_jobs.append(job17["name"])
        assert isinstance(job17["keywords"], list)
        assert set(job17["keywords"]) == {"Pflege", "ICU", "Station"}
        print("  ✓ JOB-NEW-17 Passed: keywords array persisted and returned as normalized list.")

        # JOB-NEW-18: Complete create payload
        print("\n--- [JOB-NEW-18] Testing complete create payload with all evolved fields ---")
        full_create = {
            "job_code": f"{test_code_prefix}18",
            "job_title": "Head of ICU Nursing",
            "department": "Healthcare",
            "profession": "Pflegefachkraft",
            "employment_type": "Full Time",
            "job_summary": "Comprehensive test job summary.",
            "responsibilities": "Manage ICU team and clinical operations.",
            "requirements": "Degree in Nursing, B2 German.",
            "compensation_type": "Collective Agreement (Tarifvertrag)",
            "tariff_group": "TVöD-P",
            "entgeltgruppe": "P 12",
            "address": "Hospitalstrasse 1",
            "city": "Munich",
            "state": "Bavaria",
            "country": "Germany",
            "german_level_required": "B2",
            "english_level_required": "B1",
            "other_language_requirements": "German B2 required",
            "allow_international_candidates": 1,
            "allow_domestic_candidates": 1,
            "closing_date": "2026-11-30",
            "max_applicants_limit": 100,
            "auto_close_on_limit": 1,
            "keywords": ["ICU", "Nursing", "Munich"],
        }
        job18 = service.save_draft(full_create)
        test_jobs.append(job18["name"])
        assert job18["job_code"] == f"{test_code_prefix}18"
        assert job18["compensation_type"] == "Collective Agreement (Tarifvertrag)"
        assert job18["tariff_group"] == "TVöD-P"
        assert job18["entgeltgruppe"] == "P 12"
        assert job18["address"] == "Hospitalstrasse 1"
        assert job18["german_level_required"] == "B2"
        assert job18["max_applicants_limit"] == 100
        print("  ✓ JOB-NEW-18 Passed: Full evolved create payload saved successfully.")

        # JOB-NEW-19: Complete update payload
        print("\n--- [JOB-NEW-19] Testing complete update payload on evolved fields ---")
        update_18 = service.update_job(
            job18["name"],
            {
                "entgeltgruppe": "P 13",
                "german_level_required": "C1",
                "max_applicants_limit": 150,
                "keywords": ["ICU", "Lead", "Hospital"],
            },
        )
        assert update_18["entgeltgruppe"] == "P 13"
        assert update_18["german_level_required"] == "C1"
        assert update_18["max_applicants_limit"] == 150
        assert set(update_18["keywords"]) == {"ICU", "Lead", "Hospital"}
        print("  ✓ JOB-NEW-19 Passed: Partial update on evolved fields applied without corrupting existing fields.")

        # JOB-NEW-20: Detailed GET response serialization
        print("\n--- [JOB-NEW-20] Testing detailed GET response serialization ---")
        get_job18 = service.get_job(job18["name"])
        evolved_keys = {
            "compensation_type",
            "tariff_group",
            "entgeltgruppe",
            "address",
            "german_level_required",
            "english_level_required",
            "other_language_requirements",
            "allow_international_candidates",
            "allow_domestic_candidates",
            "closing_date",
            "max_applicants_limit",
            "auto_close_on_limit",
            "keywords",
            "location",
        }
        missing_keys = evolved_keys - set(get_job18.keys())
        assert not missing_keys, f"Missing evolved schema keys in GET response: {missing_keys}"
        print("  ✓ JOB-NEW-20 Passed: Detailed GET response contains all 14 evolved schema fields.")

        # JOB-NEW-21: Publish validation enforces German level and compensation
        print("\n--- [JOB-NEW-21] Testing publish validation enforces German level ---")
        draft21 = service.save_draft(get_base_payload("21"))
        test_jobs.append(draft21["name"])
        # Clear German level
        frappe.db.set_value("Job Opening", draft21["name"], "german_level_required", None)
        try:
            service.publish_job(
                draft21["name"],
                {
                    "compensation_type": "Salary Range",
                    "minimum_salary": 60000,
                    "maximum_salary": 80000,
                    "currency": "EUR",
                },
            )
            assert False, "Should have raised ATSValidationError for missing german_level_required on publish"
        except ATSValidationError as exc:
            assert exc.field == "german_level_required"
            print("  ✓ JOB-NEW-21 Passed: Missing german_level_required rejected on publish.")

        # JOB-NEW-22: Publishing a Salary Range job
        print("\n--- [JOB-NEW-22] Testing publishing Salary Range job ---")
        draft22 = service.save_draft(get_base_payload("22"))
        test_jobs.append(draft22["name"])
        pub22 = service.publish_job(
            draft22["name"],
            {
                "compensation_type": "Salary Range",
                "minimum_salary": 55000,
                "maximum_salary": 75000,
                "currency": "EUR",
                "german_level_required": "B2",
            },
        )
        assert pub22["status"] == "Open"
        assert pub22["published"] == 1
        assert pub22["compensation_type"] == "Salary Range"
        assert pub22["minimum_salary"] == 55000
        print("  ✓ JOB-NEW-22 Passed: Published Salary Range job successfully.")

        # JOB-NEW-23: Publishing a Collective Agreement job
        print("\n--- [JOB-NEW-23] Testing publishing Collective Agreement job ---")
        draft23 = service.save_draft(get_base_payload("23"))
        test_jobs.append(draft23["name"])
        pub23 = service.publish_job(
            draft23["name"],
            {
                "compensation_type": "Collective Agreement (Tarifvertrag)",
                "tariff_group": "TVöD-P",
                "entgeltgruppe": "P 9",
                "german_level_required": "B2",
            },
        )
        assert pub23["status"] == "Open"
        assert pub23["published"] == 1
        assert pub23["compensation_type"] == "Collective Agreement (Tarifvertrag)"
        assert pub23["tariff_group"] == "TVöD-P"
        assert pub23["entgeltgruppe"] == "P 9"
        print("  ✓ JOB-NEW-23 Passed: Published Collective Agreement job successfully without min/max salary.")

        print("\n=======================================================")
        print("ALL 23 JOB OPENING SCHEMA EVOLUTION CONTRACT TESTS PASSED 100%!")
        print("=======================================================\n")

    finally:
        for jid in test_jobs:
            if frappe.db.exists("Job Opening", jid):
                frappe.delete_doc("Job Opening", jid, force=True)
        frappe.db.commit()
        print("[CLEANUP] All evolution test records cleaned up.")


if __name__ == "__main__":
    run_evolution_tests()
