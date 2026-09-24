"""Direct LG ThinQ HTTP client; routes verified against LG's OpenAPI export.

Endpoint wrappers and error constants derived from LG Electronics' Apache-2.0 code.
"""
import asyncio
import base64
import json
import time
import uuid
from enum import Enum
from typing import Any
from urllib.parse import quote
from aiohttp import ClientSession, ClientResponse, ClientTimeout
from aiohttp.hdrs import METH_GET, METH_POST, METH_DELETE
from .const import API_KEY
from .country import get_region_from_country

def _id(value: str) -> str:
    return quote(str(value), safe="")

class ThinQAPIErrorCodes(str, Enum):
    """The class that represents the error codes for LG ThinQ Connect API."""

    UNKNOWN_ERROR = "0000"
    BAD_REQUEST = "1000"
    MISSING_PARAMETERS = "1101"
    UNACCEPTABLE_PARAMETERS = "1102"
    INVALID_TOKEN = "1103"
    INVALID_MESSAGE_ID = "1104"
    NOT_REGISTERED_ADMIN = "1201"
    NOT_REGISTERED_USER = "1202"
    NOT_REGISTERED_SERVICE = "1203"
    NOT_SUBSCRIBED_EVENT = "1204"
    NOT_EXIST_DEVICE = "1205"
    NOT_SUBSCRIBED_PUSH = "1206"
    ALREADY_SUBSCRIBED_PUSH = "1207"
    NOT_REGISTERED_SERVICE_BY_ADMIN = "1208"
    NOT_REGISTERED_USER_IN_SERVICE = "1209"
    NOT_REGISTERED_DEVICE_IN_SERVICE = "1210"
    NOT_REGISTERED_DEVICE_BY_USER = "1211"
    NOT_OWNED_DEVICE = "1212"
    NOT_REGISTERED_DEVICE = "1213"
    NOT_SUBSCRIBABLE_DEVICE = "1214"
    INCORRECT_HEADER = "1216"
    ALREADY_DEVICE_DELETED = "1217"
    INVALID_TOKEN_AGAIN = "1218"
    NOT_SUPPORTED_MODEL = "1219"
    NOT_SUPPORTED_FEATURE = "1220"
    NOT_SUPPORTED_PRODUCT = "1221"
    NOT_CONNECTED_DEVICE = "1222"
    INVALID_STATUS_DEVICE = "1223"
    INVALID_DEVICE_ID = "1224"
    DUPLICATE_DEVICE_ID = "1225"
    INVALID_SERVICE_KEY = "1301"
    NOT_FOUND_TOKEN = "1302"
    NOT_FOUND_USER = "1303"
    NOT_ACCEPTABLE_TERMS = "1304"
    NOT_ALLOWED_API = "1305"
    EXCEEDED_API_CALLS = "1306"
    NOT_SUPPORTED_COUNTRY = "1307"
    NO_CONTROL_AUTHORITY = "1308"
    NOT_ALLOWED_API_AGAIN = "1309"
    NOT_SUPPORTED_DOMAIN = "1310"
    BAD_REQUEST_FORMAT = "1311"
    EXCEEDED_NUMBER_OF_EVENT_SUBSCRIPTION = "1312"
    INTERNAL_SERVER_ERROR = "2000"
    NOT_SUPPORTED_MODEL_AGAIN = "2101"
    NOT_PROVIDED_FEATURE = "2201"
    NOT_SUPPORTED_PRODUCT_AGAIN = "2202"
    NOT_EXISTENT_MODEL_JSON = "2203"
    INVALID_DEVICE_STATUS = "2205"
    INVALID_COMMAND_ERROR = "2207"
    FAIL_DEVICE_CONTROL = "2208"
    DEVICE_RESPONSE_DELAY = "2209"
    RETRY_REQUEST = "2210"
    SYNCING = "2212"
    RETRY_AFTER_DELETING_DEVICE = "2213"
    FAIL_REQUEST = "2214"
    COMMAND_NOT_SUPPORTED_IN_REMOTE_OFF = "2301"
    COMMAND_NOT_SUPPORTED_IN_STATE = "2302"
    COMMAND_NOT_SUPPORTED_IN_ERROR = "2303"
    COMMAND_NOT_SUPPORTED_IN_POWER_OFF = "2304"
    COMMAND_NOT_SUPPORTED_IN_MODE = "2305"


