"""Support for LG ThinQ Connect API."""

import asyncio
from datetime import datetime
import json
import logging
from time import monotonic
from typing import Any

from aiohttp import ClientError
from thinqconnect import (
    DeviceType,
    ThinQApi,
    ThinQAPIErrorCodes,
    ThinQAPIException,
    ThinQMQTTClient,
)

from homeassistant.core import Event, HomeAssistant

from .const import DEVICE_PUSH_MESSAGE, DEVICE_STATUS_MESSAGE
from .coordinator import DeviceDataUpdateCoordinator
from .device_inventory import device_inventory_changed
from .diagnostic_redaction import device_ref, redact_api_data

_LOGGER = logging.getLogger(__name__)


class ThinQMQTT:
    """A class that implements MQTT connection."""

    def __init__(
        self,
        hass: HomeAssistant,
        thinq_api: ThinQApi,
        client_id: str,
        coordinators: dict[str, DeviceDataUpdateCoordinator],
        entry_id: str,
    ) -> None:
        """Initialize a mqtt."""
        self.hass = hass
        self.thinq_api = thinq_api
        self.client_id = client_id
        self.coordinators = coordinators
        self.entry_id = entry_id
        self._inventory_check_pending = False
        self._last_inventory_check = 0.0
        self.client: ThinQMQTTClient | None = None

    async def async_connect(self) -> bool:
        """Create a mqtt client and then try to connect."""

        self.client = await ThinQMQTTClient(
            self.thinq_api, self.client_id, self.on_message_received
        )
        if self.client is None:
            return False

        # Connect to server and create certificate.
        return await self.client.async_prepare_mqtt()

    async def async_disconnect(self, event: Event | None = None) -> None:
        """Unregister client and disconnects handlers."""
        await self.async_end_subscribes()

        if self.client is not None:
            try:
                await self.client.async_disconnect()
            except (ThinQAPIException, TypeError, ValueError, ClientError, TimeoutError):
                # Saying goodbye is a courtesy, never a reason to fail the unload
                _LOGGER.exception("Failed to disconnect")

    def _get_failed_device_count(
        self, results: list[dict | BaseException | None]
    ) -> int:
        """Check if there exists errors while performing tasks and then return count."""
        # Note that result code '1207' means 'Already subscribed push'
        # and is not actually fail.
        return sum(
            isinstance(result, BaseException)
            and not (
                isinstance(result, ThinQAPIException)
                and result.code == ThinQAPIErrorCodes.ALREADY_SUBSCRIBED_PUSH
            )
            for result in results
        )

    async def async_refresh_subscribe(self, now: datetime | None = None) -> None:
        """Update event subscribes."""
        _LOGGER.debug("async_refresh_subscribe: now=%s", now)

        tasks = [
            self.hass.async_create_task(
                self.thinq_api.async_post_event_subscribe(coordinator.device_id)
            )
            for coordinator in self.coordinators.values()
        ]
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            if (count := self._get_failed_device_count(results)) > 0:
                _LOGGER.error("Failed to refresh subscription on %s devices", count)

    async def async_start_subscribes(self) -> None:
        """Start push/event subscribes."""
        _LOGGER.debug("async_start_subscribes")

        if self.client is None:
            _LOGGER.error("Failed to start subscription: No client")
            return

        tasks = [
            self.hass.async_create_task(
                self.thinq_api.async_post_push_subscribe(coordinator.device_id)
            )
            for coordinator in self.coordinators.values()
        ]
        tasks.extend(
            self.hass.async_create_task(
                self.thinq_api.async_post_event_subscribe(coordinator.device_id)
            )
            for coordinator in self.coordinators.values()
        )
        tasks.append(self.hass.async_create_task(self.thinq_api.async_post_push_devices_subscribe()))
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            if (count := self._get_failed_device_count(results)) > 0:
                _LOGGER.error("Failed to start subscription on %s devices", count)

        await self.client.async_connect_mqtt()

    async def async_end_subscribes(self) -> None:
        """Start push/event unsubscribes."""
        _LOGGER.debug("async_end_subscribes")

        tasks = [
            self.hass.async_create_task(
                self.thinq_api.async_delete_push_subscribe(coordinator.device_id)
            )
            for coordinator in self.coordinators.values()
        ]
        tasks.extend(
            self.hass.async_create_task(
                self.thinq_api.async_delete_event_subscribe(coordinator.device_id)
            )
            for coordinator in self.coordinators.values()
        )
        tasks.append(self.hass.async_create_task(self.thinq_api.async_delete_push_devices_subscribe()))
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            if (count := self._get_failed_device_count(results)) > 0:
                _LOGGER.error("Failed to end subscription on %s devices", count)

    def on_message_received(
        self,
        topic: str,
        payload: bytes,
        dup: bool,
        qos: Any,
        retain: bool,
        **kwargs: dict,
    ) -> None:
        """Handle the received message that matching the topic."""
        decoded = payload.decode()
        try:
            message = json.loads(decoded)
        except ValueError:
            _LOGGER.error("Failed to parse LG device message")
            return
        if not isinstance(message, dict):
            _LOGGER.warning("Ignoring malformed LG device message")
            return

        asyncio.run_coroutine_threadsafe(
            self.async_handle_device_event(message), self.hass.loop
        ).result()

    async def async_handle_device_event(self, message: dict) -> None:
        """Handle received mqtt message."""
        push_type = message.get("pushType")
        if push_type not in (DEVICE_STATUS_MESSAGE, DEVICE_PUSH_MESSAGE):
            if not self._inventory_check_pending and monotonic() - self._last_inventory_check >= 60:
                self._inventory_check_pending = True
                self._last_inventory_check = monotonic()
                self.hass.async_create_task(self._async_check_device_inventory())
            return
        if not isinstance(message.get("deviceId"), str):
            _LOGGER.warning("Ignoring malformed LG device message")
            return
        report = message.get("report")
        if push_type == DEVICE_STATUS_MESSAGE and not isinstance(report, dict):
            _LOGGER.warning("Ignoring malformed LG status message")
            return
        if message.get("deviceType") == DeviceType.WASHTOWER and not report:
            _LOGGER.warning("Ignoring LG WashTower message without a location")
            return
        unique_id = (
            f"{message['deviceId']}_{next(iter(report))}"
            if message.get("deviceType") == DeviceType.WASHTOWER
            else message["deviceId"]
        )
        coordinator = self.coordinators.get(unique_id)
        if coordinator is None:
            _LOGGER.error("Failed to handle device event: No device")
            return

        _LOGGER.debug(
            "async_handle_device_event: device=%s, message=%s",
            device_ref(coordinator.device_id),
            redact_api_data(message),
        )
        if push_type == DEVICE_STATUS_MESSAGE:
            coordinator.handle_update_status(message.get("report", {}))
        elif push_type == DEVICE_PUSH_MESSAGE:
            coordinator.handle_notification_message(message.get("pushCode"))

    async def _async_check_device_inventory(self) -> None:
        """Reload once when LG announces a changed registered-device list."""
        try:
            registered = await self.thinq_api.async_get_device_list()
            loaded = {
                coordinator.device_id: coordinator.api.device.alias
                for coordinator in self.coordinators.values()
            }
            if device_inventory_changed(registered, loaded):
                await self.hass.config_entries.async_reload(self.entry_id)
        except (ThinQAPIException, ClientError, TimeoutError):
            _LOGGER.warning("Could not refresh LG device inventory after notification")
        finally:
            self._inventory_check_pending = False

