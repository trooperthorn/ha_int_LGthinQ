"""Readable laundry states for write-only operation selects."""

import importlib.util
from pathlib import Path
import sys
import types
import unittest
import client_loader


class LaundryStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "custom_components/lg_thinq_extended/laundry_status.py"
        spec = importlib.util.spec_from_file_location("custom_components.lg_thinq_extended.laundry_status", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.module = module

    def test_running_states_seen_in_captures(self):
        for raw in ("running", "rinsing", "drying", "prewash"):
            with self.subTest(raw=raw):
                data = {"washer_current_state": types.SimpleNamespace(value=raw)}
                self.assertEqual(self.module.laundry_operation_display(data, "washer"), "running")

    def test_idle_and_completed_states(self):
        for raw, expected in (("power_off", "off"), ("initial", "ready"), ("end", "finished")):
            with self.subTest(raw=raw):
                data = {"washer_current_state": types.SimpleNamespace(value=raw)}
                self.assertEqual(self.module.laundry_operation_display(data, "washer"), expected)
        self.assertIsNone(self.module.laundry_operation_display({}, "washer"))

    def test_start_requires_explicit_remote_enabled_state(self):
        for value, expected in ((True, True), (False, False), (None, False)):
            with self.subTest(value=value):
                data = {"washer_remote_control_enabled": types.SimpleNamespace(value=value)}
                self.assertIs(self.module.laundry_remote_ready(data, "washer"), expected)
        self.assertFalse(self.module.laundry_remote_ready({}, "washer"))
        self.assertFalse(self.module.laundry_remote_ready({}, None))


if __name__ == "__main__":
    unittest.main()