error_code_mapping = {member.value: member.name for member in ThinQAPIErrorCodes}


class ThinQAPIException(Exception):
    """The class that represents an exception for LG ThinQ Connect API."""

    def __init__(self, code: str, message: str, headers: dict):
        """Initialize the exception."""
        self.code = code
        self.message = message
        self.headers = {}  # Never retain request credentials in exceptions.
        self.error_name = error_code_mapping.get(code, "UNKNOWN_ERROR")
        super().__init__(f"Error: {self.error_name} ({self.code}) - {self.message}")

    def __str__(self) -> str:
        return f"ThinQAPIException: {self.error_name} ({self.code}) - {self.message}"


class ThinQApi:
    """Own request lifecycle without an external appliance SDK."""

    def __init__(self, session: ClientSession, access_token: str, country_code: str,
                 client_id: str, **kwargs: Any):
        self._session = session
        self._access_token = access_token
        self._country_code = country_code
        self._client_id = client_id
        self._region_code = get_region_from_country(country_code)
        self._blocked_until = 0.0
        self._auth_failed = False

    def __await__(self):
        async def ready():
            return self
        return ready().__await__()

    async def _async_fetch(self, method: str, url: str, **kwargs: Any) -> ClientResponse:
        return await self._session.request(method, url, **kwargs)

    async def async_request(self, method: str, endpoint: str, **kwargs: Any):
        if self._auth_failed:
            raise ThinQAPIException("1103", "LG credentials rejected; reauthenticate", {})
        if time.monotonic() < self._blocked_until:
            raise ThinQAPIException("1306", "LG rate limit cooldown is active", {})
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "x-country": self._country_code,
            "x-client-id": self._client_id,
            "x-api-key": API_KEY,
            "x-message-id": base64.urlsafe_b64encode(uuid.uuid4().bytes).decode().rstrip("="),
            "x-service-phase": "OP",
            **kwargs.pop("headers", {}),
        }
        timeout = ClientTimeout(total=kwargs.pop("timeout", 15))
        url = f"https://api-{self._region_code.lower()}.lgthinq.com/{endpoint}"
        # No automatic retries: a timed-out control may have reached the appliance.
        async with await self._async_fetch(method, url, headers=headers,
                                          timeout=timeout, allow_redirects=False, **kwargs) as response:
            if response.status == 401:
                self._auth_failed = True
                raise ThinQAPIException("1103", "LG credentials rejected", {})
            try:
                payload = json.loads(await response.text())
            except (ValueError, UnicodeError):
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            error = payload.get("error") or {}
            if not isinstance(error, dict):
                error = {}
            code = str(error.get("code", response.status))
            if response.status == 429 or code in {"1306", "1314"}:
                try:
                    cooldown = float(response.headers.get("Retry-After", "60"))
                except ValueError:
                    cooldown = 60
                self._blocked_until = time.monotonic() + max(1, min(cooldown, 86400))
                raise ThinQAPIException("1306", "LG request rate exceeded", {})
            if code in {"1103", "1218", "1302"}:
                self._auth_failed = True
            if response.status >= 300 or error:
                if response.status == 406 and not error:
                    code = "1221"
                # Vendor messages can contain identifiers. Preserve code, not raw payload.
                raise ThinQAPIException(code, error_code_mapping.get(code, f"LG HTTP {response.status}"), {})
            if response.status == 204:
                return None
            if "response" not in payload:
                raise ThinQAPIException("invalid_response", "LG returned an invalid response envelope", {})
            return payload["response"]

    async def async_get_device_list(self, timeout: int | float = 15) -> list | None:
        return await self.async_request(method=METH_GET, endpoint="devices", timeout=timeout)

    async def async_get_device_profile(self, device_id: str, timeout: int | float = 15) -> dict | None:
        return await self.async_request(
            method=METH_GET,
            endpoint=f"devices/{_id(device_id)}/profile",
            timeout=timeout,
        )

    async def async_get_device_status(self, device_id: str, timeout: int | float = 15) -> dict | None:
        return await self.async_request(method=METH_GET, endpoint=f"devices/{_id(device_id)}/state", timeout=timeout)

    async def async_post_device_control(self, device_id: str, payload: Any, timeout: int | float = 15) -> dict | None:
        headers = {"x-conditional-control": "true"}
        return await self.async_request(
            method=METH_POST,
            endpoint=f"devices/{_id(device_id)}/control",
            json=payload,
            timeout=timeout,
            headers=headers,
        )

    async def async_get_device_energy_profile(self, device_id: str, timeout: int | float = 15) -> dict | None:
        return await self.async_request(
            method=METH_GET,
            endpoint=f"devices/energy/{_id(device_id)}/profile",
            timeout=timeout,
        )

    async def async_get_device_energy_usage(
        self,
        device_id: str,
        energy_property: str,
        period: str,
        start_date: str,
        end_date: str,
        timeout: int | float = 15,
    ) -> dict | None:
        return await self.async_request(
            method=METH_GET,
            endpoint=f"devices/energy/{_id(device_id)}/usage",
            params={"property": energy_property, "period": period, "startDate": start_date, "endDate": end_date},
            timeout=timeout,
        )

    async def async_post_client_register(self, payload: Any, timeout: int | float = 15) -> dict | None:
        return await self.async_request(
            method=METH_POST,
            endpoint="client",
            json=payload,
            timeout=timeout,
        )

    async def async_delete_client_register(self, payload: Any, timeout: int | float = 15) -> dict | None:
        return await self.async_request(
            method=METH_DELETE,
            endpoint="client",
            json=payload,
            timeout=timeout,
        )

    async def async_post_client_certificate(self, payload: Any, timeout: int | float = 15) -> dict | None:
        return await self.async_request(
            method=METH_POST,
            endpoint="client/certificate",
            json=payload,
            timeout=timeout,
        )

    async def async_get_push_list(self, timeout: int | float = 15) -> dict | None:
        return await self.async_request(
            method=METH_GET,
            endpoint="push",
            timeout=timeout,
        )

    async def async_post_push_subscribe(self, device_id: str, timeout: int | float = 15) -> dict | None:
        return await self.async_request(
            method=METH_POST,
            endpoint=f"push/{_id(device_id)}/subscribe",
            timeout=timeout,
        )

    async def async_delete_push_subscribe(self, device_id: str, timeout: int | float = 15) -> dict | None:
        return await self.async_request(
            method=METH_DELETE,
            endpoint=f"push/{_id(device_id)}/unsubscribe",
            timeout=timeout,
        )

    async def async_get_event_list(self, timeout: int | float = 15) -> dict | None:
        return await self.async_request(
            method=METH_GET,
            endpoint="event",
            timeout=timeout,
        )

    async def async_post_event_subscribe(self, device_id: str, timeout: int | float = 15) -> dict | None:
        """Subscribe to event notifications for the device."""
        return await self.async_request(
            method=METH_POST,
            endpoint=f"event/{_id(device_id)}/subscribe",
            json={"expire": {"unit": "HOUR", "timer": 24}},
            timeout=timeout,
        )

    async def async_delete_event_subscribe(self, device_id: str, timeout: int | float = 15) -> dict | None:
        """Unsubscribe to event notifications for the device."""
        return await self.async_request(
            method=METH_DELETE,
            endpoint=f"event/{_id(device_id)}/unsubscribe",
            timeout=timeout,
        )

    async def async_get_push_devices_list(self, timeout: int | float = 15) -> dict | None:
        """Get the list of clients subscribed to push notifications for devices registered,unregistered, and alias updated."""
        return await self.async_request(
            method=METH_GET,
            endpoint="push/devices",
            timeout=timeout,
        )

    async def async_post_push_devices_subscribe(self, timeout: int | float = 15) -> dict | None:
        """Subscribe to push notifications for devices registered,unregistered, and alias updated."""
        return await self.async_request(
            method=METH_POST,
            endpoint="push/devices",
            timeout=timeout,
        )

    async def async_delete_push_devices_subscribe(self, timeout: int | float = 15) -> dict | None:
        """Unsubscribe to push notifications for devices registered,unregistered, and alias updated."""
        return await self.async_request(
            method=METH_DELETE,
            endpoint="push/devices",
            timeout=timeout,
        )

    async def async_get_route(self, timeout: int | float = 15) -> dict | None:
        return await self.async_request(
            method=METH_GET,
            endpoint="route",
            timeout=timeout,
        )

