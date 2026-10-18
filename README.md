# Insurance underwriting agents

**Recruiter summary:** End-to-end underwriting triage for a synthetic book of
business — a rules engine scores every application into auto-approve /
refer / decline with a cited rule trace, a ReAct planner answers backlog,
referral, servicing, loss-ratio, and renewal questions from governed
SQLite views, and declines plus high-value issuance wait on human
confirmation gates. 99 tests, all green; every figure below comes from a
real run of this repo.

## The problem

Underwriting is risk selection *before* a policy exists. Carriers drown in
applications while two failure modes compound: bad risks auto-approved on
thin evidence, and good applications stuck for weeks waiting on a human.
Both cost money; neither is visible until the loss ratios arrive.

## Approach

Deterministic building blocks, no model required:

- **Rules engine** (`underwrite/rules.py`) — the domain differentiator.
  Seven ordered rules (`UW-COV-01`…`UW-DATA-07`) score every application into
  auto-approve / refer-to-underwriter / decline. Every decision carries a
  cited trace of which rules fired, in order, plus a pricing band (A–D).
- **Governed data access** — text-to-SQL over 4 read-only views through a
  SELECT-only gateway (`SEC-SELECT-01, SEC-WRITE-02, SEC-VIEW-03`, backed by a SQLite authorizer), with one self-correction
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

Real run (`python -m pytest tests/ -q`): **99 passed**. Deterministic
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
| `underwrite/views.py` | 4 read-only views + SELECT-only gateway (`SEC-SELECT-01, SEC-WRITE-02, SEC-VIEW-03`) + authorizer backstop (`authz.py`) |
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
- Missing rating data fails closed: UW-DATA-07 refers instead of approving.
- Feedback free text is PII-scrubbed before storage; only redaction counts
  are kept.
- Deterministic, seeded, stdlib-only: no network, no model calls.

## Limitations and known failures

- The rules engine is illustrative, not actuarial: seven hand-written rules
  and synthetic base rates, not a real risk model.
- The live cat-signal backend is a documented stub (returns a gap).
- TF-IDF retrieval is keyword-based; paraphrased SOP questions can miss.
- The audit log and gate ledger are in-memory (no persistence across
  restarts).

## Standardization review (2026-10-18)

Reviewed against the portfolio standard after the build. Bugs found and fixed, each now pinned by a test:

1. **Rules engine failed open on missing data.** When the live catastrophe feed returned a gap, the planner turned it into `cat_risk="low"`, and a territory with no loss history became `loss_ratio=0.0`. UW-CAT-06 and UW-TER-03 then showed as "not fired" in a trace that is meant to prove what was checked, and an application could auto-approve on data nobody had. Gaps now reach the rules as `None` and a new rule, **UW-DATA-07**, refers the application. The output below shows APP-HIGHVAL-001 with the live feed unconfigured: UW-CAT-06 is replaced by UW-DATA-07 instead of silently passing.
2. **Declined applications were still quoted a premium.** `quoted_premium` is now `None` on a decline and the answer says "no quote: declined".
3. **Gateway allowlist bypass.** `check()` only looked at names written right after `FROM`/`JOIN` and whitespace, so a comma join (`FROM v_x, base_table`), a double-quoted name (`JOIN "sqlite_master"`) or a comment in place of the space (`FROM/**/base_table`) read base tables and the schema. A SQLite authorizer now refuses every read that is not an allowlisted view or done on a view's behalf (`authz.py`, ADR 0001); `/* */` comments are stripped before scanning; the 100-row cap is enforced at fetch time.

Differentiator on the seeded data (regenerated and checked by CI on every push):

<!-- run: python scripts/show_differentiator.py -->
```text
-- fake cat feed
  APP-HIGHVAL-001: refer-to-underwriter band B $11,250.00 rules=['UW-COV-01', 'UW-TER-03', 'UW-CAT-06']
  APP-DECLINE-001: decline band C no quote rules=['UW-CLM-02']
  APP-CLEAN-001: auto-approve band A $495.00 rules=[]
-- live feed, not configured
  APP-HIGHVAL-001: refer-to-underwriter band B $11,250.00 rules=['UW-COV-01', 'UW-TER-03', 'UW-DATA-07']
  APP-DECLINE-001: decline band C no quote rules=['UW-CLM-02']
  APP-CLEAN-001: auto-approve band A $495.00 rules=[]
```
<!-- /run -->

Test count (also checked by CI):

<!-- run: python scripts/count_tests.py -->
```text
99 tests collected
```
<!-- /run -->

### How to run

```bash
python -m pytest tests/ -q              # offline, stdlib only
python scripts/show_differentiator.py   # the rules engine on the seeded anchors
python scripts/check_brands.py          # hashed brand-name check (also in CI)
```

### Authorizer template sync (2026-10-18)

The SQLite authorizer was updated to the shared strict, view-aware version.
A base-table read is allowed only when SQLite reports it on behalf of one of
the allowed views (the authorizer's view-name argument). A read with no view
name is denied. `sqlite_master` is always denied, even if listed, and so is
`load_extension`. The old version falsely denied a self-join of `v_segment_loss`; a regression test covers it.
`tests/test_authorizer_sync.py` drives the authorizer directly, independent
of the text check. It covers comma joins and comment-obfuscated joins with a
base table, every view, and view self-joins.

Known residual: a read that uses no columns of a table behind a view is
allowed, because SQLite reports the unused side of a view self-join the same
way. So `SELECT count(*) FROM <that table>` or `EXISTS (SELECT 1 FROM ...)`
can still reveal a row count, but no column data. Any column reference is
denied.

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
| CI: ruff, tests, docs drift check, hashed brand check, gitleaks; CodeQL; Dependabot | Built (runs on every push) |

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

## Docs

- [docs/implementation-guide.md](docs/implementation-guide.md): from synthetic book to a pilot
- [docs/interview-points.md](docs/interview-points.md): talking points
- [docs/threat-model.md](docs/threat-model.md): STRIDE + OWASP LLM notes
- [docs/adr/0001-sqlite-authorizer-backstop.md](docs/adr/0001-sqlite-authorizer-backstop.md)

## Related repos

- [Jagadish-insurance-claims-agents](https://github.com/jagadishmazure-jpg/Jagadish-insurance-claims-agents): the post-loss end of the lifecycle (boundary above)
- [Jagadish-coldchain-logistics-agents](https://github.com/jagadishmazure-jpg/Jagadish-coldchain-logistics-agents), [Jagadish-retail-ops-agents](https://github.com/jagadishmazure-jpg/Jagadish-retail-ops-agents): same spine, other domains
- [Jagadish-fraud-detection-agents](https://github.com/jagadishmazure-jpg/Jagadish-fraud-detection-agents): explainable risk scoring in another setting

## Disclaimer

All data is synthetic and fictional, generated deterministically for
demonstration. No real applicants, policies, or carriers are represented.
This is an independent portfolio project, unaffiliated with any insurer.
