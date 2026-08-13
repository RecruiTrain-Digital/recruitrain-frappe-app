# Phase 14.4 Backend Evolution Certification Report
**Domain:** Job Opening Backend Evolution (Compensation & Posting Requirements)  
**Date:** August 13, 2026  
**Status:** FULLY CERTIFIED & FROZEN (100% PASS RATE)

---

## 1. Executive Summary

This report certifies the successful backend evolution of the **Job Opening** domain for RecruitTrain ATS. The schema and business rules have been expanded to accommodate updated business posting requirements—specifically healthcare-focused professional roles, dual compensation models (Salary Range vs. Collective Agreement / Tarifvertrag), granular location & address fields, language requirements (CEFR standard), candidate origin preferences, and applicant limit constraints.

All changes maintain strict compliance with the **"Thin Client" Architecture** and **Backend-As-Source-Of-Truth** design principles. The backend contract has passed 100% of both the regression verification suite (**JOB-01 through JOB-15**) and the new evolution test suite (**JOB-NEW-01 through JOB-NEW-23**).

The Job Opening backend contract is now **FROZEN**. Frontend development for Phase 14.5 is officially authorized to proceed.

---

## 2. Taxonomy & Schema Evolution

### 2.1 Tariff Group Master Taxonomy (`Tariff Group`)
- **DocType Schema**: Created `Tariff Group` DocType (`tariff_group.json`, `tariff_group.py`) under the `Master` module.
- **Seeder & Validator**: Implemented `TariffGroupValidator` (`tariff_group_validator.py`) with canonical seeding for healthcare collective agreements (`TVöD-P`, `TV-L Pflege`, `AVR Caritas`, `AVR Diakonie`, `TV-Ärzte`) and pay scale grades (`Entgeltgruppen` P 5 through P 16, Ä1 through Ä4).
- **Category Resolution**: Supports filtered query by department and profession.

### 2.2 Healthcare Profession Taxonomy Expansion
- Extended `PROFESSION_SYNONYM_MAP` in `profession_validator.py` with healthcare roles and aliases (e.g., `Medizinische Fachangestellte (MFA)`, `Operationstechnische Assistenz (OTA)`, `Anästhesietechnische Assistenz (ATA)`, `Gesundheits- und Krankenpfleger`, `Altenpfleger`, `Pflegefachmann / Pflegefachfrau`).

### 2.3 Job Opening DocType Schema (`Job Opening`)
Updated `job_opening.json` with the following evolved fields:
- **Compensation**: `compensation_type` (Select), `tariff_group` (Data/Link), `entgeltgruppe` (Data).
- **Location**: `address` (Small Text).
- **Language Requirements**: `german_level_required` (Select: A1-C2), `english_level_required` (Select: A1-C2), `other_language_requirements` (Small Text).
- **Candidate Preferences**: `allow_international_candidates` (Check, default 1), `allow_domestic_candidates` (Check, default 1).
- **Application Settings**: `max_applicants_limit` (Int), `auto_close_on_limit` (Check, default 0).
- **Posting Details**: `closing_date` (Date), `keywords` (Small Text / JSON array).

---

## 3. Compensation & Validation Rules

`JobValidator` (`job_validator.py`) was enhanced with explicit validation routines:

1. **Compensation Model Validation (`validate_compensation`)**:
   - **`Salary Range`**: Validates numeric bounds (`minimum_salary <= maximum_salary`). On publish (when salary is non-negotiable), requires `minimum_salary`, `maximum_salary`, and `currency`.
   - **`Collective Agreement (Tarifvertrag)`**: On publish, strictly requires `tariff_group` and `entgeltgruppe`. Min/max salary fields are optional.
   - Handles Frappe ORM `0.0` database default values gracefully.

2. **Language Level Validation (`validate_language_requirements`)**:
   - Strictly enforces standard CEFR levels (`A1`, `A2`, `B1`, `B2`, `C1`, `C2`).
   - `german_level_required` is strictly enforced on publish for healthcare job postings.

3. **Applicant Limit Validation (`validate_applicant_limit`)**:
   - Ensures `max_applicants_limit` is a positive integer (maps `0` / unsupplied to `None`).

---

## 4. API Controller & Master Services

Registered endpoints in `recruitrain_employer.api.master`:
- **`list_tariff_groups(department, profession)`**: Whitelisted API endpoint to retrieve filtered tariff groups and Entgeltgruppen for dynamic UI cascading selects.
- **`get_tariff_groups()`**: Whitelisted API endpoint returning all seeded canonical tariff groups.

Updated `recruitrain_employer.api.jobs` & `JobService`:
- Updated `JOB_FIELD_ALIASES` mapping camelCase keys (`maxApplicantsLimit`, `germanLevel`, `tariffGroup`, etc.) to canonical database fields.
- Normalized `keywords` array inputs into comma-separated strings for database persistence and array lists for API responses.
- Updated `_LIST_FIELDS` and `_DETAIL_FIELDS` in `JobService` to return all evolved schema attributes.
- Expanded `_extract_list_filters` to support filtering by `compensation_type`, `tariff_group`, `german_level_required`, `allow_international_candidates`, and `allow_domestic_candidates`.

