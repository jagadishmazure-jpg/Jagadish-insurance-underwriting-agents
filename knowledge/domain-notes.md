# Underwriting domain notes

Distilled notes on insurance underwriting operations, written for this
repo's demo. All figures are illustrative and synthetic.

## What underwriting is

Underwriting is risk selection *before* a policy exists: deciding which
applications to accept, at what price, and with what terms. It is the
mirror image of claims, which handles losses *after* they happen. The
two functions share data (loss history feeds underwriting models) but
have opposite jobs.

## The triage problem

A carrier receives far more applications than underwriters can read.
Straight-through processing (auto-approve) handles the clean majority;
the rules engine exists to route the risky minority to humans with the
reasons attached. The failure modes are symmetric: auto-approving a bad
risk loses money for years, while referring everything burns underwriter
capacity and slows growth.

## Referral tiers

- **Auto-approve**: no rule fired. Bind immediately.
- **Refer**: a rule fired but the risk may still be acceptable with
  judgment (high limit, tough territory, young operator, weak credit,
  cat exposure). Goes to the work queue with a cited trace.
- **Decline**: hard stop (e.g. 3+ prior claims). Still gated behind a
  human confirmation, because a decline communicated in error is a
  regulatory event.

## Pricing bands

Bands A-D translate a risk score into a rate multiplier (0.90 / 1.00 /
1.25 / 1.60 on illustrative base rates). The band is advisory; the
underwriter of record sets the final rate. Bands keep pricing
explainable: a customer asking "why is my premium higher" gets the band
and the triggered rules, not a black box.

## Servicing and renewals

After issue, the policy lives in servicing: endorsements (address,
coverage, vehicle, beneficiary changes) and the renewal cycle. A renewal
re-scores the risk; deteriorated segments go back to manual review. This
repo covers servicing; first-notice-of-loss and payouts belong to the
claims side.

## Where the agent helps

The planner answers operational questions (backlog, referrals, loss
ratios, renewals) from governed data, runs the rules engine on demand
with a visible trace, and never issues or declines without a human gate.
