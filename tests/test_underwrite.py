"""End-to-end tests for the underwriting scaffold (deterministic, seeded)."""

import os
import sqlite3

import pytest

from underwrite import audit as audit_mod
from underwrite import catsignal as cat_mod
from underwrite import demo_helpers
from underwrite import escalation as esc
from underwrite import feedback as fb
from underwrite import orchestrator
from underwrite import pii as pii_mod
from underwrite import rules
from underwrite import sop_rag
from underwrite import telemetry as tel
from underwrite import text2sql
from underwrite import views
from underwrite.views import SecurityError

SOPS_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "docs", "sops")


@pytest.fixture()
def conn():
    c = tel.connect()
    views.bootstrap(c, seed=42)
    yield c
    c.close()


# ---------------------------------------------------------------- telemetry
def test_tables_exist(conn):
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ("territories", "applications", "policies", "endorsements",
              "work_queue", "segment_stats"):
        assert t in tables


def test_anchor_highval_refers(conn):
    row = conn.execute(
        "SELECT decision FROM applications WHERE app_id='APP-HIGHVAL-001'"
    ).fetchone()
    assert row["decision"] == "refer-to-underwriter"


def test_anchor_decline_declines(conn):
    row = conn.execute(
        "SELECT decision FROM applications WHERE app_id='APP-DECLINE-001'"
    ).fetchone()
    assert row["decision"] == "decline"


def test_anchor_clean_auto_approves(conn):
    row = conn.execute(
        "SELECT decision, pricing_band FROM applications "
        "WHERE app_id='APP-CLEAN-001'").fetchone()
    assert row["decision"] == "auto-approve"
    assert row["pricing_band"] == "A"


def test_seed_is_deterministic():
    c1 = views.bootstrap(tel.connect(), seed=42)
    c2 = views.bootstrap(tel.connect(), seed=42)
    n1 = c1.execute("SELECT COUNT(*) c FROM applications").fetchone()["c"]
    n2 = c2.execute("SELECT COUNT(*) c FROM applications").fetchone()["c"]
    assert n1 == n2 == 60
    a1 = c1.execute("SELECT app_id FROM applications ORDER BY app_id"
                    ).fetchall()
    a2 = c2.execute("SELECT app_id FROM applications ORDER BY app_id"
                    ).fetchall()
    assert [r["app_id"] for r in a1] == [r["app_id"] for r in a2]
    c1.close(); c2.close()


def test_gulf_coast_anchor_loss_ratio(conn):
    row = conn.execute(
        "SELECT loss_ratio FROM territories WHERE territory='GULF-COAST'"
    ).fetchone()
    assert row["loss_ratio"] == 0.78


# -------------------------------------------------------------------- rules
def _app(**kw):
    base = {"app_id": "T", "line": "auto", "age_band": "40-59",
            "territory": "MIDWEST", "prior_claims": 0,
            "coverage_amount": 100_000.0, "credit_band": "good"}
    base.update(kw)
    return base


def test_rules_clean_auto_approves():
    r = rules.evaluate(_app())
    assert r["decision"] == "auto-approve"
    assert r["triggered"] == []
    assert r["pricing_band"] == "A"


def test_rules_coverage_referral():
    r = rules.evaluate(_app(coverage_amount=2_000_000.0))
    assert r["decision"] == "refer-to-underwriter"
    assert "UW-COV-01" in r["triggered"]


def test_rules_claims_decline():
    r = rules.evaluate(_app(prior_claims=4))
    assert r["decision"] == "decline"
    assert "UW-CLM-02" in r["triggered"]


def test_rules_territory_referral():
    r = rules.evaluate(_app(), {"loss_ratio": 0.78})
    assert r["decision"] == "refer-to-underwriter"
    assert "UW-TER-03" in r["triggered"]


def test_rules_young_operator():
    r = rules.evaluate(_app(age_band="16-24"))
    assert "UW-YNG-04" in r["triggered"]


def test_rules_poor_credit():
    r = rules.evaluate(_app(credit_band="poor"))
    assert "UW-CRD-05" in r["triggered"]


