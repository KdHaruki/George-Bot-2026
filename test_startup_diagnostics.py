import os
import unittest
from unittest.mock import patch

from main import start_gemini_diagnostics


class StartupDiagnosticsTests(unittest.TestCase):
    def test_disabled_by_default(self):
        with patch.dict(os.environ, {"GEMINI_DIAGNOSTICS": "0"}), patch("main.Thread") as thread:
            self.assertIsNone(start_gemini_diagnostics())
            thread.assert_not_called()

    def test_enabled_starts_one_background_check(self):
        with patch.dict(os.environ, {"GEMINI_DIAGNOSTICS": "1"}), patch("main.Thread") as thread:
            result = start_gemini_diagnostics()
            self.assertEqual(thread.call_args.kwargs["kwargs"], {"test": True})
            self.assertTrue(thread.call_args.kwargs["daemon"])
            result.start.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
