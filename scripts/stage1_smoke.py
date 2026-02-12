"""Stage 1: Smoke Test — Single API Calls

Verifies Nansen API connectivity, data shape, and rate limiter basics.
Runs the existing smoke test suite against the live API.

Prerequisites:
    export NANSEN_API_KEY=your_key

Usage:
    python scripts/stage1_smoke.py
"""

import subprocess
import sys


def main() -> int:
    print("=" * 60)
    print("STAGE 1: Smoke Test — Single API Calls")
    print("=" * 60)
    print()
    print("Running: pytest tests/test_nansen_client_smoke.py -v")
    print()

    result = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            "tests/test_nansen_client_smoke.py",
            "-v",
            "--tb=short",
        ],
        cwd="/home/jsong407/hyper-strategies-pnl-weighted",
    )

    print()
    if result.returncode == 0:
        print("STAGE 1 PASSED")
        print("  - API key works")
        print("  - All 4 endpoints return valid data")
        print("  - Pydantic model parsing handles real responses")
        print("  - Auto-pagination works")
    else:
        print("STAGE 1 FAILED — fix issues before proceeding")

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
