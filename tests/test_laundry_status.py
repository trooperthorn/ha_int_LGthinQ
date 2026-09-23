"""Readable laundry states for write-only operation selects."""

import importlib.util
from pathlib import Path
import sys
import types
import unittest


class LaundryStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sdk = types.ModuleType("thinqconnect")
        devices = types.ModuleType("thinqconnect.devices")
        const = types.ModuleType("thinqconnect.devices.const")
        const.Property = types.SimpleNamespace(CURRENT_STATE="current_state")
        cls.previous = {name: sys.modules.get(name) for name in (
            "thinqconnect", "thinqconnect.devices", "thinqconnect.devices.const"
        )}
        sys.modules.update({
            "thinqconnect": sdk,
            "thinqconnect.devices": devices,
            "thinqconnect.devices.const": const,
        })
        path = Path(__file__).resolve().parents[1] / "custom_components/lg_thinq_extended/laundry_status.py"
        spec = importlib.util.spec_from_file_location("lg_laundry_status_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.module = module

    @classmethod
    def tearDownClass(cls):
        for name, previous in cls.previous.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous

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


if __name__ == "__main__":
    unittest.main()