def test_rules_cat_property():
    app = _app(line="property")
    r = rules.evaluate(app, {"cat_risk": "high"})
    assert "UW-CAT-06" in r["triggered"]


def test_rules_trace_order_is_stable():
    r = rules.evaluate(_app(prior_claims=5, coverage_amount=3_000_000.0),
                       {"loss_ratio": 0.9})
    ids = [t["rule_id"] for t in r["trace"]]
    assert ids == ["UW-COV-01", "UW-CLM-02", "UW-TER-03", "UW-YNG-04",
                   "UW-CRD-05", "UW-CAT-06"]


def test_rules_decline_outranks_refer():
    r = rules.evaluate(_app(prior_claims=4, coverage_amount=3_000_000.0))
    assert r["decision"] == "decline"
    assert "UW-COV-01" in r["triggered"] and "UW-CLM-02" in r["triggered"]


def test_rules_pricing_bands():
    assert rules.pricing_band(10) == ("A", 0.90)
    assert rules.pricing_band(45) == ("B", 1.00)
    assert rules.pricing_band(65) == ("C", 1.25)
    assert rules.pricing_band(95) == ("D", 1.60)


def test_rules_quote_rounded_to_cents():
    premium = rules.quote_premium(_app(line="life", coverage_amount=250_000.0))
    assert premium == 495.00
    assert premium == round(premium, 2)


def test_rules_deterministic():
    a = rules.evaluate(_app(coverage_amount=2_000_000.0), {"loss_ratio": 0.5})
    b = rules.evaluate(_app(coverage_amount=2_000_000.0), {"loss_ratio": 0.5})
    assert a == b


# ------------------------------------------------------- views gateway
def test_gateway_allows_select(conn):
    rows = views.run_query(conn, "SELECT app_id FROM v_application_backlog LIMIT 5")
    assert len(rows) == 5
    assert "app_id" in rows[0]


def test_gateway_denies_write_keyword():
    with pytest.raises(SecurityError) as ei:
        views.check("DELETE FROM applications")
    assert ei.value.rule_id == "SEC-SELECT-01"


def test_gateway_denies_write_inside_select():
    with pytest.raises(SecurityError) as ei:
        views.check("SELECT * FROM v_application_backlog WHERE 1=1; UPDATE x")
    assert ei.value.rule_id in ("SEC-SELECT-01", "SEC-WRITE-02")


def test_gateway_denies_unknown_view():
    with pytest.raises(SecurityError) as ei:
        views.check("SELECT * FROM applications")
    assert ei.value.rule_id == "SEC-VIEW-03"


def test_gateway_denies_multi_statement():
    with pytest.raises(SecurityError) as ei:
        views.check("SELECT * FROM v_application_backlog; SELECT 1")
    assert ei.value.rule_id == "SEC-SELECT-01"


def test_gateway_ignores_write_word_in_literal(conn):
    rows = views.run_query(
        conn, "SELECT 'drop' AS word FROM v_application_backlog LIMIT 1")
    assert rows[0]["word"] == "drop"


def test_gateway_caps_limit():
    assert views._cap_limit(
        "SELECT a FROM v_application_backlog LIMIT 5000").endswith("LIMIT 100")
    assert views._cap_limit(
        "SELECT a FROM v_application_backlog").endswith("LIMIT 100")


def test_gateway_error_hides_row_data(conn):
    with pytest.raises(SecurityError) as ei:
        views.run_query(conn, "SELECT * FROM applications")
    assert "APP-" not in str(ei.value)


# ------------------------------------------------------------------ text2sql
def test_intents_detected():
    assert "backlog_by_tier" in text2sql.detect_intents("show the backlog by tier")
    assert "referral_reasons" in text2sql.detect_intents("why was it referred?")
    assert "servicing_queue" in text2sql.detect_intents("open endorsements")
    assert "loss_ratio_segment" in text2sql.detect_intents("loss ratio by territory")
    assert "renewal_pipeline" in text2sql.detect_intents("renewals coming due")


def test_unknown_intent():
    with pytest.raises(text2sql.UnknownIntent):
        text2sql.run_question(None, "tell me a joke")


def test_build_sql_unknown():
    with pytest.raises(text2sql.UnknownIntent):
        text2sql.build_sql("nope")


