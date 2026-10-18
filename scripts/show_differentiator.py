"""Print the rules engine on the seeded anchors (rendered into README, checked in CI)."""
import pathlib
import sqlite3

from underwrite import catsignal, views
from underwrite.orchestrator import PlannerAgent

ROOT = pathlib.Path(__file__).resolve().parent.parent
conn = sqlite3.connect(":memory:")
conn.row_factory = sqlite3.Row
views.bootstrap(conn)
for label, backend in (("fake cat feed", catsignal.FakeCatSignal()), ("live feed, not configured", catsignal.LiveCatSignal())):
    planner = PlannerAgent(conn, ROOT / "docs" / "sops", cat_backend=backend)
    print(f"-- {label}")
    for app_id in ("APP-HIGHVAL-001", "APP-DECLINE-001", "APP-CLEAN-001"):
        uw = planner._tool_underwrite(app_id)
        quote = "no quote" if uw["quoted_premium"] is None else f"${uw['quoted_premium']:,.2f}"
        print(f"  {app_id}: {uw['decision']} band {uw['pricing_band']} {quote} rules={uw['triggered']}")
