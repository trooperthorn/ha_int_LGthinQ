"""Check reconciliation of LG's registered-device notifications."""

import importlib.util
from pathlib import Path
import unittest


path = Path(__file__).resolve().parents[1] / "custom_components/lg_thinq_extended/device_inventory.py"
spec = importlib.util.spec_from_file_location("lg_device_inventory_test", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DeviceInventoryTests(unittest.TestCase):
    def test_add_remove_and_rename(self):
        registered = [{"deviceId": "one", "deviceInfo": {"alias": "Washer"}}]
        self.assertFalse(module.device_inventory_changed(registered, {"one": "Washer"}))
        self.assertTrue(module.device_inventory_changed(registered, {}))
        self.assertTrue(module.device_inventory_changed(registered, {"one": "Old name"}))
        self.assertTrue(module.device_inventory_changed(registered, {"one": "Washer", "two": "Oven"}))

    def test_failed_or_malformed_inventory_does_not_trigger_reload(self):
        self.assertFalse(module.device_inventory_changed(None, {"one": "Washer"}))
        self.assertFalse(module.device_inventory_changed("error", {"one": "Washer"}))
        self.assertFalse(module.device_inventory_changed([{"invalid": True}], {}))


if __name__ == "__main__":
    unittest.main()

