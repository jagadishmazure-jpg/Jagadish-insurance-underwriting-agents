# Endorsements (SOP-03)

Synthetic operating procedure for the demo book of business. Illustrative
only.

## What counts as an endorsement

Address changes, coverage increases, vehicle additions, and beneficiary
changes are endorsements against an active policy. They enter the
servicing queue as open items until processed.

## Coverage increases

A coverage increase that pushes total coverage above the $1M auto-approve
limit re-runs the rules engine on the policy as if it were a new
application. If any referral rule fires, the endorsement waits for an
underwriter instead of binding automatically.

## Documentation

Every endorsement records who requested it, when, and what changed. The
audit log links the endorsement to the policy and the requesting session.

## Turnaround

Open endorsements age in days in the servicing queue. Anything open more
than 14 days escalates to the servicing supervisor.
