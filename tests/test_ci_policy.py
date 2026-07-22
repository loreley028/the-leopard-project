from __future__ import annotations

import unittest
from pathlib import Path


CI_PATH = Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"


class CiPolicyTests(unittest.TestCase):
    def test_ci_is_read_only_offline_and_token_independent(self) -> None:
        text = CI_PATH.read_text(encoding="utf-8")
        self.assertIn("contents: read", text)
        self.assertNotIn("contents: write", text)
        self.assertIn('-m "not live"', text)
        self.assertIn("-p no:cacheprovider", text)
        self.assertNotIn("LEOPARD_RUN_LIVE=1", text)
        self.assertNotIn("secrets.", text)
        self.assertNotIn("aliyun", text.lower())
        self.assertIn("validate_phase0.py", text)
        self.assertIn("validate_phase1a.py", text)
        self.assertIn("validate_phase1b0.py", text)
        self.assertIn("validate_workflow.py", text)
        self.assertIn("check_sensitive_files.py", text)
        self.assertIn("git status --porcelain", text)
        self.assertIn('PYTHONDONTWRITEBYTECODE: "1"', text)
        self.assertNotIn('-e ".[dev]"', text)


if __name__ == "__main__":
    unittest.main()
