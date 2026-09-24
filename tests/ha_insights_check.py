"""Exercise HA services, inventory cleanup and insights against real HA, mocked LG."""
import asyncio
from datetime import timedelta
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.exceptions import ServiceValidationError
from custom_components.lg_thinq_extended.api import ThinQGuardedApi
from custom_components.lg_thinq_extended.client.integration.homeassistant.api import _async_create_ha_bridges
from custom_components.lg_thinq_extended.coordinator import DeviceDataUpdateCoordinator
from custom_components.lg_thinq_extended.services import register_services
from custom_components.lg_thinq_extended import async_cleanup_device_registry
from custom_components.lg_thinq_extended.const import DOMAIN
from custom_components.lg_thinq_extended.entity import ThinQEntity
from homeassistant.helpers.entity import EntityDescription

async def main():
 with tempfile.TemporaryDirectory() as temp:
  hass=HomeAssistant(temp)
  hass.config_entries=SimpleNamespace(async_get_entry=lambda _:None)
  import yaml
  from homeassistant.components.script.config import SCRIPT_ENTITY_SCHEMA
  from homeassistant.components.automation.config import PLATFORM_SCHEMA
  example=yaml.safe_load((Path(__file__).resolve().parents[1]/'examples/lg_insights_package.yaml').read_text())
  for script in example['script'].values(): SCRIPT_ENTITY_SCHEMA(script)
  for automation in example['automation']: PLATFORM_SCHEMA(automation)
  fixture=json.loads((Path(__file__).parent/'fixtures/appliances.json').read_text())[0]
  api=ThinQGuardedApi(MagicMock(),'token','US','client')
  api.async_request=AsyncMock()
  api.profiles['fixture']=fixture['profile']
  api.states['fixture']=fixture['state']
  api.device_metadata['fixture']={'macAddress':'02:11:22:33:44:55'}
  api.async_get_device_profile=AsyncMock(return_value=fixture['profile'])
  api.async_get_device_energy_profile=AsyncMock(return_value={'result':{'property':['energyUsage']}})
  api.async_get_device_status=AsyncMock(return_value=fixture['state'])
  bridge=(await _async_create_ha_bridges(api,{'deviceId':'fixture','deviceInfo':{'deviceType':fixture['type'],'modelName':'test','alias':'test','reportable':True}}))[0]
  entry=SimpleNamespace(domain=DOMAIN,entry_id='entry',async_on_unload=lambda _:None,pref_disable_polling=False)
  c=DeviceDataUpdateCoordinator(hass,entry,bridge)
  entry.runtime_data=SimpleNamespace(coordinators={'fixture':c},mqtt_client=None)
  c.monitoring.store=MagicMock(async_load=AsyncMock(return_value=None),async_save=AsyncMock())
  await c.monitoring.load()
  c.data=await c._async_update_data()
  c.last_update_success=True
  entity=ThinQEntity(c,EntityDescription(key='main_current_state'),'main_current_state')
  assert ('mac','02:11:22:33:44:55') in entity.device_info['connections']
  registry=MagicMock()
  registry.async_get.return_value=SimpleNamespace(config_entry_id='entry',identifiers={(DOMAIN,'fixture')})
  with patch('custom_components.lg_thinq_extended.services.dr.async_get',return_value=registry),patch.object(hass.config_entries,'async_get_entry',return_value=entry):
   register_services(hass)
   async def call(name,**data):
    return await hass.services.async_call(DOMAIN,name,{'device_id':'ha-device',**data},blocking=True,return_response=True)
   response=await call('get_device_data')
   assert response['mac_address']=='02:11:22:33:44:55'
   await call('configure_monitoring',maintenance_interval=2,tariff_per_kwh=0.15)
   c.monitoring.history.values['main__maintenance_observed']=2
   assert c.insights.maintenance_cycles()==2
   await call('reset_maintenance')
   assert c.insights.maintenance_cycles()==0
   # Standard washer's profile must not become a guessed dry command.
   try: await call('start_laundry_mode',mode='DRYING')
   except ServiceValidationError: pass
   else: raise AssertionError('unsupported mode sent')
   api.async_request.assert_not_called()
   mode={'mode':['r','w'],'value':{'w':['DRYING'],'r':['DRYING']}}
   profile={'property':[{'location':{'locationName':'MAIN'},'mode':{'washerOperationMode':mode},'operation':{'washerOperationMode':{'mode':['w'],'value':{'w':['START']}}}}]}
   api.async_get_device_profile.return_value=profile
   api.async_get_device_status.return_value=[{'location':{'locationName':'MAIN'},'remoteControlEnable':{'remoteControlEnabled':False}}]
   try: await call('start_laundry_mode',mode='DRYING')
   except ServiceValidationError: pass
   else: raise AssertionError('unarmed device sent')
   api.async_request.assert_not_called()
   api.async_get_device_status.return_value[0]['remoteControlEnable']['remoteControlEnabled']=True
   response=await call('start_laundry_mode',mode='DRYING')
   assert response['status']=='accepted' and response['confirmed'] is False
   assert api.async_request.call_args.kwargs['json']['mode']=={'washerOperationMode':'DRYING'}
   assert c.insights.command['status']=='accepted'
   c.insights.unconfirmed()
   assert c.insights.command['status']=='accepted_unconfirmed'
   # Historical energy gaps do not create partial totals presented as complete.
   today=dt_util.now().date()
   async def usage(device,prop,period,start,end):
    if period=='MONTHLY':
     rows=[{'usedDate':today.strftime('%Y%m'),'useAmount':20}]
    else:
     rows=[{'usedDate':(today-timedelta(days=i)).strftime('%Y%m%d'),'useAmount':10} for i in range(1,31)]
    return {'result':{'property':[prop],'dataList':rows}}
   api.async_get_device_energy_usage=AsyncMock(side_effect=usage)
   await call('refresh_energy_history')
   assert c.insights.total('energyUsage',30)==300
   api.async_get_device_energy_usage.side_effect=TimeoutError()
   await call('refresh_energy_history')
   assert c.insights.total('energyUsage',30) is None
   assert len(c.insights.history['energyUsage']['daily'])==30
  # Registry removal must use confirmed inventory, scoped to this config entry.
  old=SimpleNamespace(id='old',identifiers={(DOMAIN,'gone')})
  kept=SimpleNamespace(id='kept',identifiers={(DOMAIN,'fixture')})
  api.async_get_device_list=AsyncMock(return_value=[{'deviceId':'fixture','deviceInfo':{}}])
  with patch('custom_components.lg_thinq_extended.dr.async_get',return_value=registry),patch('custom_components.lg_thinq_extended.dr.async_entries_for_config_entry',return_value=[old,kept]):
   await async_cleanup_device_registry(hass,entry,api)
   registry.async_remove_device.assert_called_once_with('old')
   registry.async_remove_device.reset_mock()
   api.async_get_device_list.return_value=[{'bad':True}]
   await async_cleanup_device_registry(hass,entry,api)
   registry.async_remove_device.assert_not_called()
  await c.monitoring.close()
  await hass.async_stop()
  print('HA services, mode permissions, command outcomes, history errors, MAC registry and removal checks passed')

asyncio.run(main())
