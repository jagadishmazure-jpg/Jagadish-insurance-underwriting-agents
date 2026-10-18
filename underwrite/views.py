"""Least-privilege gateway over the underwriting telemetry database.

The planner may only issue SELECT statements against four read-only views.
Every denial cites a stable rule ID:

- SEC-SELECT-01: statement is not a SELECT (or smuggles extra statements).
- SEC-WRITE-02:  SELECT text contains a write keyword.
- SEC-VIEW-03:   query references an identifier outside the view allowlist.

String literals are stripped before scanning so that a word like 'drop'
inside a quoted value can never false-positive. Result sets are auto-capped
at MAX_LIMIT rows, and error paths never echo row data.
"""

import re

from . import telemetry as tel

MAX_LIMIT = 100

VIEW_SQL = {
    "v_application_backlog": """
        SELECT app_id, line, territory, decision, pricing_band, risk_score,
               submitted_day, (90 - submitted_day) AS days_waiting,
               prior_claims, coverage_amount
        FROM applications WHERE status = 'pending'
    """,
    "v_referral_reasons": """
        SELECT app_id, line, territory, decision, pricing_band, prior_claims,
               coverage_amount, credit_band, age_band
        FROM applications WHERE decision IN ('refer-to-underwriter', 'decline')
    """,
    "v_servicing_queue": """
        SELECT 'endorsement' AS queue_type, endo_id AS ref_id, policy_id,
               endo_type AS detail, requested_day AS due_day,
               (90 - requested_day) AS days_open, status
        FROM endorsements WHERE status = 'open'
        UNION ALL
        SELECT 'renewal' AS queue_type, policy_id AS ref_id, policy_id,
               line || ' renewal' AS detail, renewal_day AS due_day,
               (renewal_day - 90) AS days_open, status
        FROM policies WHERE renewal_day BETWEEN 90 AND 150
               AND status = 'active'
    """,
    "v_segment_loss": """
        SELECT line, territory, earned_premium, incurred_losses,
               ROUND(incurred_losses / earned_premium, 3) AS loss_ratio
        FROM segment_stats
    """,
}

_WRITE_KEYWORDS = {
    "insert", "update", "delete", "drop", "alter", "create",
    "truncate", "attach", "detach", "vacuum", "pragma", "grant", "revoke",
}
_WRITE_PHRASES = ("replace into",)

_LITERAL_RE = re.compile(r"'(?:[^']|'')*'")
_COMMENT_RE = re.compile(r"--[^\n]*")
_TOKEN_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")
_FROM_RE = re.compile(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.IGNORECASE)
_LIMIT_RE = re.compile(r"\blimit\s+(\d+)\s*;?\s*$", re.IGNORECASE)


class SecurityError(Exception):
    def __init__(self, rule_id, reason):
        super().__init__(f"[{rule_id}] {reason}")
        self.rule_id = rule_id
        self.reason = reason


def install_views(conn):
    for name, sql in VIEW_SQL.items():
        conn.execute(f"DROP VIEW IF EXISTS {name}")
        conn.execute(f"CREATE VIEW {name} AS {sql}")
    conn.commit()


def _strip_noise(sql):
    """Remove string literals and -- comments before security scanning."""
    return _COMMENT_RE.sub(" ", _LITERAL_RE.sub(" ", sql))


def check(sql):
    """Raise SecurityError (with cited rule ID) if the SQL is not allowed."""
    cleaned = _strip_noise(sql)
    if ";" in cleaned:
        raise SecurityError("SEC-SELECT-01", "multiple statements are not allowed")
    head = cleaned.lstrip(" \t\n\r(").lower()
    if not head.startswith("select"):
        raise SecurityError("SEC-SELECT-01", "only SELECT statements are permitted")
    tokens = {t.lower() for t in _TOKEN_RE.findall(cleaned)}
    lowered = cleaned.lower()
    if tokens & _WRITE_KEYWORDS or any(p in lowered for p in _WRITE_PHRASES):
        raise SecurityError("SEC-WRITE-02",
                            "write operations are denied on telemetry views")
    for ident in _FROM_RE.findall(cleaned):
        if ident.lower() not in VIEW_SQL:
            raise SecurityError(
                "SEC-VIEW-03",
                f"identifier '{ident}' is not an exposed read-only view",
            )
    return True


def _cap_limit(sql):
    sql = sql.strip().rstrip(";")
    match = _LIMIT_RE.search(sql)
    if match:
        if int(match.group(1)) > MAX_LIMIT:
            sql = _LIMIT_RE.sub(f"LIMIT {MAX_LIMIT}", sql)
        return sql
    return f"{sql} LIMIT {MAX_LIMIT}"


def run_query(conn, sql, params=()):
    """Security-checked SELECT against the allowlisted views. Returns row dicts."""
    check(sql)
    sql = _cap_limit(sql)
    cursor = conn.execute(sql, params)
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def bootstrap(conn, seed=42):
    """Convenience: seed data + install views. Used by the demo and tests."""
    tel.seed_demo_data(conn, seed=seed)
    install_views(conn)
    return conn
