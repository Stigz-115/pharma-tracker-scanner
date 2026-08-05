"""
PHI / PII leakage detection.

Scans third-party request URLs (query strings, paths, POST bodies) for patterns
that suggest personal or health information is being transmitted to a tracker.

This is heuristic. It flags *candidates* for human review, not confirmed
violations. Pharma sites are subject to HIPAA (where a covered entity/BA
relationship exists) and FTC Health Breach Notification rules, so any PII/PHI
reaching an ad-tech or analytics endpoint is worth surfacing.
"""

import re
from urllib.parse import urlparse, parse_qs, unquote

# Parameter names commonly carrying identifiers
SENSITIVE_PARAM_NAMES = {
    "email", "e_mail", "mail", "em", "user_email",
    "phone", "tel", "telephone", "mobile", "phone_number",
    "fname", "lname", "firstname", "lastname", "first_name", "last_name", "name", "fullname",
    "dob", "birthdate", "birthday", "date_of_birth",
    "ssn", "social",
    "address", "addr", "street", "zip", "zipcode", "postal",
    "mrn", "patient", "patient_id", "member_id", "policy",
    "diagnosis", "condition", "medication", "drug", "rx", "prescription", "indication",
    "npi", "hcp", "hin",
    "gender", "sex", "insurance",
}

# Health / condition keywords that, in a URL, hint the page topic is being leaked
HEALTH_TERMS = [
    "diabetes", "cancer", "oncology", "hiv", "aids", "depression", "anxiety",
    "psoriasis", "arthritis", "migraine", "hepatitis", "asthma", "copd",
    "alzheimer", "parkinson", "obesity", "fertility", "pregnancy", "contracept",
    "vaccine", "immuniz", "chemo", "insulin", "opioid", "adhd", "bipolar",
    "schizophren", "crohn", "colitis", "eczema", "lupus", "sclerosis",
    "erectile", "menopause", "std", "sti", "addiction", "overdose",
]

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
# hashed email (md5/sha) often used to pass email to ad platforms
HASH_RE = re.compile(r"\b[a-f0-9]{32}\b|\b[a-f0-9]{40}\b|\b[a-f0-9]{64}\b")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}(?!\d)")
SSN_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
DOB_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}[-/](?:0?[1-9]|1[0-2])[-/](?:0?[1-9]|[12]\d|3[01])(?!\d)")


def scan_url_for_phi(url: str, post_body: str = "") -> list:
    """Return a list of findings dicts for a single request."""
    findings = []
    haystack_raw = url + " " + (post_body or "")
    haystack = unquote(haystack_raw)
    low = haystack.lower()

    # 1) Regex-based content matches (most severe)
    if EMAIL_RE.search(haystack):
        findings.append({"type": "email_address", "severity": "critical",
                         "detail": "Raw email address present in request"})
    if PHONE_RE.search(haystack):
        findings.append({"type": "phone_number", "severity": "high",
                         "detail": "Phone-number pattern present in request"})
    if SSN_RE.search(haystack):
        findings.append({"type": "ssn", "severity": "critical",
                         "detail": "SSN-formatted value present in request"})
    if DOB_RE.search(haystack):
        findings.append({"type": "date_of_birth", "severity": "high",
                         "detail": "Date-of-birth pattern present in request"})

    # 2) Sensitive query-parameter names
    try:
        qs = parse_qs(urlparse(url).query)
    except Exception:
        qs = {}
    for pname, pvals in qs.items():
        pclean = pname.lower().strip()
        if pclean in SENSITIVE_PARAM_NAMES:
            val_preview = (pvals[0][:40] if pvals and pvals[0] else "")
            findings.append({"type": f"sensitive_param:{pclean}", "severity": "high",
                             "detail": f"Query param '{pname}' = '{val_preview}'"})

    # 3) Health/condition terms in URL (topic leakage)
    for term in HEALTH_TERMS:
        if term in low:
            findings.append({"type": f"health_term:{term}", "severity": "medium",
                             "detail": f"Health term '{term}' present in third-party request URL"})
            break  # one is enough to flag the request

    # 4) Hashed identifiers (common ad-tech email hashing)
    if HASH_RE.search(haystack) and any(k in low for k in ("em", "hash", "sha", "md5", "hem", "identity")):
        findings.append({"type": "hashed_identifier", "severity": "medium",
                         "detail": "Possible hashed email/identifier in request"})

    return findings
