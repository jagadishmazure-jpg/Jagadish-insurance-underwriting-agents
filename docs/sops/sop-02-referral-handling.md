# Referral Handling (SOP-02)

Synthetic operating procedure for the demo book of business. Illustrative
only.

## Referral tiers

Every referral lands in the underwriter work queue with a priority. High
priority is reserved for applications the engine declined or scored in
band D; normal priority covers routine referrals (coverage limit,
territory, young operator, credit band, cat exposure).

## Escalation tiers

- T1: auto-approved, no human touch.
- T2: routine referral or a deep backlog (20+ pending applications).
- T3: referral scored in pricing band D.
- T4: engine-recommended decline.

## Confirmation gates

Every decline is gated: a human must approve or deny the decline token
before it is communicated. Policy issuance with a quoted premium above
$25,000 is likewise gated. Gates are recorded in the hash-chained audit
log with their approve/deny outcome.

## SLA

High-priority queue items carry a 5-day SLA from submission; normal items
carry 10 days. Breaches page the duty underwriter.