---

## 5. Contract Verification Results

### Suite 1: Evolved Contract Suite (`test_job_contract_evolution.py`)
Executed **23 automated test cases** covering all schema evolution requirements:

| Test ID | Scenario | Result |
| :--- | :--- | :---: |
| **JOB-NEW-01** | Reject invalid `compensation_type` string | **PASS** |
| **JOB-NEW-02** | Require `minimum_salary` on publish for Salary Range | **PASS** |
| **JOB-NEW-03** | Require `maximum_salary` on publish for Salary Range | **PASS** |
| **JOB-NEW-04** | Require `currency` on publish for Salary Range | **PASS** |
| **JOB-NEW-05** | Reject `minimum_salary > maximum_salary` | **PASS** |
| **JOB-NEW-06** | Require `tariff_group` on publish for Collective Agreement | **PASS** |
| **JOB-NEW-07** | Require `entgeltgruppe` on publish for Collective Agreement | **PASS** |
| **JOB-NEW-08** | Persist and return `tariff_group` | **PASS** |
| **JOB-NEW-09** | Persist and return `entgeltgruppe` | **PASS** |
| **JOB-NEW-10** | Persist and return German/English/Other language requirements | **PASS** |
| **JOB-NEW-11** | Reject non-CEFR German language level | **PASS** |
| **JOB-NEW-12** | Persist `allow_international_candidates` preference | **PASS** |
| **JOB-NEW-13** | Persist `allow_domestic_candidates` preference | **PASS** |
| **JOB-NEW-14** | Validate and persist `closing_date` | **PASS** |
| **JOB-NEW-15** | Validate and persist `max_applicants_limit` | **PASS** |
| **JOB-NEW-16** | Persist `auto_close_on_limit` flag | **PASS** |
| **JOB-NEW-17** | Normalize array/string `keywords` into returned list | **PASS** |
| **JOB-NEW-18** | Save complete create payload with all evolved fields | **PASS** |
| **JOB-NEW-19** | Apply partial update on evolved fields without side-effects | **PASS** |
| **JOB-NEW-20** | Detailed GET response returns all 14 evolved schema fields | **PASS** |
| **JOB-NEW-21** | Enforce mandatory `german_level_required` on publish | **PASS** |
| **JOB-NEW-22** | Publish valid Salary Range Job Opening | **PASS** |
| **JOB-NEW-23** | Publish valid Collective Agreement Job Opening without min/max salary | **PASS** |

### Suite 2: Regression Contract Suite (`test_job_contract_verification.py`)
Executed **15 core contract tests (JOB-01 through JOB-15)**:

| Test Suite | Total Tests | Passed | Failed | Pass Rate |
| :--- | :---: | :---: | :---: | :---: |
| **Core Job Contract (JOB-01..15)** | 15 | 15 | 0 | **100%** |
| **Evolved Job Contract (JOB-NEW-01..23)** | 23 | 23 | 0 | **100%** |
| **TOTAL** | **38** | **38** | **0** | **100%** |

---

## 6. Frontend Handoff Specifications (Phase 14.5)

Frontend developers should use the following data contracts for Phase 14.5:

### 6.1 Master Data Endpoints
- `GET /api/method/recruitrain_employer.api.master.list_tariff_groups`
  - Query params: `department` (optional), `profession` (optional).
  - Returns array of `{ name, tariff_group_name, default_entgeltgruppen: [...] }`.

### 6.2 Job Opening Entity Structure
```json
{
  "name": "JOB-2026-00042",
  "job_code": "JOB-2026-00042",
  "job_title": "Pflegefachkraft Intensivmedizin",
  "company": "RecruiTrain",
  "department": "Healthcare",
  "profession": "Pflegefachkraft",
  "employment_type": "Full Time",
  "compensation_type": "Collective Agreement (Tarifvertrag)",
  "tariff_group": "TVöD-P",
  "entgeltgruppe": "P 8",
  "address": "Krankenhausstrasse 12",
  "city": "Munich",
  "state": "Bavaria",
  "country": "Germany",
  "german_level_required": "B2",
  "english_level_required": "B1",
  "other_language_requirements": "Basic Medical German",
  "allow_international_candidates": 1,
  "allow_domestic_candidates": 1,
  "max_applicants_limit": 50,
  "auto_close_on_limit": 1,
  "keywords": ["ICU", "Nursing", "Munich"],
  "closing_date": "2026-12-31",
  "status": "Open",
  "published": 1
}
```

---

## 7. Conclusion & Next Steps

Phase 14.4 Backend Evolution is **100% COMPLETE AND CERTIFIED**.

- **Backend State**: FROZEN
- **Next Step**: Proceed to Phase 14.5 for Frontend Jobs Form & Drawer Reconciliation.
