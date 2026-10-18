"""ReAct-style planner orchestrating underwriting data, SOPs, and cat signals.

Loop: reason (detect intents, possibly several -> fan-out; detect an
application id -> run the rules engine) -> act (run each tool, audited) ->
synthesize (cited answer + escalation tier + optional confirmation-gate
token for declines and high-value issuance). Every step is audit-logged.
"""

import re

from . import audit as audit_mod
from . import catsignal as cat_mod
from . import escalation as esc
from . import rules
from . import sop_rag
from . import text2sql
from . import views

_APP_RE = re.compile(r"\bAPP-[A-Z0-9-]+\b", re.I)
_UNDERWRITE_RE = re.compile(r"underwrite|triage|score|decision on|quote", re.I)


class PlannerAgent:
    def __init__(self, conn, sops_dir, cat_backend=None):
        self.conn = conn
        self.audit = audit_mod.AuditLog()
        self.gate = esc.ConfirmationGate()
        self.sops = sop_rag.SopIndex(sop_rag.load_chunks(sops_dir))
        self.cat = cat_backend or cat_mod.FakeCatSignal()

    def _territory_loss(self, territory):
        row = self.conn.execute(
            "SELECT loss_ratio FROM territories WHERE territory = ?",
            (territory,)).fetchone()
        return row[0] if row else 0.0

    # -- tool-facing helpers -------------------------------------------------
    def _tool_sql(self, intent):
        result = text2sql.run(self.conn, intent)
        self.audit.record("planner", "tool.sql", {
            "intent": intent, "rows": len(result["rows"]),
        })
        return result

    def _tool_underwrite(self, app_id):
        row = self.conn.execute(
            "SELECT * FROM applications WHERE app_id = ?", (app_id,)).fetchone()
        if row is None:
            self.audit.record("planner", "tool.underwrite.miss",
                              {"app_id": app_id})
            return None
        app = dict(row)
        ctx = {
            "loss_ratio": self._territory_loss(app["territory"]),
            "cat_risk": ("high" if self.cat.get_signal(
                app["territory"]).get("band") == "high" else "low"),
        }
        result = rules.evaluate(app, ctx)
        self.audit.record("planner", "tool.underwrite", {
            "app_id": app_id, "decision": result["decision"],
            "triggered": result["triggered"],
            "pricing_band": result["pricing_band"],
        })
        return {"app": app, "ctx": ctx, **result}

    def _tool_sop(self, question):
        answer = self.sops.answer(question)
        self.audit.record("planner", "tool.sop", {
            "found": answer["found"], "citations": answer["citations"],
        })
        return answer

    def _tool_cat(self, territory):
        signal = self.cat.get_signal(territory)
        self.audit.record("planner", "tool.catsignal", {
            "territory": territory, "ok": signal.get("ok"),
            "band": signal.get("band"),
        })
        return signal

    # -- main entry point ----------------------------------------------------
    def ask(self, question):
        self.audit.record("planner", "question_received", {"question": question})
        intents = text2sql.detect_intents(question)

        sql_results = {}
        for intent in intents:  # multi-intent fan-out
            try:
                sql_results[intent] = self._tool_sql(intent)
            except text2sql.EscalationNeeded:
                self.audit.record("planner", "sql.escalated", {"intent": intent})

        uw_result = None
        app_ids = _APP_RE.findall(question)
        if app_ids or _UNDERWRITE_RE.search(question):
            target = (app_ids[0].upper() if app_ids
                      else self._top_backlog_app())
            if target:
                uw_result = self._tool_underwrite(target)

        sop_answer = self._tool_sop(question)

        cat_signal = None
        if uw_result and uw_result["app"]["line"] == "property":
            cat_signal = self._tool_cat(uw_result["app"]["territory"])

        decision = uw_result["decision"] if uw_result else None
        band = uw_result["pricing_band"] if uw_result else None
        backlog_rows = sql_results.get("backlog_by_tier", {}).get("rows", [])
        tier = esc.assess_tier(decision, band, backlog_rows)

        gate_token = self._maybe_gate(question, uw_result)

        answer, citations = self._synthesize(
            question, intents, sql_results, uw_result, sop_answer,
            cat_signal, tier, gate_token)
        self.audit.record("planner", "answer_synthesized", {
            "tier": tier, "gate_token": gate_token, "citations": citations,
        })
        return {
            "question": question,
            "intents": intents,
            "row_counts": {k: len(v["rows"]) for k, v in sql_results.items()},
            "underwriting": ({k: uw_result[k] for k in
                              ("decision", "triggered", "pricing_band",
                               "risk_score", "quoted_premium")}
                             if uw_result else None),
            "answer": answer,
            "citations": citations,
            "tier": tier,
            "gate_token": gate_token,
            "cat": cat_signal,
            "audit_events": len(self.audit.events()),
        }

    def _top_backlog_app(self):
        rows = views.run_query(
            self.conn,
            "SELECT app_id FROM v_application_backlog ORDER BY days_waiting "
            "DESC LIMIT 1")
        return rows[0]["app_id"] if rows else None

    def _maybe_gate(self, question, uw_result):
        if uw_result is None:
            return None
        if uw_result["decision"] == "decline":
            token = self.gate.request(
                "decline",
                f"Decline {uw_result['app']['app_id']} "
                f"({', '.join(uw_result['triggered']) or 'no rules'})",
                {"app_id": uw_result["app"]["app_id"],
                 "triggered": uw_result["triggered"]})
            self.audit.record("planner", "gate.requested",
                              {"token": token, "action": "decline"})
            return token
        premium = uw_result["quoted_premium"]
        if esc.ConfirmationGate.requires_gate("policy_issue", premium):
            token = self.gate.request(
                "policy_issue",
                f"Issue policy for {uw_result['app']['app_id']} "
                f"(quoted premium ${premium:,.2f})",
                {"app_id": uw_result["app"]["app_id"], "premium": premium})
            self.audit.record("planner", "gate.requested",
                              {"token": token, "action": "policy_issue"})
            return token
        return None

    def _synthesize(self, question, intents, sql_results, uw_result,
                    sop_answer, cat_signal, tier, gate_token):
        lines, citations = [], []
        if not intents and not sop_answer["found"] and not uw_result:
            return ("I couldn't map that to an underwriting question or an "
                    "underwriting SOP. Try asking about the application "
                    "backlog, referral reasons, the servicing queue, loss "
                    "ratios, renewals, or underwriting a specific "
                    "application."), []
        for intent, result in sql_results.items():
            lines.append(f"[{intent}] {len(result['rows'])} row(s) "
                         f"from governed views.")
        if uw_result:
            app = uw_result["app"]
            lines.append(
                f"Underwriting {app['app_id']} ({app['line']}, "
                f"{app['territory']}): decision "
                f"{uw_result['decision']} -- pricing band "
                f"{uw_result['pricing_band']} (score "
                f"{uw_result['risk_score']}, quoted premium "
                f"${uw_result['quoted_premium']:,.2f}).")
            if uw_result["triggered"]:
                lines.append("Triggered rules: "
                             + ", ".join(uw_result["triggered"]) + ".")
            else:
                lines.append("No referral rules fired; auto-approved by the "
                             "rules engine.")
        if sop_answer["found"]:
            lines.append(sop_answer["message"])
            for excerpt in sop_answer["excerpts"]:
                lines.append(f"- {excerpt['citation']}: {excerpt['text'][:200]}")
            citations.extend(sop_answer["citations"])
        if cat_signal:
            if cat_signal.get("ok"):
                lines.append(
                    f"Cat signal for {cat_signal['territory']}: "
                    f"{cat_signal['band']} (index {cat_signal['risk_index']}; "
                    f"{', '.join(cat_signal['drivers'])}).")
            else:
                lines.append(f"Cat-signal gap: {cat_signal.get('gap')} -- "
                             "answered without external cat data.")
        lines.append(f"Escalation tier: {tier}.")
        if gate_token:
            lines.append(
                f"High-impact action gated behind human confirmation: "
                f"{gate_token}. Approve or deny it in the demo before "
                "anything executes.")
        return "\n".join(lines), citations
