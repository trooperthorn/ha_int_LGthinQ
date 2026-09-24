"""LG cloud MQTT transport using Paho and cryptography (no appliance SDK)."""
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import ssl
import tempfile
from urllib.parse import urlparse

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import paho.mqtt.client as mqtt

CLIENT_BODY = {"type": "MQTT", "service-code": "SVC202", "device-type": "607", "allowExist": True}


def generate_credentials():
    """Return a private key PEM and LG's base64 DER CSR."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    csr = (x509.CertificateSigningRequestBuilder()
           .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "lg_thinq")]))
           .sign(key, hashes.SHA512()))
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    encoded = "".join(csr.public_bytes(serialization.Encoding.PEM).decode("ascii").splitlines()[1:-1])
    return pem, encoded


def certificate_context(certificate, private_key):
    """Load the client identity then remove temporary PEM files immediately."""
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    with tempfile.TemporaryDirectory(prefix="lg-thinq-") as directory:
        cert_path = Path(directory) / "client.pem"
        key_path = Path(directory) / "key.pem"
        cert_path.write_bytes(certificate)
        key_path.write_bytes(private_key)
        key_path.chmod(0o600)
        cert_path.chmod(0o600)
        context.load_cert_chain(cert_path, key_path)
    return context


class ThinQMQTTClient:
    """Maintain a TLS MQTT session and renew expiring client certificates."""

    def __init__(self, thinq_api, client_id, on_message_received, **kwargs):
        self._api = thinq_api
        self._client_id = client_id
        self._callback = on_message_received
        self._client = None
        self._loop = asyncio.get_running_loop()
        self._ready = asyncio.Event()
        self._connected = False
        self._registered = False
        self._closing = False
        self._expires = None
        self._topics = []
        self._connection_callback = kwargs.get("on_connection_changed")

    def __await__(self):
        async def ready():
            route = await self._api.async_get_route()
            if not isinstance(route, dict) or not isinstance(route.get("mqttServer"), str):
                raise ValueError("LG returned no MQTT route")
            endpoint = urlparse(route["mqttServer"])
            if endpoint.scheme != "mqtts" or not endpoint.hostname:
                raise ValueError("LG returned an invalid TLS MQTT route")
            self._host, self._port = endpoint.hostname, endpoint.port or 8883
            return self
        return ready().__await__()

    @property
    def is_connected(self):
        return self._connected

    async def async_prepare_mqtt(self):
        await self._api.async_post_client_register(CLIENT_BODY)
        self._registered = True
        key, csr = await asyncio.to_thread(generate_credentials)
        response = await self._api.async_post_client_certificate({"service-code": "SVC202", "csr": csr})
        if not isinstance(response, dict):
            raise ValueError("LG returned no MQTT certificate")
        result = response.get("result", response)
        if not isinstance(result, dict) or not isinstance(result.get("certificatePem"), str):
            raise ValueError("LG returned no MQTT certificate")
        certificate = result["certificatePem"].encode("ascii")
        topics = result.get("subscriptions")
        if not isinstance(topics, list) or not topics or not all(isinstance(t, str) and t for t in topics):
            raise ValueError("LG returned no MQTT subscription topics")
        self._topics = topics
        self._expires = x509.load_pem_x509_certificate(certificate).not_valid_after_utc
        self._tls = await asyncio.to_thread(certificate_context, certificate, key)
        return True

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure or self._closing:
            return
        self._connected = True
        if self._connection_callback:
            self._loop.call_soon_threadsafe(self._connection_callback, True)
        # Subscribe on every connection, including a recovered session.
        client.subscribe([(topic, 1) for topic in self._topics])

    def _on_subscribe(self, client, userdata, mid, reason_codes, properties):
        if not any(code.is_failure for code in reason_codes):
            self._loop.call_soon_threadsafe(self._ready.set)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self._connected = False
        if self._connection_callback:
            self._loop.call_soon_threadsafe(self._connection_callback, False)
        self._loop.call_soon_threadsafe(self._ready.clear)

    def _on_message(self, client, userdata, message):
        if not self._closing:
            self._callback(topic=message.topic, payload=message.payload,
                           dup=message.dup, qos=message.qos, retain=message.retain)

    async def async_connect_mqtt(self):
        self._closing = False
        self._ready.clear()
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                   client_id=self._client_id, clean_session=False)
        self._client.tls_set_context(self._tls)
        self._client.reconnect_delay_set(min_delay=1, max_delay=120)
        self._client.on_connect = self._on_connect
        self._client.on_subscribe = self._on_subscribe
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.connect_async(self._host, self._port, keepalive=60)
        self._client.loop_start()
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=30)
        except BaseException:
            await self._stop_connection()
            raise

    async def _stop_connection(self):
        self._closing = True
        if self._client is not None:
            client, self._client = self._client, None
            await asyncio.to_thread(client.disconnect)
            await asyncio.to_thread(client.loop_stop)
        self._connected = False
        self._ready.clear()

    @property
    def certificate_expiry(self):
        return self._expires

    async def async_refresh_certificate(self):
        if self._expires and self._expires <= datetime.now(timezone.utc) + timedelta(days=1):
            await self.async_prepare_mqtt()
            await self._stop_connection()
            await self.async_connect_mqtt()

    async def async_disconnect(self):
        await self._stop_connection()
        if self._registered:
            try:
                await self._api.async_delete_client_register(CLIENT_BODY)
            finally:
                self._registered = False
