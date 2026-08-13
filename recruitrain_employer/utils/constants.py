# Copyright (c) 2024, RecruiTrain and contributors
# For license information, please see license.txt

"""
recruitrain_employer.utils.constants
=======================================

Application-Wide Constants for the RecruiTrain Employer ATS.

Centralising all magic strings, numeric thresholds, and allowed-value lists
in this module makes the codebase easier to maintain and reduces the risk of
typos causing silent bugs.

Sections
--------
1.  DocType Names
2.  Employer Roles
3.  Job Opening Statuses
4.  Application Pipeline Stages
5.  Interview Constants
6.  Offer Constants
7.  File Upload Limits
8.  Pagination Defaults
9.  Required Fields by DocType
10. Miscellaneous
"""

# ---------------------------------------------------------------------------
# 1. DocType Names
# ---------------------------------------------------------------------------

DOCTYPE_CANDIDATE = "Candidate"
DOCTYPE_CANDIDATE_EDUCATION = "Candidate Education"
DOCTYPE_CANDIDATE_EXPERIENCE = "Candidate Experience"
DOCTYPE_CANDIDATE_SKILL = "Candidate Skill"
DOCTYPE_CANDIDATE_LANGUAGE = "Candidate Language"
DOCTYPE_CANDIDATE_CERTIFICATION = "Candidate Certification"
DOCTYPE_CANDIDATE_DOCUMENT = "Candidate Document"

DOCTYPE_COMPANY = "Company"
DOCTYPE_EMPLOYER_USER = "Employer User"
DOCTYPE_EMPLOYER_SETTINGS = "Employer Settings"

DOCTYPE_JOB_OPENING = "Job Opening"
DOCTYPE_JOB_APPLICATION = "Job Application"

DOCTYPE_INTERVIEW = "Interview"
DOCTYPE_INTERVIEW_FEEDBACK = "Interview Feedback"

DOCTYPE_OFFER = "Offer"

DOCTYPE_ACTIVITY_LOG = "Activity Log"
DOCTYPE_NOTIFICATION = "Notification Log"

# Subscription DocTypes
DOCTYPE_SUBSCRIPTION_PLAN = "Subscription_Plan_Recruitrain"
DOCTYPE_SUBSCRIPTION_PLAN_RECRUITRAIN = "Subscription_Plan_Recruitrain"
DOCTYPE_COMPANY_SUBSCRIPTION = "Company Subscription"
DOCTYPE_SUBSCRIPTION_USAGE = "Subscription Usage"
DOCTYPE_BILLING_TRANSACTION = "Billing Transaction"

# Subscription Statuses
SUBSCRIPTION_STATUS_TRIAL = "Trial"
SUBSCRIPTION_STATUS_ACTIVE = "Active"
SUBSCRIPTION_STATUS_PAST_DUE = "Past Due"
SUBSCRIPTION_STATUS_CANCELLED = "Cancelled"
SUBSCRIPTION_STATUS_EXPIRED = "Expired"
SUBSCRIPTION_STATUS_PAUSED = "Paused"

ALLOWED_SUBSCRIPTION_STATUSES = [
    SUBSCRIPTION_STATUS_TRIAL,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_PAST_DUE,
    SUBSCRIPTION_STATUS_CANCELLED,
    SUBSCRIPTION_STATUS_EXPIRED,
    SUBSCRIPTION_STATUS_PAUSED,
]

# Master DocTypes
DOCTYPE_SKILL = "Skill"
DOCTYPE_PROFESSION = "Profession"
DOCTYPE_EMPLOYMENT_TYPE = "Employment Type"
DOCTYPE_DEPARTMENT = "Department"
DOCTYPE_INDUSTRY = "Industry"

# ---------------------------------------------------------------------------
# 2. Employer Roles
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Role constants must match the Select options in employer_user.json exactly:
# Administrator | HR Manager | Recruiter | Hiring Manager | Interviewer | Viewer
# ---------------------------------------------------------------------------

ROLE_ADMIN = "Administrator"
ROLE_HR_MANAGER = "HR Manager"
ROLE_HIRING_MANAGER = "Hiring Manager"
ROLE_RECRUITER = "Recruiter"
ROLE_INTERVIEWER = "Interviewer"
ROLE_VIEWER = "Viewer"

#: Ordered list of employer roles from highest to lowest privilege.
#: Matches the Employer User DocType `role` field options exactly.
EMPLOYER_ROLES = [
    ROLE_ADMIN,
    ROLE_HR_MANAGER,
    ROLE_HIRING_MANAGER,
    ROLE_RECRUITER,
    ROLE_INTERVIEWER,
    ROLE_VIEWER,
]

