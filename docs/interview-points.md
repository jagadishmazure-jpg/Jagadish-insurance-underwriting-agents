# Interview points

- **Why rules, not a model, for the decision.** Underwriting decisions must be
  explainable to regulators and applicants. An ordered rule list with a full
  trace (every rule, fired or not) is auditable; a model can rank or draft,
  but the decision of record stays traceable.
- **Fail closed on missing inputs.** The review found the original engine
  read a catastrophe-feed outage as "low risk". UW-DATA-07 makes a data gap
  a referral. Talk track: in risk selection, unknown is never the same as safe.
- **Decline outranks refer outranks approve.** One precedence rule, tested.
- **Pricing bands, not prices.** The bands (A to D) and base rates are
  synthetic; the point is a transparent mapping from score to multiplier.
- **Least-privilege data access.** Text-to-SQL is fixed templates over four
  views; a SQLite authorizer enforces the view allowlist however a table is
  spelled (ADR 0001).
- **Human gates.** Declines and high-value issuance always wait for a person.
- **Honest numbers.** 99 tests are regression checks on synthetic data, not
  claims about real underwriting quality.
