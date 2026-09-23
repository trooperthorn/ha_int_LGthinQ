"""Direct request behavior, security boundaries, and LG OpenAPI contracts."""
import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock
import client_loader
from custom_components.lg_thinq_extended.client import ThinQApi, ThinQAPIException

class Response:
    def __init__(self, status=200, body=None, headers=None):
        self.status=status
        self.body=json.dumps({'response': body}) if not isinstance(body, bytes) else body.decode()
        self.headers=headers or {}
        self.closed=False
    async def text(self): return self.body
    async def __aenter__(self): return self
    async def __aexit__(self,*args): self.closed=True

class TransportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session=type('Session',(),{})()
        self.response=Response(body=[])
        self.session.request=AsyncMock(return_value=self.response)
        self.api=ThinQApi(self.session,'secret-token','US','client-test')

    async def test_regions_and_headers(self):
        await self.api.async_get_device_list()
        args,kwargs=self.session.request.call_args
        self.assertEqual(args,('GET','https://api-aic.lgthinq.com/devices'))
        self.assertEqual(kwargs['headers']['Authorization'],'Bearer secret-token')
        self.assertFalse(kwargs['allow_redirects'])
        self.assertTrue(self.response.closed)
        first=kwargs['headers']['x-message-id']
        await self.api.async_get_route()
        self.assertNotEqual(first,self.session.request.call_args.kwargs['headers']['x-message-id'])
        for country,region in [('KR','kic'),('DE','eic')]:
            api=ThinQApi(self.session,'token',country,'client')
            await api.async_get_device_list()
            self.assertIn('api-'+region+'.lgthinq.com',self.session.request.call_args.args[1])

    async def test_empty_401_latches_and_never_exposes_credentials(self):
        self.response.status=401; self.response.body=''
        with self.assertRaises(ThinQAPIException) as caught: await self.api.async_get_device_list()
        self.assertEqual(caught.exception.code,'1103')
        self.assertEqual(caught.exception.headers,{})
        with self.assertRaises(ThinQAPIException): await self.api.async_get_device_profile('one')
        self.assertEqual(self.session.request.await_count,1)

    async def test_rate_limit_prevents_next_call_without_retrying_post(self):
        self.response.status=429;self.response.headers={'Retry-After':'120'}
        with self.assertRaises(ThinQAPIException): await self.api.async_post_device_control('one',{'operation':{}})
        with self.assertRaises(ThinQAPIException): await self.api.async_get_device_status('one')
        self.assertEqual(self.session.request.await_count,1)

    async def test_timeout_does_not_retry_control(self):
        self.session.request.side_effect=TimeoutError
        with self.assertRaises(TimeoutError): await self.api.async_post_device_control('one',{})
        self.assertEqual(self.session.request.await_count,1)

    async def test_conditional_control_and_encoded_device_id(self):
        await self.api.async_post_device_control('id/other',{'operation':{'washerOperationMode':'STOP'}})
        args,kwargs=self.session.request.call_args
        self.assertIn('id%2Fother/control',args[1])
        self.assertEqual(kwargs['headers']['x-conditional-control'],'true')
        self.assertEqual(kwargs['json']['operation']['washerOperationMode'],'STOP')

    async def test_unsupported_energy_and_malformed_success(self):
        self.response.status=406;self.response.body=''
        with self.assertRaises(ThinQAPIException) as caught: await self.api.async_get_device_energy_profile('one')
        self.assertEqual(caught.exception.code,'1221')
        self.response.status=200
        with self.assertRaises(ThinQAPIException) as caught: await self.api.async_get_device_status('one')
        self.assertEqual(caught.exception.code,'invalid_response')

    async def test_vendor_error_is_sanitized(self):
        self.response.status=400
        self.response.body=json.dumps({'error':{'code':'2301','message':'secret-token account personal text'}})
        with self.assertRaises(ThinQAPIException) as caught: await self.api.async_get_device_list()
        self.assertNotIn('secret-token',str(caught.exception))
        self.assertEqual(caught.exception.code,'2301')

    async def test_all_openapi_routes_have_callable_methods(self):
        calls=[('async_get_route',()),('async_get_device_list',()),('async_get_device_profile',('one',)),
          ('async_get_device_status',('one',)),('async_post_device_control',('one',{})),
          ('async_get_push_list',()),('async_post_push_subscribe',('one',)),('async_delete_push_subscribe',('one',)),
          ('async_get_push_devices_list',()),('async_post_push_devices_subscribe',()),('async_delete_push_devices_subscribe',()),
          ('async_get_event_list',()),('async_post_event_subscribe',('one',)),('async_delete_event_subscribe',('one',)),
          ('async_post_client_register',({},)),('async_delete_client_register',({},)),('async_post_client_certificate',({},)),
          ('async_get_device_energy_profile',('one',)),('async_get_device_energy_usage',('one','energyUsage','DAILY','2026-09-01','2026-09-02'))]
        for name,args in calls: await getattr(self.api,name)(*args)
        seen=set()
        for call in self.session.request.call_args_list:
            method,url=call.args
            path=url.split('.com',1)[1].replace('/one/','/{deviceId}/')
            seen.add((method.lower(),path))
        spec=json.loads((client_loader.ROOT/'docs/lg-openapi.json').read_text(encoding='utf-8-sig'))
        expected={(method,path.split('?')[0]) for path,ops in spec['paths'].items() for method in ops}
        self.assertEqual(seen,expected)
        await self.api.async_post_event_subscribe('one')
        self.assertEqual(self.session.request.call_args.kwargs['json']['expire'],{'unit':'HOUR','timer':24})