def test_run_each_intent(conn):
    for intent in ("backlog_by_tier", "referral_reasons", "servicing_queue",
                   "loss_ratio_segment", "renewal_pipeline"):
        result = text2sql.run(conn, intent)
        assert result["intent"] == intent
        assert isinstance(result["rows"], list)


def test_run_question_first_intent(conn):
    result = text2sql.run_question(conn, "show the referral backlog")
    assert result["intent"] in ("backlog_by_tier", "referral_reasons")


def test_retry_then_escalate(monkeypatch, conn):
    calls = []

    def boom(conn, sql, params=()):
        calls.append(sql)
        raise sqlite3.Error("down")

    monkeypatch.setattr(views, "run_query", boom)
    with pytest.raises(text2sql.EscalationNeeded):
        text2sql.run(conn, "backlog_by_tier")
    assert len(calls) == 2  # original + one simplified retry


def test_retry_recovers(monkeypatch, conn):
    real = views.run_query
    calls = []

    def flaky(conn, sql, params=()):
        calls.append(sql)
        if len(calls) == 1:
            raise sqlite3.Error("blip")
        return real(conn, sql, params)

    monkeypatch.setattr(views, "run_query", flaky)
    result = text2sql.run(conn, "backlog_by_tier")
    assert "simplified retry" in result["sql"]
    assert isinstance(result["rows"], list)


# ------------------------------------------------------------------ sop_rag
def test_sop_chunks_load():
    chunks = sop_rag.load_chunks(SOPS_DIR)
    assert len(chunks) >= 8  # 4 docs x (overview + sections)
    assert all(c["citation"] for c in
               ({"citation": f"{c['source']} §{c['section']}"} for c in chunks))


def test_sop_retrieval_cites():
    idx = sop_rag.SopIndex(sop_rag.load_chunks(SOPS_DIR))
    ans = idx.answer("How are coverage increases handled?")
    assert ans["found"] is True
    assert any("sop-03-endorsements.md" in c for c in ans["citations"])


def test_sop_not_found_is_explicit():
    idx = sop_rag.SopIndex(sop_rag.load_chunks(SOPS_DIR))
    ans = idx.answer("quantum tunneling reinsurance treaties")
    assert ans["found"] is False
    assert "could not find" in ans["message"].lower()
    assert ans["citations"] == []


def test_sop_retrieve_sorted():
    idx = sop_rag.SopIndex(sop_rag.load_chunks(SOPS_DIR))
    hits = idx.retrieve("renewal review loss ratio", k=3)
    scores = [h["score"] for h in hits]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------- catsignal
def test_fake_cat_gulf_high():
    sig = cat_mod.FakeCatSignal().get_signal("GULF-COAST")
    assert sig["ok"] is True
    assert sig["band"] == "high"
    assert sig["risk_index"] == 82
    assert sig["drivers"]


def test_fake_cat_deterministic():
    a = cat_mod.FakeCatSignal().get_signal("MIDWEST")
    b = cat_mod.FakeCatSignal().get_signal("MIDWEST")
    assert a == b


def test_fake_cat_unknown_territory():
    sig = cat_mod.FakeCatSignal().get_signal("NOWHERE")
    assert sig["ok"] is True
    assert sig["band"] == "low"


def test_live_cat_gap_without_key():
    sig = cat_mod.LiveCatSignal().get_signal("GULF-COAST")
    assert sig["ok"] is False
    assert "gap" in sig
    assert "risk_index" not in sig  # never hallucinates


# --------------------------------------------------------------- escalation
def test_tier_decline_is_t4():
    assert esc.assess_tier(decision="decline") == "T4"


def test_tier_band_d_refer_is_t3():
    assert esc.assess_tier(decision="refer-to-underwriter",
                           pricing_band="D") == "T3"


def test_tier_routine_refer_is_t2():
    assert esc.assess_tier(decision="refer-to-underwriter",
                           pricing_band="B") == "T2"


def test_tier_deep_backlog_is_t2():
    assert esc.assess_tier(backlog_rows=[{}] * 25) == "T2"


