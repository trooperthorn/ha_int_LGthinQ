"""Run in CI with real Home Assistant; all appliance calls are mocked."""
import asyncio
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from homeassistant.core import HomeAssistant
from custom_components.lg_thinq_extended.client.integration.homeassistant.api import _async_create_ha_bridges
from custom_components.lg_thinq_extended.coordinator import DeviceDataUpdateCoordinator
from custom_components.lg_thinq_extended.monitoring import definitions, energy_definitions, MonitoringSensor, MonitoringBinarySensor
from custom_components.lg_thinq_extended.sensor import ThinQEnergySensorEntity, ENERGY_USAGE_SENSORS
from custom_components.lg_thinq_extended.client import ThinQAPIException

async def main():
    with tempfile.TemporaryDirectory() as temp:
        hass = HomeAssistant(temp)
        fixtures = json.loads((Path(__file__).parent/'fixtures/appliances.json').read_text())
        for fixture in fixtures[:4]:
            api = SimpleNamespace(async_get_device_profile=AsyncMock(return_value=fixture['profile']),
                async_get_device_energy_profile=AsyncMock(return_value={"result": {"property": ["energyUsage"]}}),
                async_get_device_status=AsyncMock(return_value=fixture['state']))
            bridge = (await _async_create_ha_bridges(api, {'deviceId': 'fixture', 'deviceInfo': {
                'deviceType': fixture['type'], 'modelName': 'fixture', 'alias': 'Fixture', 'reportable': True}}))[0]
            entry = SimpleNamespace(entry_id='fixture', async_on_unload=lambda fn: None, pref_disable_polling=False)
            coordinator = DeviceDataUpdateCoordinator(hass, entry, bridge)
            coordinator.monitoring.store = MagicMock(async_load=AsyncMock(return_value=None), async_save=AsyncMock())
            await coordinator.monitoring.load()
            coordinator.data = await coordinator._async_update_data()
            sensors, binaries = definitions(coordinator)
            energy_sensors, energy_binaries = energy_definitions(coordinator)
            entities = [MonitoringSensor(coordinator, m) for m in sensors + energy_sensors]
            entities += [MonitoringBinarySensor(coordinator, m) for m in binaries + energy_binaries]
            assert len({e.unique_id for e in entities}) == len(entities)
            for e in entities:
                value = e.native_value if isinstance(e, MonitoringSensor) else e.is_on
                assert e.name
            detergent = [e for e in entities if 'detergent_setting_reported' in e.unique_id]
            if fixture['type'] == 'DEVICE_WASHER':
                assert detergent[0].native_value in {'normal', 'auto'}, detergent[0].native_value
            # Local ticks must not re-emit appliance events through coordinator listeners.
            coordinator.async_update_listeners = MagicMock()
            coordinator.monitoring.tick(__import__('homeassistant.util.dt', fromlist=['now']).now())
            coordinator.async_update_listeners.assert_not_called()
            bridge.async_get_energy_usage = AsyncMock(return_value=460.0)
            energy = ThinQEnergySensorEntity(coordinator, ENERGY_USAGE_SENSORS[0], 'energyUsage', 'today')
            energy.hass = hass
            await energy._async_update_and_schedule()
            assert energy.available and energy.native_value == 460
            energy._stop_update()
            bridge.async_get_energy_usage.side_effect = ThinQAPIException('1212', 'Not owned', {})
            await energy._async_update_and_schedule()
            assert not energy.available
            assert energy.extra_state_attributes['last_good_value'] == 460
            assert energy.extra_state_attributes['error'] == '1212'
            energy._stop_update()
            await coordinator.monitoring.close()
            print(fixture['type'], 'monitoring entities:', len(entities), 'OK')
        await hass.async_stop()

asyncio.run(main())
