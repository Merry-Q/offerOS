"""Create/reset the isolated fictional OfferOS demo account."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.demo import DEMO_PASSWORD, DEMO_USERNAME, seed_demo_library


def seed() -> None:
    result = seed_demo_library(reset=True)
    print(f"Demo account ready: {DEMO_USERNAME} / {DEMO_PASSWORD}")
    print(f"Seeded jobs: {result['jobs']}")


if __name__ == "__main__":
    seed()
