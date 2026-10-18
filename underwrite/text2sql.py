"""Rule-based NL -> SQL over the read-only underwriting views.

Five planner intents, each mapped to a fixed parameterized SELECT template
over the view allowlist. The gateway in views.py enforces SELECT-only,
identifier allowlist, and the LIMIT cap, so generated SQL can never escape
the sandbox.

On a database error the planner retries once with a simplified query
(``SELECT * FROM <view> LIMIT 20``) before raising EscalationNeeded.
Escalation paths never echo row data -- only the intent name is reported.
"""

import re
import sqlite3

from . import views

BACKLOG_SQL = (
    "SELECT app_id, line, territory, decision, pricing_band, risk_score, "
    "days_waiting FROM v_application_backlog "
    "ORDER BY days_waiting DESC LIMIT 50"
)
REFERRAL_SQL = (
    "SELECT app_id, line, territory, decision, pricing_band, prior_claims, "
    "coverage_amount FROM v_referral_reasons "
    "ORDER BY coverage_amount DESC LIMIT 50"
)
SERVICING_SQL = (
    "SELECT queue_type, ref_id, policy_id, detail, days_open "
    "FROM v_servicing_queue WHERE queue_type = 'endorsement' "
    "ORDER BY days_open DESC LIMIT 50"
)
LOSSRATIO_SQL = (
    "SELECT line, territory, earned_premium, incurred_losses, loss_ratio "
    "FROM v_segment_loss ORDER BY loss_ratio DESC LIMIT 50"
)
RENEWAL_SQL = (
    "SELECT queue_type, ref_id, policy_id, detail, due_day, days_open "
    "FROM v_servicing_queue WHERE queue_type = 'renewal' "
    "ORDER BY due_day ASC LIMIT 50"
)

_TEMPLATES = {
    "backlog_by_tier": ("v_application_backlog", BACKLOG_SQL),
    "referral_reasons": ("v_referral_reasons", REFERRAL_SQL),
    "servicing_queue": ("v_servicing_queue", SERVICING_SQL),
    "loss_ratio_segment": ("v_segment_loss", LOSSRATIO_SQL),
    "renewal_pipeline": ("v_servicing_queue", RENEWAL_SQL),
}

_INTENT_PATTERNS = [
    ("backlog_by_tier",
     re.compile(r"backlog|pending applications|waiting|queue of apps|by tier", re.I)),
    ("referral_reasons",
     re.compile(r"referr|why was|declined?|triage|risk tier", re.I)),
    ("servicing_queue",
     re.compile(r"endorsement|servicing|policy change|address change|vehicle add", re.I)),
    ("loss_ratio_segment",
     re.compile(r"loss ratio|loss-ratio|by segment|by territory|profitab", re.I)),
    ("renewal_pipeline",
     re.compile(r"renewal|renewing|coming due|expir", re.I)),
]


class UnknownIntent(Exception):
    """The question matched no governed intent."""


class EscalationNeeded(Exception):
    """Even the simplified retry failed; a human must take over."""


def detect_intents(question):
    """Return every matching intent name, in priority order (fan-out)."""
    return [name for name, pattern in _INTENT_PATTERNS if pattern.search(question)]


def build_sql(intent):
    """Return (sql, params) for an intent. Raises UnknownIntent for bad names."""
    if intent not in _TEMPLATES:
        raise UnknownIntent(intent)
    _view, sql = _TEMPLATES[intent]
    return sql, ()


def run(conn, intent):
    """Execute one intent with a single simplified-query retry on DB errors."""
    view, sql = _TEMPLATES[intent]
    try:
        rows = views.run_query(conn, sql)
    except sqlite3.Error:
        try:
            rows = views.run_query(conn, f"SELECT * FROM {view} LIMIT 20")
            sql = f"SELECT * FROM {view} LIMIT 20  -- simplified retry"
        except sqlite3.Error as exc:
            raise EscalationNeeded(intent) from exc
    return {"intent": intent, "sql": sql, "rows": rows}


def run_question(conn, question):
    """Detect the first intent and run it. Raises UnknownIntent when none match."""
    intents = detect_intents(question)
    if not intents:
        raise UnknownIntent(question)
    return run(conn, intents[0])
