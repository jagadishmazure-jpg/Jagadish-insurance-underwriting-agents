# Insurance underwriting agents

**Recruiter summary:** End-to-end underwriting triage for a synthetic book of
business — a rules engine scores every application into auto-approve /
refer / decline with a cited rule trace, a ReAct planner answers backlog,
referral, servicing, loss-ratio, and renewal questions from governed
SQLite views, and declines plus high-value issuance wait on human
confirmation gates. 73 tests, all green; every figure below comes from a
real run of this repo.

## The problem

Underwriting is risk selection *before* a policy exists. Carriers drown in
applications while two failure modes compound: bad risks auto-approved on
thin evidence, and good applications stuck for weeks waiting on a human.
Both cost money; neither is visible until the loss ratios arrive.

## Approach

Deterministic building blocks, no model required:

- **Rules engine** (`underwrite/rules.py`) — the domain differentiator.
  Six ordered rules (`UW-COV-01`…`UW-CAT-06`) score every application into
  auto-approve / refer-to-underwriter / decline. Every decision carries a
  cited trace of which rules fired, in order, plus a pricing band (A–D).
- **Governed data access** — text-to-SQL over 4 read-only views through a
  SELECT-only gateway (`SEC-SELECT-01/02/03`), with one self-correction
  retry before escalation.
- **SOP RAG** — TF-IDF retrieval over 4 underwriting SOPs with citations;
  explicit "could not find" instead of invented policy.
- **Catastrophe signal** — fake (seeded) and live backends; the live
  backend returns an explicit gap until configured, never a hallucinated
  risk index.
- **ReAct planner** — multi-intent fan-out, T1–T4 escalation, confirmation
  gates on every decline and on issuance above $25,000.
- **Trust layer** — hash-chained audit log; user feedback is PII-scrubbed
  (email/phone/SSN/account patterns) before it is recorded.

## Outcome

Real run (`python -m pytest tests/ -q`): **73 passed**. Deterministic
anchors prove the spine: `APP-HIGHVAL-001` ($2.5M Gulf-Coast property)
refers on `UW-COV-01` + `UW-TER-03` + `UW-CAT-06`; `APP-DECLINE-001`
(4 prior claims) declines on `UW-CLM-02` behind a confirmation gate;
`APP-CLEAN-001` auto-approves into pricing band A at a quoted $495.00.

## How it works, step by step

1. `telemetry.seed_demo_data(conn, seed=42)` builds the synthetic book:
   60 applications, territories, policies, endorsements, work queue,
   segment aggregates.
2. `views.install_views(conn)` exposes 4 read-only views behind the
   security gateway.
3. `PlannerAgent.ask(question)` detects intents (fan-out), optionally runs
   `rules.evaluate` on a named application, consults SOP RAG and the cat
   signal, assesses the tier, and mints confirmation gates.
4. Every step is recorded in the hash-chained `AuditLog`.

```python
from underwrite import telemetry, views, orchestrator
conn = telemetry.connect()
views.bootstrap(conn, seed=42)
planner = orchestrator.PlannerAgent(conn, "docs/sops")
result = planner.ask("Underwrite APP-HIGHVAL-001")
print(result["underwriting"]["decision"])   # refer-to-underwriter
print(result["underwriting"]["triggered"])  # ['UW-COV-01', 'UW-TER-03', 'UW-CAT-06']
```

## Module map

| Module | What it does |
|---|---|
| `underwrite/telemetry.py` | Seeded SQLite book: applications, policies, endorsements, work queue, segments |
| `underwrite/rules.py` | **Differentiator:** ordered rules engine, cited trace, pricing bands, quotes |
| `underwrite/views.py` | 4 read-only views + SELECT-only gateway (`SEC-*` rule IDs) |
| `underwrite/text2sql.py` | 5 intents → fixed SELECT templates + one retry |
| `underwrite/sop_rag.py` | TF-IDF SOP retrieval with citations |
| `underwrite/catsignal.py` | Fake/live catastrophe signal with explicit gaps |
| `underwrite/orchestrator.py` | ReAct planner: fan-out, tiering, gates, synthesis |
| `underwrite/escalation.py` | T1–T4 tiers + human confirmation gates |
| `underwrite/audit.py` | SHA-256 hash-chained audit log |
| `underwrite/feedback.py` | Thumbs/corrections, PII-scrubbed, audit-linked |
| `underwrite/pii.py` | Email/phone/SSN/account-number scrubber |
| `underwrite/demo_helpers.py` | Stdlib demo logic (fully tested) |

## How this differs from coldchain/retail

The skeleton (governed views, SOP RAG, audit chain, gates) is shared on
purpose — it is the enterprise spine. What is **only** here:

- The **rules engine with referral tiers**: no sibling repo scores
  decisions through cited, ordered underwriting rules with a pricing band.
  Coldchain triages telemetry anomalies; retail triages stock and returns;
  this repo triages *risk selection itself*.
- **Pre-policy lifecycle**: applications, quotes, and issuance — the other
  repos operate on things that already exist (shipments, inventory,
  policies in force).
- **Catastrophe signal** as a first-class underwriting input with
  fake/live backends and gap behavior.

## Boundary with Jagadish-insurance-claims-agents

`Jagadish-insurance-claims-agents` covers **post-loss claims**: FNOL
intake, document extraction, fraud scoring, settlement, payout. This repo
covers **pre-policy risk selection and servicing**: application triage,
rules-engine decisions, endorsements, renewals — the other end of the
policy lifecycle. The two share vocabulary (loss ratios feed underwriting)
but never the same workflow; see that repo for anything after a loss
occurs: https://github.com/jagadishmazure-jpg/Jagadish-insurance-claims-agents

## Guardrails and security controls

- SELECT-only gateway with cited rule IDs; string literals stripped before
  scanning; result caps; error paths never echo row data.
- All declines and issuance above $25,000 need human confirmation.
- Feedback free text is PII-scrubbed before storage; only redaction counts
  are kept.
- Deterministic, seeded, stdlib-only: no network, no model calls.

## Limitations and known failures

- The rules engine is illustrative, not actuarial: six hand-written rules
  and synthetic base rates, not a real risk model.
- The live cat-signal backend is a documented stub (returns a gap).
- TF-IDF retrieval is keyword-based; paraphrased SOP questions can miss.
- The audit log and gate ledger are in-memory (no persistence across
  restarts).

## Built / Written-not-run / Planned

| Item | Status |
|---|---|
| Rules engine with referral tiers + cited trace | Built |
| Text-to-SQL over 4 governed views (5 intents) | Built |
| SOP RAG with citations + explicit not-found | Built |
| Fake/live cat signal with gap behavior | Built |
| ReAct planner, T1–T4 tiers, confirmation gates | Built |
| Hash-chained audit + PII-scrubbed feedback | Built |
| Thin Streamlit demo | Built (needs `pip install streamlit` to run) |
| Live cat-model provider integration | Planned |
| Persistent audit store | Planned |
| CI workflow | Written-not-run (`.github/workflows/ci.yml` ships with the repo; enable on push) |

## Demo

```bash
pip install streamlit
streamlit run demo/app.py
```

## Knowledge

- [knowledge/domain-notes.md](knowledge/domain-notes.md) — underwriting
  triage, referral tiers, pricing bands, servicing.
- [knowledge/architecture.md](knowledge/architecture.md) — Mermaid
  architecture diagram.

## Disclaimer

All data is synthetic and fictional, generated deterministically for
demonstration. No real applicants, policies, or carriers are represented.
This is an independent portfolio project, unaffiliated with any insurer.
