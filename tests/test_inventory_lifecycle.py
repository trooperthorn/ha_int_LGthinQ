"""Inventory lifecycle regression tests without a running HA instance."""
import ast
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from test_device_inventory import module

source=Path(__file__).resolve().parents[1]/'custom_components/lg_thinq_extended/mqtt.py'
class APIError(Exception):
    def __init__(self,code): self.code=code
node=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.ClassDef))
ns=dict(parse_device_inventory=module.parse_device_inventory, DOMAIN="lg_thinq_extended", asyncio=asyncio,monotonic=lambda:100,device_inventory_changed=module.device_inventory_changed,
        ThinQAPIException=APIError,ClientError=ConnectionError,
        ThinQAPIErrorCodes=SimpleNamespace(ALREADY_SUBSCRIBED_PUSH='1207'),
        DEVICE_STATUS_MESSAGE='DEVICE_STATUS',DEVICE_PUSH_MESSAGE='DEVICE_PUSH',
        DeviceType=SimpleNamespace(WASHTOWER='DEVICE_WASHTOWER'),_LOGGER=logging.getLogger('inventory-test'))
exec(compile('from __future__ import annotations\n'+ast.unparse(node),str(source),'exec'),ns)

class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    def client(self):
        hass=SimpleNamespace(bus=SimpleNamespace(async_fire=MagicMock()),async_create_task=asyncio.create_task,config_entries=SimpleNamespace(async_reload=AsyncMock()))
        return ns['ThinQMQTT'](hass,SimpleNamespace(async_get_device_list=AsyncMock(return_value=[])),'client',{},'entry')

    def test_partial_snapshot_cannot_remove_devices(self):
        self.assertIsNone(module.parse_device_inventory([{'deviceId':'one','deviceInfo':{}},{'invalid':True}]))
        self.assertEqual(module.parse_device_inventory([]),{})

    def test_expected_unsubscribe_codes_only_ignored_on_teardown(self):
        c=self.client()
        errors=[APIError(code) for code in ['1204','1205','1206','1213','1217']]
        self.assertEqual(c._get_failed_device_count(errors,ending=True),0)
        self.assertEqual(c._get_failed_device_count(errors),5)
        self.assertEqual(c._get_failed_device_count([APIError('1103'),TimeoutError()],ending=True),2)

    async def test_unknown_device_message_is_not_error(self):
        c=self.client()
        with patch.object(c,'_schedule_inventory_check') as schedule, patch.object(ns['_LOGGER'],'error') as error:
            await c.async_handle_device_event({'pushType':'DEVICE_STATUS','deviceId':'removed','report':{}})
            schedule.assert_called_once()
            error.assert_not_called()

    async def test_notification_during_fetch_is_not_lost(self):
        c=self.client()
        async def fetch():
            if c.thinq_api.async_get_device_list.await_count==1: c._inventory_check_pending=True
            return []
        c.thinq_api.async_get_device_list.side_effect=fetch
        c._inventory_check_pending=True
        with patch.object(asyncio,'sleep',new=AsyncMock()):
            await c._async_check_device_inventory()
        self.assertEqual(c.thinq_api.async_get_device_list.await_count,2)

    async def test_added_device_requests_reload(self):
        c=self.client()
        c.thinq_api.async_get_device_list.return_value=[{'deviceId':'new','deviceInfo':{'alias':'Combo'}}]
        c._inventory_check_pending=True
        with patch.object(asyncio,'sleep',new=AsyncMock()): await c._async_check_device_inventory()
        c.hass.config_entries.async_reload.assert_awaited_once_with('entry')
