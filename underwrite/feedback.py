"""User-feedback capture wired into the hash-chained audit log.

A thumbs up/down plus a free-text correction is appended as a ``feedback``
audit event, so feedback inherits the log's tamper evidence and is
verifiable with :meth:`AuditLog.verify_chain` alongside every other event.

The correction is free text typed by a person, so it goes through
:class:`PIIScrubber` before it is written: emails, phone numbers, SSNs and
account numbers become placeholders and only the redaction count is stored.
Corrections longer than :data:`MAX_CORRECTION_CHARS` are rejected.
"""

from .audit import AuditLog
from .pii import PIIScrubber

RATINGS = ("up", "down")
MAX_CORRECTION_CHARS = 2000
_SCRUBBER = PIIScrubber()


class FeedbackError(ValueError):
    """Raised when a feedback submission is malformed."""


def _require_nonblank(name, value):
    if not isinstance(value, str) or not value.strip():
        raise FeedbackError(f"{name} must be a non-blank string")
    return value.strip()


def capture_feedback(audit_log, *, session_id, turn_id, rating, correction=""):
    """Append one feedback event to the audit log; returns the event.

    ``rating`` must be ``"up"`` or ``"down"``. A ``"down"`` rating requires
    a non-blank ``correction`` describing what was wrong; an ``"up"`` rating
    may omit it. ``session_id`` / ``turn_id`` link the feedback to the turn
    it refers to (supplied by the calling UI/orchestrator).
    """
    if not isinstance(audit_log, AuditLog):
        raise FeedbackError("audit_log must be an AuditLog")
    session_id = _require_nonblank("session_id", session_id)
    turn_id = _require_nonblank("turn_id", turn_id)
    if rating not in RATINGS:
        raise FeedbackError(f"rating must be one of {RATINGS}, got {rating!r}")
    correction = correction.strip() if isinstance(correction, str) else ""
    if rating == "down" and not correction:
        raise FeedbackError("a thumbs-down requires a non-blank correction")
    if len(correction) > MAX_CORRECTION_CHARS:
        raise FeedbackError(
            f"correction is longer than {MAX_CORRECTION_CHARS} characters")
    correction, redactions = _SCRUBBER.scrub(correction)
    return audit_log.record("user", "feedback", {
        "session_id": session_id,
        "turn_id": turn_id,
        "rating": rating,
        "correction": correction,
        "pii_redactions": len(redactions),
    })


def list_feedback(audit_log):
    """Return all feedback events currently in the log, in order."""
    return [e for e in audit_log.events() if e["action"] == "feedback"]
