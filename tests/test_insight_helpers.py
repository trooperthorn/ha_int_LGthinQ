"""Profile boundaries, history coverage, and MAC identity regression tests."""
import unittest
from datetime import date, timedelta
import client_loader
from custom_components.lg_thinq_extended.insight_helpers import (
    reported_mac, energy_records, rolling, combo_start_payload, merge_report, payload_confirmed)


class InsightTests(unittest.TestCase):
    def test_mac_requires_explicit_valid_unique_unicast_identity(self):
        self.assertEqual(reported_mac({"macAddress": "02-11-22-33-44-55"}), "02:11:22:33:44:55")
        for info in ({"deviceId": "021122334455"}, {"mac": "ff:ff:ff:ff:ff:ff"},
                     {"mac": "00:00:00:00:00:00"}, {"mac": "03:11:22:33:44:55"},
                     {"mac": "garbage"}, {"mac": "021122334455", "macAddress": "021122334456"}):
            self.assertIsNone(reported_mac(info))

    def test_energy_requires_every_completed_day(self):
        today = date(2026, 9, 24)
        records = {(today-timedelta(days=i)).strftime("%Y%m%d"): i for i in range(1,31)}
        records[today.strftime("%Y%m%d")] = 1000
        self.assertEqual(rolling(records, today, 7), 28)
        del records['20260922']
        self.assertIsNone(rolling(records, today, 7))

    def test_energy_dates_and_alias_amount(self):
        response = {"result": {"property": ["energyUsage"], "dataList": [{"usedDate": "20260923", "useAmount": 12}]}}
        self.assertEqual(energy_records(response, "energyUsage", "DAILY"), {"20260923": 12})
        response['result']['dataList'] *= 2
        with self.assertRaises(ValueError): energy_records(response, "energyUsage", "DAILY")

    def test_mode_aliases_and_permissions(self):
        for key in ('washerMode', 'washerOperationMode'):
            profile = {"property": [{"location": {"locationName": "MAIN"}, "mode": {
                key: {"mode": ["r", "w"], "value": {"w": ["DRYING"]}}},
                "operation": {"washerOperationMode": {"mode": ["w"], "value": {"w": ["START"]}}}}]}
            payload = combo_start_payload(profile, 'DRYING')
            self.assertEqual(payload['mode'], {key: 'DRYING'})
            self.assertEqual(payload['operation']['washerOperationMode'], 'START')
            with self.assertRaises(ValueError): combo_start_payload(profile, 'WASHING')
            profile['property'][0]['mode'][key]['mode'] = ['r']
            with self.assertRaises(ValueError): combo_start_payload(profile, 'DRYING')
        with self.assertRaises(ValueError): combo_start_payload({}, 'DRYING')

    def test_partial_state_does_not_confirm_write_only_operation(self):
        self.assertFalse(payload_confirmed({'operation': {'washerOperationMode': 'START'}}, {'runState': {'currentState': 'RUNNING'}}))
        self.assertTrue(payload_confirmed({'refrigeration': {'expressMode': True}}, {'refrigeration': {'expressMode': True}}))
        state = [{'location': {'locationName': 'MAIN'}, 'timer': {'remainHour': 1, 'remainMinute': 10}}]
        merged = merge_report(state, {'location': {'locationName': 'MAIN'}, 'timer': {'remainMinute': 5}})
        self.assertEqual(merged[0]['timer'], {'remainHour': 1, 'remainMinute': 5})
        self.assertEqual(state[0]['timer']['remainMinute'], 10)
