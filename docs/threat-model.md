# Threat model (STRIDE, with OWASP LLM Top 10 notes)

| Threat | Where | Control |
|---|---|---|
| **S**poofing an approver | confirmation gates | Gate tokens are minted per action; in-memory here, a pilot needs authenticated approvers (listed as Planned) |
| **T**ampering with decisions after the fact | audit log | SHA-256 hash chain; `verify_chain()` detects edits (tested) |
| **R**epudiation of a decline | rules trace | Every decision stores the full ordered trace and triggered rule IDs |
| **I**nformation disclosure: base tables or schema via SQL | gateway | Fixed templates; regex rules SEC-SELECT-01 / SEC-WRITE-02 / SEC-VIEW-03; SQLite authorizer denies any non-view read; 100-row fetch cap |
| **I**nformation disclosure: PII in feedback | feedback | `PIIScrubber` redacts email, phone, SSN and 9-12 digit account numbers before storage; only the count is kept |
| **D**enial of service: runaway queries | gateway | One statement, row cap, one retry then escalation |
| **E**levation: auto-approving on missing data | rules | UW-DATA-07 refers when territory loss history or the cat feed is missing |

OWASP LLM Top 10 notes (relevant once a model drafts answers):
- LLM01 prompt injection: the model never writes SQL or decides; it can only
  pick an intent, and the rules engine decides.
- LLM02 sensitive information disclosure: views expose rating fields only;
  feedback is scrubbed before storage.
- LLM06 excessive agency: declines and issuance are gated on a human.