def test_tier_quiet_is_t1():
    assert esc.assess_tier() == "T1"


def test_gate_decline_always():
    assert esc.ConfirmationGate.requires_gate("decline") is True


def test_gate_issue_threshold():
    assert esc.ConfirmationGate.requires_gate("policy_issue", 30000.0) is True
    assert esc.ConfirmationGate.requires_gate("policy_issue", 5000.0) is False


def test_gate_approve_deny_flow():
    gate = esc.ConfirmationGate()
    t1 = gate.request("decline", "decline APP-X", {"app_id": "APP-X"})
    t2 = gate.request("policy_issue", "issue", {})
    assert len(gate.pending()) == 2
    gate.approve(t1)
    gate.deny(t2, "needs review")
    assert gate.get(t1)["status"] == "approved"
    assert gate.get(t2)["status"] == "denied"
    assert gate.pending() == []
    assert len(gate.decided()) == 2


def test_gate_unknown_token():
    gate = esc.ConfirmationGate()
    with pytest.raises(KeyError):
        gate.approve("gate-9999")
    assert gate.get("gate-9999") is None


# -------------------------------------------------------------------- audit
def test_audit_chain_verifies():
    log = audit_mod.AuditLog()
    log.record("planner", "question_received", {"q": "hi"})
    log.record("planner", "tool.sql", {"rows": 3})
    assert log.verify_chain() is True
    assert [e["seq"] for e in log.events()] == [1, 2]


def test_audit_tamper_detected():
    log = audit_mod.AuditLog()
    log.record("planner", "answer_synthesized", {"tier": "T1"})
    log.events()[0]["details"]["tier"] = "T4"
    assert log.verify_chain() is False


def test_audit_prev_hash_links():
    log = audit_mod.AuditLog()
    e1 = log.record("a", "one")
    e2 = log.record("a", "two")
    assert e2["prev_hash"] == e1["hash"]


# ----------------------------------------------------------------------- pii
def test_pii_scrubs_email_phone_ssn():
    scrubber = pii_mod.PIIScrubber()
    text = ("contact jane.doe@example.com or 555-123-4567, "
            "ssn 123-45-6789, acct 987654321")
    out, redactions = scrubber.scrub(text)
    assert "[REDACTED:EMAIL:1]" in out
    assert "[REDACTED:PHONE:2]" in out
    assert "[REDACTED:SSN:3]" in out
    assert "[REDACTED:ACCOUNT_NUMBER:4]" in out
    assert "jane.doe@example.com" not in out
    assert "123-45-6789" not in out
    assert len(redactions) == 4


def test_pii_clean_text_unchanged():
    scrubber = pii_mod.PIIScrubber()
    out, redactions = scrubber.scrub("the premium looks too high")
    assert out == "the premium looks too high"
    assert redactions == []


# ------------------------------------------------------------------ feedback
def test_feedback_up_ok():
    log = audit_mod.AuditLog()
    event = fb.capture_feedback(log, session_id="s1", turn_id="t1", rating="up")
    assert event["details"]["rating"] == "up"
    assert event["details"]["pii_redactions"] == 0
    assert log.verify_chain() is True


def test_feedback_down_requires_correction():
    log = audit_mod.AuditLog()
    with pytest.raises(fb.FeedbackError):
        fb.capture_feedback(log, session_id="s1", turn_id="t1", rating="down",
                            correction="   ")


def test_feedback_bad_rating():
    log = audit_mod.AuditLog()
    with pytest.raises(fb.FeedbackError):
        fb.capture_feedback(log, session_id="s1", turn_id="t1", rating="meh")


def test_feedback_blank_session():
    log = audit_mod.AuditLog()
    with pytest.raises(fb.FeedbackError):
        fb.capture_feedback(log, session_id="  ", turn_id="t1", rating="up")


def test_feedback_scrubs_pii():
    log = audit_mod.AuditLog()
    event = fb.capture_feedback(
        log, session_id="s1", turn_id="t1", rating="down",
        correction="wrong quote, call me at 555-123-4567 or "
                   "jane.doe@example.com")
    details = event["details"]
    assert details["pii_redactions"] == 2
    assert "555-123-4567" not in details["correction"]
    assert "jane.doe@example.com" not in details["correction"]
    assert log.verify_chain() is True


