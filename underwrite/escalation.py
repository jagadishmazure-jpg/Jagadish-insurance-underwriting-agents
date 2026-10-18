"""Escalation tiers (T1-T4) and human confirmation gates.

Tiers mirror docs/sops/sop-02-referral-handling.md. High-impact actions --
every decline and any policy issuance above ISSUE_GATE_THRESHOLD -- are
gated: the planner mints a gate token and a human must approve/deny before
execution.
"""

ISSUE_GATE_THRESHOLD = 25000.0


def assess_tier(decision=None, pricing_band=None, backlog_rows=()):
    """Worst-case tier across the underwriting decision and backlog depth."""
    if decision == "decline":
        return "T4"
    if decision == "refer-to-underwriter" and pricing_band == "D":
        return "T3"
    if decision == "refer-to-underwriter" or len(list(backlog_rows)) >= 20:
        return "T2"
    return "T1"


class ConfirmationGate:
    """In-memory approve/deny ledger for high-impact actions."""

    def __init__(self):
        self._pending = {}
        self._decided = {}
        self._seq = 0

    @staticmethod
    def requires_gate(action_type, value=0.0):
        if action_type == "decline":
            return True
        if action_type == "policy_issue":
            return value > ISSUE_GATE_THRESHOLD
        return False

    def request(self, action_type, summary, payload=None):
        self._seq += 1
        token = f"gate-{self._seq:04d}"
        self._pending[token] = {
            "token": token,
            "action": action_type,
            "summary": summary,
            "payload": payload or {},
            "status": "pending",
        }
        return token

    def approve(self, token):
        return self._decide(token, "approved")

    def deny(self, token, reason=""):
        return self._decide(token, "denied", reason)

    def _decide(self, token, status, reason=""):
        if token not in self._pending:
            raise KeyError(f"unknown or already-decided gate token: {token}")
        record = self._pending.pop(token)
        record["status"] = status
        record["reason"] = reason
        self._decided[token] = record
        return record

    def pending(self):
        return [dict(v) for v in self._pending.values()]

    def decided(self):
        return [dict(v) for v in self._decided.values()]

    def get(self, token):
        if token in self._pending:
            return dict(self._pending[token])
        return dict(self._decided.get(token, {})) or None
