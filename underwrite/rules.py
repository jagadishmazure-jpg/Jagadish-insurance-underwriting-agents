"""Underwriting rules engine with referral tiers.

This is the domain differentiator of the repo: every application is scored
against an ordered rule list and lands in exactly one of
``auto-approve`` / ``refer-to-underwriter`` / ``decline``. The decision
always carries a cited rule trace -- which rules fired, in evaluation
order -- so referrals and declines surface the exact triggering rules.
No silent overrides: a rule fires or it does not, and the trace proves it.

Missing inputs fail closed. The planner passes ``loss_ratio=None`` when the
territory has no loss history and ``cat_risk=None`` when the catastrophe feed
returned a gap; UW-DATA-07 then refers the application instead of letting
UW-TER-03 / UW-CAT-06 read the gap as "low risk". (A key that is simply
absent from ``ctx`` means the caller did not supply that input, which unit
tests use to exercise one rule at a time.)

Declined applications get no quoted premium.

Pricing bands (A/B/C/D) convert the risk score into a rate multiplier.
Base rates below are illustrative synthetic constants, not market rates.
"""

# Illustrative base rate per $1,000 of coverage, by line (synthetic).
BASE_RATE_PER_1K = {"property": 4.50, "auto": 6.00, "life": 2.20}

# Coverage above this auto-approve limit always routes to a human.
COVERAGE_REFERRAL_LIMIT = 1_000_000.0
# Prior claims at or above this count decline outright.
DECLINE_CLAIM_COUNT = 3
# Territory loss ratio above this routes to a human.
TERRITORY_REFERRAL_LR = 0.70


def _cov(app, ctx):
    return app["coverage_amount"] > COVERAGE_REFERRAL_LIMIT


def _clm(app, ctx):
    return app["prior_claims"] >= DECLINE_CLAIM_COUNT


def _ter(app, ctx):
    lr = ctx.get("loss_ratio")
    return lr is not None and lr > TERRITORY_REFERRAL_LR


def _yng(app, ctx):
    return app["line"] == "auto" and app["age_band"] == "16-24"


def _crd(app, ctx):
    return app["credit_band"] == "poor"


def _cat(app, ctx):
    return app["line"] == "property" and ctx.get("cat_risk") == "high"


def _data(app, ctx):
    if "loss_ratio" in ctx and ctx["loss_ratio"] is None:
        return True
    return app["line"] == "property" and "cat_risk" in ctx and ctx["cat_risk"] is None


RULES = [
    {"id": "UW-COV-01", "outcome": "refer", "check": _cov,
     "note": "coverage above the $1M auto-approve limit"},
    {"id": "UW-CLM-02", "outcome": "decline", "check": _clm,
     "note": "3+ prior claims in the lookback window"},
    {"id": "UW-TER-03", "outcome": "refer", "check": _ter,
     "note": "territory loss ratio above 0.70"},
    {"id": "UW-YNG-04", "outcome": "refer", "check": _yng,
     "note": "young-operator auto exposure"},
    {"id": "UW-CRD-05", "outcome": "refer", "check": _crd,
     "note": "poor insurance credit band"},
    {"id": "UW-CAT-06", "outcome": "refer", "check": _cat,
     "note": "property in a high catastrophe-risk territory"},
    {"id": "UW-DATA-07", "outcome": "refer", "check": _data,
     "note": "a rating input is missing (no territory loss history or cat-feed gap)"},
]


def risk_score(app, ctx=None):
    """Deterministic 0-100-ish risk score from application attributes."""
    ctx = ctx or {}
    score = 10.0
    score += min(45.0, 15.0 * app["prior_claims"])
    if (ctx.get("loss_ratio") or 0.0) > TERRITORY_REFERRAL_LR:
        score += 25.0
    if app["credit_band"] == "poor":
        score += 20.0
    elif app["credit_band"] == "fair":
        score += 10.0
    if app["line"] == "auto" and app["age_band"] == "16-24":
        score += 15.0
    if app["coverage_amount"] > 500_000:
        score += 10.0
    return round(score, 1)


def pricing_band(score):
    """Map a risk score to (band, rate multiplier)."""
    if score < 30:
        return "A", 0.90
    if score < 55:
        return "B", 1.00
    if score < 80:
        return "C", 1.25
    return "D", 1.60


def quote_premium(app, ctx=None):
    """Illustrative annual premium quote, rounded to cents (synthetic rates)."""
    score = risk_score(app, ctx)
    _band, multiplier = pricing_band(score)
    base = BASE_RATE_PER_1K[app["line"]]
    return round(base * (app["coverage_amount"] / 1000.0) * multiplier, 2)


def evaluate(app, ctx=None):
    """Score one application.

    Returns decision, ordered rule trace, triggered rule ids, risk score,
    pricing band, and multiplier. Decline outranks referral outranks
    auto-approve; the trace records every rule either way.
    """
    ctx = ctx or {}
    trace = []
    decision = "auto-approve"
    for rule in RULES:
        fired = bool(rule["check"](app, ctx))
        trace.append({"rule_id": rule["id"], "fired": fired,
                      "outcome": rule["outcome"], "note": rule["note"]})
        if fired:
            if rule["outcome"] == "decline":
                decision = "decline"
            elif decision != "decline":
                decision = "refer-to-underwriter"
    score = risk_score(app, ctx)
    band, multiplier = pricing_band(score)
    return {
        "decision": decision,
        "trace": trace,
        "triggered": [t["rule_id"] for t in trace if t["fired"]],
        "risk_score": score,
        "pricing_band": band,
        "multiplier": multiplier,
        "quoted_premium": None if decision == "decline" else quote_premium(app, ctx),
    }
