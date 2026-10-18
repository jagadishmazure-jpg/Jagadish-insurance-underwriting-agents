"""Catastrophe/weather risk signal for property lines.

Two backends share one interface. ``FakeCatSignal`` is seeded and
deterministic, so tests and the demo never depend on the network.
``LiveCatSignal`` documents the production interface and always returns an
explicit gap until it is configured -- it never hallucinates a risk index.
"""

TERRITORY_RISK = {
    # territory: (risk_index 0-100, drivers)
    "GULF-COAST": (82, ["named-storm season", "storm-surge exposure"]),
    "MIDWEST": (41, ["convective-storm season"]),
    "NORTHEAST": (36, ["winter-storm exposure"]),
    "PACIFIC-NW": (28, ["low cat activity"]),
    "SOUTHWEST": (47, ["wildfire season", "hail exposure"]),
    "MOUNTAIN": (33, ["wildfire fringe"]),
}


class FakeCatSignal:
    """Deterministic seeded catastrophe signal (offline default)."""

    def get_signal(self, territory):
        risk_index, drivers = TERRITORY_RISK.get(territory, (30, ["unknown territory"]))
        band = ("high" if risk_index >= 70 else
                "moderate" if risk_index >= 40 else "low")
        return {
            "ok": True,
            "territory": territory,
            "risk_index": risk_index,
            "band": band,
            "drivers": list(drivers),
        }


class LiveCatSignal:
    """Production interface for a real cat-model feed (stub).

    Configure with an API key; until then every call returns an explicit
    gap dict so the planner answers without external data instead of
    inventing a risk index.
    """

    def __init__(self, api_key=None, endpoint="https://catfeed.example.invalid/v1"):
        self.api_key = api_key
        self.endpoint = endpoint

    def get_signal(self, territory):
        if not self.api_key:
            return {
                "ok": False,
                "territory": territory,
                "gap": ("live catastrophe feed not configured "
                        "(set CATSIGNAL_API_KEY); answered without cat data"),
            }
        # A real implementation would GET {endpoint}/risk?territory=...
        # with the key and parse the provider's risk index here.
        return {
            "ok": False,
            "territory": territory,
            "gap": "live backend not implemented in this scaffold",
        }
