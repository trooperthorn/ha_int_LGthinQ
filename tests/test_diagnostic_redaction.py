"""Security behavior for user-downloadable ThinQ diagnostics."""

import importlib.util
from pathlib import Path
import unittest


PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "lg_thinq_extended"
    / "diagnostic_redaction.py"
)
SPEC = importlib.util.spec_from_file_location("lg_thinq_redaction", PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RedactionTests(unittest.TestCase):
    def test_nested_secrets_are_removed_and_device_ids_are_stable(self) -> None:
        payload = {
            "deviceId": "raw-lg-device-id",
            "deviceInfo": {
                "alias": "Private kitchen",
                "modelName": "LG_TEST_MODEL",
                "macAddress": "aa:bb:cc:dd:ee:ff",
            },
            "userList": ["person@example.com"],
            "runState": {"currentState": "RUNNING"},
        }
        safe = MODULE.redact_api_data(payload)
        self.assertEqual(safe["deviceId"], MODULE.device_ref("raw-lg-device-id"))
        self.assertEqual(safe["deviceInfo"]["alias"], "[REDACTED]")
        self.assertEqual(safe["deviceInfo"]["macAddress"], "[REDACTED]")
        self.assertEqual(safe["userList"], "[REDACTED]")
        self.assertEqual(safe["deviceInfo"]["modelName"], "LG_TEST_MODEL")
        self.assertEqual(safe["runState"]["currentState"], "RUNNING")

    def test_sensitive_scalar_strings_are_removed(self) -> None:
        self.assertEqual(
            MODULE.redact_api_data({"note": "person@example.com"})["note"],
            "[REDACTED STRING]",
        )
        self.assertEqual(
            MODULE.redact_api_data({"network": "192.168.1.8"})["network"],
            "[REDACTED STRING]",
        )

    def test_mqtt_status_log_keeps_state_without_account_ids(self) -> None:
        message = {
            "deviceId": "raw-device",
            "serviceId": "raw-service",
            "userList": ["raw-user"],
            "pushType": "DEVICE_STATUS",
            "report": [{"runState": {"currentState": "DRYING"}}],
        }
        safe = MODULE.redact_api_data(message)
        self.assertEqual(safe["deviceId"], MODULE.device_ref("raw-device"))
        self.assertEqual(safe["serviceId"], "[REDACTED]")
        self.assertEqual(safe["userList"], "[REDACTED]")
        self.assertEqual(safe["report"][0]["runState"]["currentState"], "DRYING")


if __name__ == "__main__":
    unittest.main()

