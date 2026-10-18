# Implementation guide

How an adopter would take this repo from a synthetic book of business to a
pilot. Nothing here has been run against real data.

## 1. Replace the data source
`underwrite/telemetry.py` seeds SQLite. In a pilot, point the four views in
`underwrite/views.py` at a read-only replica of the policy-admin and rating
tables. Keep the views narrow: the planner should never see raw applicant
PII, only the fields the rules read.

## 2. Encode your own rules
`underwrite/rules.py` is an ordered list of `{id, outcome, check, note}`.
Replace the six domain rules with your carrier's guidelines and keep
UW-DATA-07 last: every input a rule reads should either be present or make
the application refer. Give each rule a stable ID so traces stay comparable
across releases. Version the rule list and log the version with each decision.

## 3. Wire the catastrophe feed
`LiveCatSignal` returns an explicit gap until configured. When you connect a
provider, keep that contract: on timeout or error return `ok: False`, never a
default band. The planner already turns a gap into UW-DATA-07.

## 4. Keep humans on the hard calls
Declines and issuance above $25,000 mint a confirmation-gate token. The gate
ledger and audit log are in memory here; a pilot needs a durable store and
authenticated approvers.

## 5. Feedback
Corrections are PII-scrubbed (email, phone, SSN, long account numbers)
before they reach the audit chain. Mine them into regression cases for the
rules (see Jagadish-agent-feedback-loop for the pattern).

## 6. What to measure in a pilot
Referral rate, decline rate, override rate on referrals, the share of
UW-DATA-07 referrals (a data-quality signal), and time from application to
decision. Compare against underwriter decisions on a held-out sample before
trusting auto-approve.
