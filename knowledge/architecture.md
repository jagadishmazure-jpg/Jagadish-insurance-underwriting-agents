# Architecture

```mermaid
flowchart TD
    subgraph DATA["Telemetry (SQLite, synthetic)"]
        T[telemetry.py<br/>applications / policies /<br/>endorsements / work_queue]
    end
    subgraph GUARD["Least-privilege access"]
        V[views.py<br/>4 read-only views<br/>SEC-SELECT-01/02/03]
    end
    subgraph BRAIN["Rules engine (differentiator)"]
        R[rules.py<br/>UW-COV-01…UW-CAT-06<br/>decision + cited trace<br/>pricing bands A–D]
    end
    subgraph TOOLS["Planner tools"]
        S[text2sql.py<br/>5 intents]
        RAG[sop_rag.py<br/>TF-IDF over 4 SOPs]
        CAT[catsignal.py<br/>fake / live backends]
    end
    subgraph PLAN["ReAct planner"]
        O[orchestrator.py<br/>fan-out → synthesize]
        E[escalation.py<br/>T1–T4 + confirmation gates]
    end
    subgraph TRUST["Trust layer"]
        A[audit.py<br/>hash-chained log]
        F[feedback.py<br/>thumbs/corrections<br/>PII-scrubbed]
    end

    T --> V --> S --> O
    T --> R --> O
    RAG --> O
    CAT --> O
    O --> E
    O --> A
    F --> A
```

## Flow

1. `telemetry.seed_demo_data` builds the synthetic book (seeded).
2. `views.install_views` exposes 4 read-only views behind the SEC-* gateway.
3. `PlannerAgent.ask` detects intents (fan-out), optionally runs
   `rules.evaluate` on a named application, consults SOP RAG and the cat
   signal, assesses the T1–T4 tier, and mints confirmation gates for
   declines and high-value issuance.
4. Every step lands in the hash-chained `AuditLog`; user feedback is
   PII-scrubbed before it is recorded.
