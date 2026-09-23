"""Verify model capability summaries against observed LG response shapes."""

import importlib.util
from pathlib import Path
import unittest


PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components/lg_thinq_extended/capability_inventory.py"
)
SPEC = importlib.util.spec_from_file_location("lg_capability_inventory", PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CapabilityTests(unittest.TestCase):
    def test_oven_read_write_constraints_and_unsupported_energy(self) -> None:
        profile = {"response": {
            "property": [{
                "location": {"locationName": "UPPER"},
                "temperature": [
                    {"unit": "F", "targetTemperature": {
                        "type": "range", "mode": ["r", "w"],
                        "value": {"r": {"min": 170, "max": 550},
                                  "w": {"min": 170, "max": 550}},
                    }},
                ],
                "timer": {"remainHour": {"type": "number", "mode": ["r"]}},
            }],
            "notification": {"push": ["COOKING_IS_COMPLETE"]},
        }}
        state = {"response": [{"runState": {"currentState": "PREHEATING"},
                               "temperature": {"targetTemperature": 350}}]}
        result = MODULE.summarize_capabilities(
            profile, state, {"error_code": "1221"}
        )
        temp = next(p for p in result["properties"] if "targetTemperature" in p["path"])
        self.assertEqual(temp["path"], "property[0].temperature[F].targetTemperature")
        self.assertTrue(temp["readable"])
        self.assertTrue(temp["writable"])
        self.assertEqual(temp["write_constraints"]["max"], 550)
        self.assertEqual(result["energy_status"], "unsupported")
        self.assertIn("runState.currentState", result["observed_state_paths"])
        self.assertNotIn("PREHEATING", str(result["observed_state_paths"]))

    def test_laundry_notification_and_energy_property(self) -> None:
        profile = {"response": {
            "property": [{"operation": {"washerOperationMode": {
                "type": "enum", "mode": ["w"],
                "value": {"w": ["START", "STOP"]},
            }}}],
            "notification": {"push": ["DRYING_IS_COMPLETE", "WASHING_IS_COMPLETE"]},
        }}
        result = MODULE.summarize_capabilities(
            profile,
            {"response": [{"runState": {"currentState": "DRYING"}}]},
            {"response": {"result": {"property": ["energyUsage"]}}},
        )
        self.assertEqual(result["energy_status"], "available")
        self.assertEqual(result["energy_properties"], ["energyUsage"])
        self.assertIn("DRYING_IS_COMPLETE", result["notifications"])
        self.assertFalse(result["properties"][0]["readable"])
        self.assertTrue(result["properties"][0]["writable"])


if __name__ == "__main__":
    unittest.main()