def test_feedback_too_long():
    log = audit_mod.AuditLog()
    with pytest.raises(fb.FeedbackError):
        fb.capture_feedback(log, session_id="s1", turn_id="t1", rating="down",
                            correction="x" * 2001)


def test_feedback_list_and_tamper():
    log = audit_mod.AuditLog()
    fb.capture_feedback(log, session_id="s1", turn_id="t1", rating="up")
    fb.capture_feedback(log, session_id="s1", turn_id="t2", rating="down",
                        correction="too slow")
    assert len(fb.list_feedback(log)) == 2
    log.events()[0]["details"]["rating"] = "down"
    assert log.verify_chain() is False


# -------------------------------------------------------------- orchestrator
def _planner(conn, cat_backend=None):
    return orchestrator.PlannerAgent(conn, SOPS_DIR, cat_backend=cat_backend)


def test_ask_backlog(conn):
    result = _planner(conn).ask("show the application backlog by tier")
    assert "backlog_by_tier" in result["intents"]
    assert result["row_counts"]["backlog_by_tier"] > 0
    assert result["tier"] in ("T1", "T2", "T3", "T4")
    assert result["audit_events"] > 0


def test_ask_underwrite_anchor_refer(conn):
    result = _planner(conn).ask("Underwrite APP-HIGHVAL-001")
    uw = result["underwriting"]
    assert uw["decision"] == "refer-to-underwriter"
    assert "UW-COV-01" in uw["triggered"]
    assert uw["pricing_band"] == "B"
    assert result["gate_token"] is None  # refer is not gated


def test_ask_underwrite_decline_gates(conn):
    result = _planner(conn).ask("Underwrite APP-DECLINE-001")
    uw = result["underwriting"]
    assert uw["decision"] == "decline"
    assert result["gate_token"] is not None
    assert result["tier"] == "T4"


def test_ask_unknown_question_graceful(conn):
    result = _planner(conn).ask("Explain quantum chromodynamics")
    assert result["intents"] == []
    assert "couldn't map" in result["answer"]


def test_ask_multi_intent_fanout(conn):
    result = _planner(conn).ask(
        "show the referral backlog and the loss ratio by territory")
    assert len(result["intents"]) >= 2
    assert len(result["row_counts"]) >= 2


def test_ask_unknown_app_id(conn):
    result = _planner(conn).ask("Underwrite APP-NOPE-999")
    assert result["underwriting"] is None


def test_ask_cat_gap_with_live_backend(conn):
    planner = _planner(conn, cat_backend=cat_mod.LiveCatSignal())
    result = planner.ask("Underwrite APP-HIGHVAL-001")
    assert result["cat"]["ok"] is False
    assert "gap" in result["cat"]
    assert "without external cat data" in result["answer"]


def test_ask_records_audit(conn):
    planner = _planner(conn)
    before = len(planner.audit.events())
    planner.ask("loss ratio by segment")
    assert len(planner.audit.events()) > before
    assert planner.audit.verify_chain() is True


# ------------------------------------------------------------- demo_helpers
def test_format_answer(conn):
    result = _planner(conn).ask("Underwrite APP-CLEAN-001")
    text = demo_helpers.format_answer(result)
    assert "auto-approve" in text
    assert "Decision:" in text


def test_pending_gates_helpers(conn):
    planner = _planner(conn)
    planner.ask("Underwrite APP-DECLINE-001")
    gates = demo_helpers.pending_gates(planner.gate)
    assert len(gates) == 1
    payload = demo_helpers.gate_action_payload(planner.gate, gates[0]["token"])
    assert payload["action"] == "decline"
    assert demo_helpers.gate_action_payload(planner.gate, "nope") is None


def test_recent_audit_rows(conn):
    planner = _planner(conn)
    planner.ask("show the backlog")
    rows = demo_helpers.recent_audit_rows(planner.audit, n=5)
    assert len(rows) <= 5
    assert all(set(r) == {"seq", "actor", "action", "hash"} for r in rows)
    assert all(len(r["hash"]) == 12 for r in rows)
