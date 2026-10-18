"""Synthetic underwriting telemetry on SQLite.

Seeded and deterministic: the same seed always produces the same book of
business. Every applicant, territory figure, and dollar amount is invented
for demonstration; nothing here is real customer data.

Tables: territories, applications, policies, endorsements, work_queue,
segment_stats.
"""

import random
import sqlite3

TERRITORIES = [
    # (territory, loss_ratio) -- GULF-COAST is the deterministic anchor:
    # elevated loss ratio, so its property applications route to referral.
    ("GULF-COAST", 0.78),
    ("MIDWEST", 0.52),
    ("NORTHEAST", 0.48),
    ("PACIFIC-NW", 0.44),
    ("SOUTHWEST", 0.55),
    ("MOUNTAIN", 0.41),
]

LINES = ("property", "auto", "life")
AGE_BANDS = ("16-24", "25-39", "40-59", "60+")
CREDIT_BANDS = ("excellent", "good", "fair", "poor")
ENDO_TYPES = ("address-change", "coverage-increase", "vehicle-add",
              "beneficiary-change")

SCHEMA = """
CREATE TABLE territories (
    territory TEXT PRIMARY KEY,
    loss_ratio REAL NOT NULL
);
CREATE TABLE applications (
    app_id TEXT PRIMARY KEY,
    line TEXT NOT NULL,
    age_band TEXT NOT NULL,
    territory TEXT NOT NULL,
    prior_claims INTEGER NOT NULL,
    coverage_amount REAL NOT NULL,
    credit_band TEXT NOT NULL,
    submitted_day INTEGER NOT NULL,
    status TEXT NOT NULL,
    decision TEXT NOT NULL,
    pricing_band TEXT NOT NULL,
    risk_score REAL NOT NULL
);
CREATE TABLE policies (
    policy_id TEXT PRIMARY KEY,
    app_id TEXT NOT NULL,
    line TEXT NOT NULL,
    premium REAL NOT NULL,
    risk_tier TEXT NOT NULL,
    issue_day INTEGER NOT NULL,
    renewal_day INTEGER NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE endorsements (
    endo_id TEXT PRIMARY KEY,
    policy_id TEXT NOT NULL,
    endo_type TEXT NOT NULL,
    status TEXT NOT NULL,
    requested_day INTEGER NOT NULL
);
CREATE TABLE work_queue (
    queue_id TEXT PRIMARY KEY,
    app_id TEXT NOT NULL,
    priority TEXT NOT NULL,
    sla_day INTEGER NOT NULL,
    assigned_to TEXT NOT NULL
);
CREATE TABLE segment_stats (
    line TEXT NOT NULL,
    territory TEXT NOT NULL,
    earned_premium REAL NOT NULL,
    incurred_losses REAL NOT NULL,
    PRIMARY KEY (line, territory)
);
"""


