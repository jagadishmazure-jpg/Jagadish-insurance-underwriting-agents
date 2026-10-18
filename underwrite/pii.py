"""PII scrubbing for free-text fields before storage.

Email addresses, phone numbers, SSN-like patterns, and long digit runs
(account/policy numbers) are replaced with typed placeholders. The scrubber
returns the redaction count so the audit log records *that* PII was present
without ever storing the raw values.
"""

from __future__ import annotations

import re

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\(\d{3}\)\s*|\b\d{3}[-.\s]?)\d{3}[-.\s]?\d{4}\b")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
ACCT_RE = re.compile(r"\b\d{9,12}\b")


class PIIScrubber:
    """Detect and redact PII, returning (scrubbed_text, redactions)."""

    _PATTERNS = (
        ("EMAIL", EMAIL_RE),
        ("PHONE", PHONE_RE),
        ("SSN", SSN_RE),
        ("ACCOUNT_NUMBER", ACCT_RE),
    )

    def scrub(self, text):
        """Replace PII with typed placeholders; return (text, redactions)."""
        redactions = []
        out = text or ""
        for pii_type, pattern in self._PATTERNS:
            def _sub(match, pii_type=pii_type):
                placeholder = f"[REDACTED:{pii_type}:{len(redactions) + 1}]"
                redactions.append((placeholder, pii_type))
                return placeholder
            out = pattern.sub(_sub, out)
        return out, redactions