# ---------------------------------------------------------------------------
# 3. Job Opening Statuses
# ---------------------------------------------------------------------------

JOB_STATUS_DRAFT = "Draft"
JOB_STATUS_OPEN = "Open"
JOB_STATUS_PAUSED = "Paused"
JOB_STATUS_ON_HOLD = "Paused"  # Alias for backward compatibility
JOB_STATUS_CLOSED = "Closed"
JOB_STATUS_FILLED = "Filled"
JOB_STATUS_CANCELLED = "Cancelled"

ALLOWED_JOB_STATUSES = [
    JOB_STATUS_DRAFT,
    JOB_STATUS_OPEN,
    JOB_STATUS_PAUSED,
    JOB_STATUS_CLOSED,
    JOB_STATUS_FILLED,
    JOB_STATUS_CANCELLED,
]

# ---------------------------------------------------------------------------
# 4. Application Pipeline Stages
# ---------------------------------------------------------------------------

APPLICATION_STAGE_APPLIED = "Applied"
APPLICATION_STAGE_SCREENING = "Screening"
APPLICATION_STAGE_INTERVIEW = "Interview"
APPLICATION_STAGE_ASSESSMENT = "Assessment"
APPLICATION_STAGE_OFFER = "Offer"
APPLICATION_STAGE_HIRED = "Hired"
APPLICATION_STAGE_REJECTED = "Rejected"
APPLICATION_STAGE_WITHDRAWN = "Withdrawn"

#: Ordered pipeline stages (terminal stages at the end).
APPLICATION_STAGES = [
    APPLICATION_STAGE_APPLIED,
    APPLICATION_STAGE_SCREENING,
    APPLICATION_STAGE_INTERVIEW,
    APPLICATION_STAGE_ASSESSMENT,
    APPLICATION_STAGE_OFFER,
    APPLICATION_STAGE_HIRED,
    APPLICATION_STAGE_REJECTED,
    APPLICATION_STAGE_WITHDRAWN,
]

#: Terminal stages from which no further transitions are allowed.
APPLICATION_TERMINAL_STAGES = [
    APPLICATION_STAGE_HIRED,
    APPLICATION_STAGE_REJECTED,
    APPLICATION_STAGE_WITHDRAWN,
]

# ---------------------------------------------------------------------------
# 5. Interview Constants
# ---------------------------------------------------------------------------

INTERVIEW_TYPE_PHONE = "Phone Screen"
INTERVIEW_TYPE_VIDEO = "Video Call"
INTERVIEW_TYPE_TECHNICAL = "Technical"
INTERVIEW_TYPE_HR = "HR"
INTERVIEW_TYPE_PANEL = "Panel"
INTERVIEW_TYPE_ONSITE = "Onsite"

INTERVIEW_TYPES = [
    INTERVIEW_TYPE_PHONE,
    INTERVIEW_TYPE_VIDEO,
    INTERVIEW_TYPE_TECHNICAL,
    INTERVIEW_TYPE_HR,
    INTERVIEW_TYPE_PANEL,
    INTERVIEW_TYPE_ONSITE,
]

INTERVIEW_STATUS_SCHEDULED = "Scheduled"
INTERVIEW_STATUS_COMPLETED = "Completed"
INTERVIEW_STATUS_CANCELLED = "Cancelled"
INTERVIEW_STATUS_RESCHEDULED = "Rescheduled"

FEEDBACK_RATING_MIN = 1
FEEDBACK_RATING_MAX = 5

FEEDBACK_RECOMMENDATION_HIRE = "Hire"
FEEDBACK_RECOMMENDATION_NO_HIRE = "No Hire"
FEEDBACK_RECOMMENDATION_STRONG_HIRE = "Strong Hire"
FEEDBACK_RECOMMENDATION_HOLD = "Hold"

FEEDBACK_RECOMMENDATION_VALUES = [
    FEEDBACK_RECOMMENDATION_STRONG_HIRE,
    FEEDBACK_RECOMMENDATION_HIRE,
    FEEDBACK_RECOMMENDATION_HOLD,
    FEEDBACK_RECOMMENDATION_NO_HIRE,
]

#: Required fields for scheduling a new Interview.
INTERVIEW_REQUIRED_FIELDS = [
    "application",
    "interview_type",
    "scheduled_on",
    "interviewers",
]

