"""F-006 regression: package code uses relative imports and scripts run from any working directory."""

import re
import subprocess
import sys
import unittest

from .helpers import ROOT, tmp_dir


class ImportPathTests(unittest.TestCase):
    def test_package_modules_use_relative_imports(self):
        offenders = []
        for path in (ROOT / "src").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if re.search(r"^\s*(from|import)\s+src\b", text, re.M):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def run_script(self, *args):
        return subprocess.run([sys.executable, *map(str, args)], cwd=tmp_dir(), capture_output=True,
                              text=True, timeout=300)

    def test_scripts_run_from_another_directory(self):
        result = self.run_script(ROOT / "scripts" / "load_sample.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("nodes: 8", result.stdout)
        result = self.run_script(ROOT / "scripts" / "features.py", "--src", "R1", "--dst", "R8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("R1-R2-R4-R6-R8", result.stdout)

    def test_cli_errors_are_one_line_messages(self):
        result = self.run_script(ROOT / "scripts" / "features.py", "--src", "R1", "--dst", "R99")
        self.assertEqual(result.returncode, 2)
        self.assertIn("error: unknown node(s) ['R99']", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
