"""Run the full test suite (stdlib unittest; pytest also works if installed).

    python scripts/run_tests.py            # everything
    python scripts/run_tests.py --quick    # skip the end-to-end script test
"""

from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quick", action="store_true", help="skip tests/test_scripts_e2e.py")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    if args.quick:
        def keep(test):
            return "test_scripts_e2e" not in test.id()

        def flatten(s):
            for item in s:
                yield from (flatten(item) if isinstance(item, unittest.TestSuite) else [item])

        suite = unittest.TestSuite(t for t in flatten(suite) if keep(t))
    result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1).run(suite)
    if result.skipped:
        print("skipped:")
        for test, reason in result.skipped:
            print(f"  {test.id()}: {reason}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