# ---------------------------------------------------------------------------
# 6. Offer Constants
# ---------------------------------------------------------------------------

OFFER_STATUS_DRAFT = "Draft"
OFFER_STATUS_SENT = "Sent"
OFFER_STATUS_ACCEPTED = "Accepted"
OFFER_STATUS_REJECTED = "Rejected"
OFFER_STATUS_EXPIRED = "Expired"
OFFER_STATUS_REVOKED = "Revoked"

ALLOWED_OFFER_STATUSES = [
    OFFER_STATUS_DRAFT,
    OFFER_STATUS_SENT,
    OFFER_STATUS_ACCEPTED,
    OFFER_STATUS_REJECTED,
    OFFER_STATUS_EXPIRED,
    OFFER_STATUS_REVOKED,
]

#: ISO 4217 currency codes supported by the platform.
SUPPORTED_CURRENCIES = [
    "EUR",
    "USD",
    "GBP",
    "CHF",
    "SEK",
    "NOK",
    "DKK",
    "PLN",
    "CZK",
]

#: Required fields for creating an Offer.
OFFER_REQUIRED_FIELDS = [
    "application",
    "position",
    "salary",
    "currency",
    "start_date",
]

# ---------------------------------------------------------------------------
# 7. File Upload Limits
# ---------------------------------------------------------------------------

#: Maximum allowed file size for candidate documents in megabytes.
MAX_FILE_SIZE_MB = 10

#: Maximum allowed file size in bytes (5MB).
MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024

#: Maximum allowed size for company logos in megabytes.
MAX_LOGO_SIZE_MB = 2

#: Allowed MIME types for candidate resume / document uploads.
ALLOWED_DOCUMENT_TYPES = [
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
]

#: Allowed MIME types for image uploads (logos, profile photos).
ALLOWED_IMAGE_TYPES = [
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/svg+xml",
    "image/webp",
]

# ---------------------------------------------------------------------------
# 8. Pagination Defaults
# ---------------------------------------------------------------------------

DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

#: Maximum number of records allowed in a single bulk operation.
BULK_OP_MAX_SIZE = 200

#: Threshold above which bulk operations are offloaded to a background job.
BULK_OP_THRESHOLD = 50

# ---------------------------------------------------------------------------
# 9. Required Fields by DocType
# ---------------------------------------------------------------------------

#: Minimum required fields for creating a Candidate record.
CANDIDATE_REQUIRED_FIELDS = [
    "first_name",
    "last_name",
    "email",
]

# Candidate Status Constants & FSM Transition Rules
CANDIDATE_STATUS_DRAFT = "Draft"
CANDIDATE_STATUS_ACTIVE = "Active"
CANDIDATE_STATUS_IN_REVIEW = "In Review"
CANDIDATE_STATUS_INTERVIEWING = "Interviewing"
CANDIDATE_STATUS_OFFERED = "Offered"
CANDIDATE_STATUS_HIRED = "Hired"
CANDIDATE_STATUS_REJECTED = "Rejected"
CANDIDATE_STATUS_ARCHIVED = "Archived"

ALLOWED_CANDIDATE_STATUSES = [
    CANDIDATE_STATUS_DRAFT,
    CANDIDATE_STATUS_ACTIVE,
    CANDIDATE_STATUS_IN_REVIEW,
    CANDIDATE_STATUS_INTERVIEWING,
    CANDIDATE_STATUS_OFFERED,
    CANDIDATE_STATUS_HIRED,
    CANDIDATE_STATUS_REJECTED,
    CANDIDATE_STATUS_ARCHIVED,
]

