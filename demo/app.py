"""Thin Streamlit demo for the underwriting assistant.

All logic lives in underwrite/ (via underwrite.demo_helpers); this file only
wires widgets. streamlit is imported lazily inside main() so importing this
module never breaks the stdlib test suite.

Live run:
    pip install streamlit
    streamlit run demo/app.py
"""

import os

SOPS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "docs", "sops")


def main():
    import sys

    import streamlit as st  # lazy: keeps stdlib tests dependency-free

    # `streamlit run demo/app.py` puts demo/ on sys.path; underwrite/ is one up.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from underwrite import demo_helpers, orchestrator, telemetry, views

    st.set_page_config(page_title="Underwriting Assistant", layout="wide")
    st.title("Underwriting Assistant (demo)")

    if "planner" not in st.session_state:
        conn = telemetry.connect()
        views.bootstrap(conn, seed=42)
        st.session_state.planner = orchestrator.PlannerAgent(conn, SOPS_DIR)
    planner = st.session_state.planner

    question = st.text_input(
        "Ask an underwriting question",
        "Underwrite APP-HIGHVAL-001 and show the referral backlog",
    )
    if st.button("Ask"):
        with st.spinner("Reasoning over applications, SOPs, and cat signals..."):
            result = planner.ask(question)
        st.session_state.last_result = result

    result = st.session_state.get("last_result")
    if result:
        st.subheader("Answer")
        st.text(demo_helpers.format_answer(result))
        st.caption(f"Escalation tier: {result['tier']}")

        gates = demo_helpers.pending_gates(planner.gate)
        if gates:
            st.subheader("Pending confirmations")
            for g in gates:
                col1, col2, col3 = st.columns([6, 1, 1])
                col1.write(f"{g['token']}: {g['summary']}")
                if col2.button("Approve", key=f"ap-{g['token']}"):
                    planner.gate.approve(g["token"])
                    st.rerun()
                if col3.button("Deny", key=f"dn-{g['token']}"):
                    planner.gate.deny(g["token"], "denied in demo")
                    st.rerun()

        with st.expander("Audit trail"):
            for row in demo_helpers.recent_audit_rows(planner.audit):
                st.write(f"{row['seq']:>3} {row['actor']:<8} {row['action']:<22} "
                         f"{row['hash']}")


if __name__ == "__main__":
    main()
