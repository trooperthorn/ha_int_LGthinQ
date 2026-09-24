"""Oven readiness and display behavior from captured state shapes."""

import importlib.util
from pathlib import Path
import sys
import types
import unittest
import client_loader


class FakeProperty:
    CURRENT_STATE = "current_state"
    REMOTE_CONTROL_ENABLED = "remote_control_enabled"


class OvenControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "custom_components/lg_thinq_extended/oven_control.py"
        spec = importlib.util.spec_from_file_location("custom_components.lg_thinq_extended.oven_control", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.module = module

    def test_idle_oven_displays_off_or_remote_ready(self):
        state = {"upper_current_state": types.SimpleNamespace(value="initial"),
                 "upper_remote_control_enabled": types.SimpleNamespace(is_on=False)}
        run, ready = self.module.oven_control_state(state, "upper")
        self.assertEqual(self.module.oven_display_state(run, ready), "off")
        self.assertFalse(self.module.oven_command_allowed(run, ready))
        state["upper_remote_control_enabled"].is_on = True
        run, ready = self.module.oven_control_state(state, "upper")
        self.assertEqual(self.module.oven_display_state(run, ready), "off_remote_ready")
        self.assertTrue(self.module.oven_command_allowed(run, ready))

    def test_running_oven_and_missing_remote_state_fail_closed(self):
        state = {"upper_current_state": types.SimpleNamespace(value="preheating")}
        run, ready = self.module.oven_control_state(state, "upper")
        self.assertFalse(ready)
        self.assertEqual(self.module.oven_display_state(run, ready), "on")
        self.assertTrue(self.module.oven_command_allowed(run, ready))
        self.assertEqual(self.module.oven_control_state(state, None), (None, False))


if __name__ == "__main__":
    unittest.main()