# Finite State Machine Transition Map for Candidate Status
CANDIDATE_STATUS_TRANSITIONS: dict[str, list[str]] = {
    CANDIDATE_STATUS_DRAFT: [CANDIDATE_STATUS_ACTIVE, CANDIDATE_STATUS_ARCHIVED],
    CANDIDATE_STATUS_ACTIVE: [
        CANDIDATE_STATUS_IN_REVIEW,
        CANDIDATE_STATUS_INTERVIEWING,
        CANDIDATE_STATUS_OFFERED,
        CANDIDATE_STATUS_HIRED,
        CANDIDATE_STATUS_REJECTED,
        CANDIDATE_STATUS_ARCHIVED,
    ],
    CANDIDATE_STATUS_IN_REVIEW: [
        CANDIDATE_STATUS_INTERVIEWING,
        CANDIDATE_STATUS_OFFERED,
        CANDIDATE_STATUS_HIRED,
        CANDIDATE_STATUS_REJECTED,
        CANDIDATE_STATUS_ARCHIVED,
    ],
    CANDIDATE_STATUS_INTERVIEWING: [
        CANDIDATE_STATUS_OFFERED,
        CANDIDATE_STATUS_HIRED,
        CANDIDATE_STATUS_REJECTED,
        CANDIDATE_STATUS_ARCHIVED,
    ],
    CANDIDATE_STATUS_OFFERED: [
        CANDIDATE_STATUS_HIRED,
        CANDIDATE_STATUS_REJECTED,
        CANDIDATE_STATUS_ARCHIVED,
    ],
    CANDIDATE_STATUS_HIRED: [CANDIDATE_STATUS_ARCHIVED],
    CANDIDATE_STATUS_REJECTED: [
        CANDIDATE_STATUS_ACTIVE,
        CANDIDATE_STATUS_IN_REVIEW,
        CANDIDATE_STATUS_ARCHIVED,
    ],
    CANDIDATE_STATUS_ARCHIVED: [CANDIDATE_STATUS_ACTIVE],
}

#: Minimum required fields for creating a Company record.
#: These mirror the ``reqd: 1`` fields in company.json:
#: company_name, email, phone, address_line_1, status.
#: (industry is enforced here as a business rule even though not reqd in schema.)
COMPANY_REQUIRED_FIELDS = [
    "company_name",
    "industry",
    "email",
    "phone",
    "address_line_1",
    "status",
]

#: Required fields for publishing a Job Opening record.
JOB_PUBLISH_REQUIRED_FIELDS = [
    "job_title",
    "company",
    "employment_type",
    "job_summary",
    "responsibilities",
    "requirements",
]

#: Minimum required fields for backward compatibility.
JOB_REQUIRED_FIELDS = JOB_PUBLISH_REQUIRED_FIELDS

#: Minimum required fields for creating a Job Application record.
APPLICATION_REQUIRED_FIELDS = [
    "job_opening",
    "candidate",
]

# ---------------------------------------------------------------------------
# 10. Miscellaneous
# ---------------------------------------------------------------------------

#: Token expiry duration for password reset links (in hours).
PASSWORD_RESET_TOKEN_EXPIRY_HOURS = 24

#: Token expiry duration for offer response links (in hours).
OFFER_TOKEN_EXPIRY_HOURS = 168  # 7 days

#: Application name for logging and metadata purposes.
APP_NAME = "recruitrain_employer"

#: Minimum password length enforced during registration and password change.
MIN_PASSWORD_LENGTH = 8

# ---------------------------------------------------------------------------
# 11. Notification Constants
# ---------------------------------------------------------------------------

NOTIFICATION_TYPE_SYSTEM = "System"
NOTIFICATION_TYPE_APPLICATION = "Application"
NOTIFICATION_TYPE_INTERVIEW = "Interview"
NOTIFICATION_TYPE_OFFER = "Offer"
NOTIFICATION_TYPE_CANDIDATE = "Candidate"
NOTIFICATION_TYPE_JOB = "Job"
NOTIFICATION_TYPE_GENERAL = "General"

ALLOWED_NOTIFICATION_TYPES = [
    NOTIFICATION_TYPE_SYSTEM,
    NOTIFICATION_TYPE_APPLICATION,
    NOTIFICATION_TYPE_INTERVIEW,
    NOTIFICATION_TYPE_OFFER,
    NOTIFICATION_TYPE_CANDIDATE,
    NOTIFICATION_TYPE_JOB,
    NOTIFICATION_TYPE_GENERAL,
]

NOTIFICATION_PRIORITY_LOW = "Low"
NOTIFICATION_PRIORITY_MEDIUM = "Medium"
NOTIFICATION_PRIORITY_HIGH = "High"
NOTIFICATION_PRIORITY_URGENT = "Urgent"

ALLOWED_NOTIFICATION_PRIORITIES = [
    NOTIFICATION_PRIORITY_LOW,
    NOTIFICATION_PRIORITY_MEDIUM,
    NOTIFICATION_PRIORITY_HIGH,
    NOTIFICATION_PRIORITY_URGENT,
]

DEFAULT_NOTIFICATION_PREFERENCES = {
    "new_application_email": True,
    "new_application_inapp": True,
    "interview_reminder_email": True,
    "interview_reminder_inapp": True,
    "offer_response_email": True,
    "offer_response_inapp": True,
    "system_alerts_email": True,
    "system_alerts_inapp": True,
}

