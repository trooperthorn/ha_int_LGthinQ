import unittest
import client_loader
from custom_components.lg_thinq_extended.client.energy import energy_total
from custom_components.lg_thinq_extended.client import ThinQAPIException

class EnergyDataTests(unittest.TestCase):
    def test_deployed_and_documented_amount_shapes(self):
        self.assertEqual(energy_total({"result": {"dataList": [{"energyUsage": 1328}]}}, "energyUsage"), 1328)
        self.assertEqual(energy_total({"result": {"property": ["energyUsage"], "dataList": [{"useAmount": 1328}]}}, "energyUsage"), 1328)
        self.assertEqual(energy_total({"result": {"dataList": [{"energyUsage": 0}]}}, "energyUsage"), 0)

    def test_absent_or_ambiguous_amount_is_not_zero(self):
        for rows in ([], [{}], [{"useAmount": 500}], [{"energyUsage": None}], [{"energyUsage": True}], [{"energyUsage": float('nan')}]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                energy_total({"result": {"dataList": rows}}, "energyUsage")

    def test_nested_vendor_error_is_preserved(self):
        with self.assertRaises(ThinQAPIException) as raised:
            energy_total({"resultCode": "1212"}, "energyUsage")
        self.assertEqual(raised.exception.code, "1212")
