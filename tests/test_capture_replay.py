"""Replay sanitized owner captures through the internal device mapping layer."""
import json
import unittest
from unittest.mock import AsyncMock
import client_loader
from custom_components.lg_thinq_extended.client.integration.homeassistant.api import _async_create_ha_bridges
from custom_components.lg_thinq_extended.laundry_status import laundry_remote_ready

class CapturedDeviceTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_sixteen_captured_device_conditions(self):
        fixtures=json.loads((client_loader.ROOT/'tests/fixtures/appliances.json').read_text())
        for fixture in fixtures:
            with self.subTest(run=fixture['run'],type=fixture['type'],index=fixture['index']):
                api=type('API',(),{})()
                api.async_get_device_profile=AsyncMock(return_value=fixture['profile'])
                api.async_get_device_energy_profile=AsyncMock(return_value=None)
                api.async_get_device_status=AsyncMock(return_value=fixture['state'])
                api.async_post_device_control=AsyncMock(return_value={})
                bridges=await _async_create_ha_bridges(api,{'deviceId':'fixture-device',
                    'deviceInfo':{'deviceType':fixture['type'],'modelName':'fixture','alias':'Appliance','reportable':True}})
                self.assertEqual(len(bridges),1)
                bridge=bridges[0]
                data=await bridge.fetch_data()
                self.assertTrue(data)
                if fixture['type']=='DEVICE_WASHER':
                    raw=fixture['state'][0]
                    self.assertEqual(data['main_current_state'].value,raw['runState']['currentState'].lower())
                    self.assertEqual(laundry_remote_ready(data,'main'),raw['remoteControlEnable']['remoteControlEnabled'])
                    await bridge.post('main_washer_operation_mode','stop')
                    payload=api.async_post_device_control.call_args.kwargs["payload"]
                    self.assertEqual(payload['operation']['washerOperationMode'],'STOP')
                    self.assertEqual(payload['location']['locationName'],'MAIN')
                elif fixture['type']=='DEVICE_REFRIGERATOR':
                    self.assertEqual(data['fridge_target_temperature'].value,fixture['state']['temperature'][0]['targetTemperature'])
                    await bridge.post('fridge_target_temperature',38)
                    self.assertTrue(api.async_post_device_control.called)
                else:
                    self.assertEqual(data['upper_current_state'].value,fixture['state'][0]['runState']['currentState'].lower())