def connect(db_path=":memory:"):
    """Open the telemetry database (in-memory by default)."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def seed_demo_data(conn, seed=42):
    """Create the schema and load the deterministic synthetic book."""
    from .rules import evaluate  # local import: rules never imports telemetry

    rng = random.Random(seed)
    cur = conn.cursor()
    cur.executescript(SCHEMA)

    loss_by_territory = {}
    for territory, loss_ratio in TERRITORIES:
        cur.execute("INSERT INTO territories VALUES (?, ?)",
                    (territory, loss_ratio))
        loss_by_territory[territory] = loss_ratio

    applications = []

    def add_application(app_id, line, age_band, territory, prior_claims,
                        coverage_amount, credit_band, submitted_day, status):
        app = {
            "app_id": app_id, "line": line, "age_band": age_band,
            "territory": territory, "prior_claims": prior_claims,
            "coverage_amount": coverage_amount, "credit_band": credit_band,
        }
        ctx = {
            "loss_ratio": loss_by_territory[territory],
            "cat_risk": "high" if (line == "property"
                                   and territory == "GULF-COAST") else "low",
        }
        result = evaluate(app, ctx)
        row = (app_id, line, age_band, territory, prior_claims,
               coverage_amount, credit_band, submitted_day, status,
               result["decision"], result["pricing_band"],
               result["risk_score"])
        cur.execute("INSERT INTO applications VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    row)
        applications.append({"app_id": app_id, "decision": result["decision"],
                             "line": line, "status": status,
                             "pricing_band": result["pricing_band"]})
        return result

    # -- deterministic anchors -------------------------------------------------
    # High-value property application: must refer (coverage + territory rules).
    add_application("APP-HIGHVAL-001", "property", "40-59", "GULF-COAST", 0,
                    2_500_000.0, "excellent", 88, "pending")
    # Heavy prior-claims auto application: must decline.
    add_application("APP-DECLINE-001", "auto", "25-39", "MIDWEST", 4,
                    120_000.0, "fair", 86, "pending")
    # Clean life application: must auto-approve.
    add_application("APP-CLEAN-001", "life", "40-59", "NORTHEAST", 0,
                    250_000.0, "excellent", 90, "approved")

    # -- generated book ---------------------------------------------------------
    for i in range(57):
        app_id = f"APP-{1000 + i}"
        line = rng.choice(LINES)
        territory = rng.choice([t for t, _ in TERRITORIES])
        coverage = round(rng.choice([100_000, 250_000, 500_000, 750_000,
                                     1_000_000, 1_500_000])
                         * rng.uniform(0.8, 1.2), 2)
        prior_claims = rng.choices([0, 1, 2, 3], weights=[70, 18, 8, 4])[0]
        status = rng.choices(["pending", "approved", "referred", "declined"],
                             weights=[55, 25, 12, 8])[0]
        add_application(
            app_id, line, rng.choice(AGE_BANDS), territory, prior_claims,
            coverage, rng.choice(CREDIT_BANDS), rng.randint(60, 90), status,
        )

    # -- policies: issued from approved applications + a standing book ----------
    policy_n = 0

    def add_policy(app_id, line, premium, risk_tier, issue_day, renewal_day,
                   status="active"):
        nonlocal policy_n
        policy_n += 1
        cur.execute(
            "INSERT INTO policies VALUES (?,?,?,?,?,?,?,?)",
            (f"POL-{2000 + policy_n}", app_id, line, premium, risk_tier,
             issue_day, renewal_day, status),
        )
        return f"POL-{2000 + policy_n}"

    policy_ids = []
    for app in applications:
        if app["status"] == "approved" and policy_n < 26:
            premium = round(rng.uniform(800, 24000), 2)
            policy_ids.append(add_policy(
                app["app_id"], app["line"], premium, app["pricing_band"],
                rng.randint(1, 60), rng.randint(100, 220)))

    # -- endorsements ------------------------------------------------------------
    for i, pid in enumerate(policy_ids):
        if rng.random() < 0.6:
            cur.execute(
                "INSERT INTO endorsements VALUES (?,?,?,?,?)",
                (f"END-{3000 + i}", pid, rng.choice(ENDO_TYPES),
                 rng.choice(["open", "open", "closed"]),
                 rng.randint(70, 90)),
            )

    # -- underwriter work queue: pending referred/declined applications ----------
    underwriters = ["UW-AMES", "UW-BAKER", "UW-CHEN", "UW-DIAZ"]
    qn = 0
    for app in applications:
        if app["status"] == "pending" and app["decision"] in (
                "refer-to-underwriter", "decline"):
            qn += 1
            cur.execute(
                "INSERT INTO work_queue VALUES (?,?,?,?,?)",
                (f"Q-{4000 + qn}", app["app_id"],
                 "high" if app["decision"] == "decline" else "normal",
                 rng.randint(92, 97), rng.choice(underwriters)),
            )

    # -- segment aggregates (synthetic; drive the loss-ratio view) ----------------
    for line in LINES:
        for territory, base_lr in TERRITORIES:
            earned = round(rng.uniform(2_000_000, 12_000_000), 2)
            jitter = rng.uniform(0.92, 1.08)
            incurred = round(earned * base_lr * jitter, 2)
            cur.execute("INSERT INTO segment_stats VALUES (?,?,?,?)",
                        (line, territory, earned, incurred))

    conn.commit()
    return conn
