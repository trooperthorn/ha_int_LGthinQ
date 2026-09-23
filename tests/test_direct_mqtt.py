"""Verify CSR cryptography and the MQTT connection lifecycle without LG calls."""
import asyncio
import base64
from datetime import datetime,timedelta,timezone
import unittest
from unittest.mock import AsyncMock,patch
import client_loader
from cryptography import x509
from cryptography.hazmat.primitives import serialization,hashes
from custom_components.lg_thinq_extended.client.mqtt_client import generate_credentials,certificate_context,ThinQMQTTClient

class CertificateTests(unittest.TestCase):
    def test_generated_csr_signature_key_and_tls_context(self):
        key_pem,encoded=generate_credentials()
        csr=x509.load_der_x509_csr(base64.b64decode(encoded))
        self.assertTrue(csr.is_signature_valid)
        key=serialization.load_pem_private_key(key_pem,password=None)
        self.assertEqual(csr.public_key().public_numbers(),key.public_key().public_numbers())
        self.assertEqual(csr.subject.rfc4514_string(),'CN=lg_thinq')
        now=datetime.now(timezone.utc)
        cert=(x509.CertificateBuilder().subject_name(csr.subject).issuer_name(csr.subject)
          .public_key(key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now).not_valid_after(now+timedelta(days=2)).sign(key,hashes.SHA256()))
        context=certificate_context(cert.public_bytes(serialization.Encoding.PEM),key_pem)
        self.assertTrue(context.check_hostname)

class FakePaho:
    def tls_set_context(self,context): pass
    def reconnect_delay_set(self,**kwargs): pass
    def connect_async(self,*args,**kwargs): pass
    def loop_start(self):
        ok=type('Code',(),{'is_failure':False})()
        self.on_connect(self,None,None,ok,None)
        self.on_subscribe(self,None,1,[ok],None)
    def subscribe(self,topics): self.topics=topics
    def disconnect(self): self.disconnected=True
    def loop_stop(self): self.stopped=True

class MQTTTests(unittest.IsolatedAsyncioTestCase):
    async def test_connect_resubscribe_and_disconnect_cleanup(self):
        api=type('API',(),{})()
        api.async_get_route=AsyncMock(return_value={'mqttServer':'mqtts://broker.example:8883'})
        api.async_delete_client_register=AsyncMock()
        client=await ThinQMQTTClient(api,'test',lambda **kw:None)
        client._tls=object();client._topics=['one','two'];client._registered=True
        paho=FakePaho()
        with patch('custom_components.lg_thinq_extended.client.mqtt_client.mqtt.Client',return_value=paho):
            await client.async_connect_mqtt()
            self.assertTrue(client.is_connected)
            self.assertEqual(paho.topics,[('one',1),('two',1)])
            await client.async_disconnect()
        self.assertTrue(paho.stopped)
        self.assertTrue(paho.disconnected)
        self.assertFalse(client.is_connected)
        api.async_delete_client_register.assert_awaited_once()

    async def test_certificate_renewal_precedes_expiry(self):
        client=ThinQMQTTClient(object(),'test',lambda **kw:None)
        client._expires=datetime.now(timezone.utc)+timedelta(hours=2)
        client._stop_connection=AsyncMock()
        client.async_prepare_mqtt=AsyncMock()
        client.async_connect_mqtt=AsyncMock()
        await client.async_refresh_certificate()
        client._stop_connection.assert_awaited_once()
        client.async_prepare_mqtt.assert_awaited_once()
        client.async_connect_mqtt.assert_awaited_once()

    async def test_malformed_certificate_cleanup(self):
        api=type('API',(),{})()
        api.async_post_client_register=AsyncMock()
        api.async_post_client_certificate=AsyncMock(return_value={'result': {}})
        api.async_delete_client_register=AsyncMock()
        client=ThinQMQTTClient(api,'test',lambda **kw:None)
        with self.assertRaisesRegex(ValueError,'no MQTT certificate'):
            await client.async_prepare_mqtt()
        await client.async_disconnect()
        api.async_delete_client_register.assert_awaited_once()

    async def test_missing_route_is_rejected(self):
        api=type('API',(),{})()
        api.async_get_route=AsyncMock(return_value={})
        with self.assertRaisesRegex(ValueError,'no MQTT route'):
            await ThinQMQTTClient(api,'test',lambda **kw:None)
