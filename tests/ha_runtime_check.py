"""Real HA scheduler and MQTT list regression checks; no live LG calls."""
import asyncio,json,tempfile,threading
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,MagicMock,patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from custom_components.lg_thinq_extended.client.integration.homeassistant.api import _async_create_ha_bridges
from custom_components.lg_thinq_extended.coordinator import DeviceDataUpdateCoordinator
from custom_components.lg_thinq_extended.mqtt import ThinQMQTT

async def main():
 with tempfile.TemporaryDirectory() as temp:
  hass=HomeAssistant(temp)
  fixture=json.loads((Path(__file__).parent/'fixtures/appliances.json').read_text())[0]
  api=SimpleNamespace(async_get_device_profile=AsyncMock(return_value=fixture['profile']),
    async_get_device_energy_profile=AsyncMock(return_value=None),async_get_device_status=AsyncMock(return_value=fixture['state']),states={'test':fixture['state']})
  bridge=(await _async_create_ha_bridges(api,{'deviceId':'test','deviceInfo':{'deviceType':'DEVICE_WASHER','modelName':'test','alias':'test','reportable':True}}))[0]
  entry=SimpleNamespace(entry_id='test',async_on_unload=lambda _:None,pref_disable_polling=False)
  c=DeviceDataUpdateCoordinator(hass,entry,bridge)
  c.monitoring.store=MagicMock(async_load=AsyncMock(return_value=None),async_save=AsyncMock())
  await c.monitoring.load()
  c.data=await c._async_update_data()
  c.async_update_listeners=MagicMock()
  mqtt=ThinQMQTT(hass,api,'test',{'test':c},'test')
  report=[{'location':{'locationName':'MAIN'},'runState':{'currentState':'RUNNING'},'timer':{'remainMinute':17}}]
  await mqtt.async_handle_device_event({'event':{'pushType':'DEVICE_STATUS','deviceId':'test','deviceType':'DEVICE_WASHER','report':report}})
  assert c.data['main_current_state'].value=='running'
  assert c.data['main_remain_minute'].value==17
  assert api.states['test'][0]['timer']['remainMinute']==17
  c.async_update_listeners.assert_called()
  # Malformed list is rejected, without mutating state.
  await mqtt.async_handle_device_event({'pushType':'DEVICE_STATUS','deviceId':'test','report':[None]})
  assert c.data['main_current_state'].value=='running'
  threads=[]
  c.monitoring.listen(lambda:threads.append(threading.get_ident()))
  def fast_interval(hass,action,interval):
   return async_track_time_interval(hass,action,timedelta(milliseconds=10))
  with patch('custom_components.lg_thinq_extended.monitoring.async_track_time_interval',side_effect=fast_interval):
   c.monitoring.start()
   await asyncio.sleep(0.08)
  assert threads and set(threads)=={threading.get_ident()}, threads
  await c.monitoring.close()
  await hass.async_stop()
  print('Real HA scheduled monitor executes on event loop; location-list MQTT updates reach washer entities and cache')

asyncio.run(main())
