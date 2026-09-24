"""Support for LG ThinQ Connect API."""

import asyncio
from datetime import datetime
import json
import logging
from time import monotonic
from typing import Any

from aiohttp import ClientError
from .client import (
    DeviceType,
    ThinQApi,
    ThinQAPIErrorCodes,
    ThinQAPIException,
    ThinQMQTTClient,
)

from homeassistant.core import Event, HomeAssistant

from .const import DEVICE_PUSH_MESSAGE, DEVICE_STATUS_MESSAGE, DOMAIN
from homeassistant.util import dt as dt_util
from .coordinator import DeviceDataUpdateCoordinator
from .device_inventory import device_inventory_changed, parse_device_inventory
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
        self._closing = False
        self._last_inventory_check = 0.0
        self._inventory_task = None
        self._known_inventory = getattr(thinq_api, "inventory", None)
        self.subscription_status = "not_checked"
        self.subscription_checked = None
        self.client: ThinQMQTTClient | None = None

    def _connection_changed(self, connected):
        """Called on HA's event loop by the MQTT transport."""
        from homeassistant.util import dt as dt_util
        for coordinator in self.coordinators.values():
            monitor = coordinator.monitoring
            previous = monitor.mqtt_connected
            monitor.mqtt_connected = connected
            if connected:
                if monitor.ever_connected and not previous:
                    monitor.reconnects += 1
                monitor.ever_connected = True
            else:
                monitor.last_disconnect = dt_util.now()
                monitor.history.advance(dt_util.now())
                monitor.history.gap()
            monitor.save_later()
            monitor.notify()

    async def async_connect(self) -> bool:
        """Create a mqtt client and then try to connect."""

        self.client = await ThinQMQTTClient(
            self.thinq_api, self.client_id, self.on_message_received,
            on_connection_changed=self._connection_changed
        )
        if self.client is None:
            return False

        # Connect to server and create certificate.
        return await self.client.async_prepare_mqtt()

    async def async_disconnect(self, event: Event | None = None) -> None:
        """Unregister client and disconnects handlers."""
        self._closing = True
        if self._inventory_task is not None:
            self._inventory_task.cancel()
            self._inventory_task = None
        await self.async_end_subscribes()

        if self.client is not None:
            try:
                await self.client.async_disconnect()
            except (ThinQAPIException, TypeError, ValueError, ClientError, TimeoutError):
                # Saying goodbye is a courtesy, never a reason to fail the unload
                _LOGGER.exception("Failed to disconnect")

    def _get_failed_device_count(
        self, results: list[dict | BaseException | None], *, ending: bool = False
    ) -> int:
        """Check if there exists errors while performing tasks and then return count."""
        # Note that result code '1207' means 'Already subscribed push'
        # and is not actually fail.
        return sum(
            isinstance(result, BaseException)
            and not (
                isinstance(result, ThinQAPIException)
                and (result.code == ThinQAPIErrorCodes.ALREADY_SUBSCRIBED_PUSH
                     or (ending and result.code in {"1204", "1205", "1206", "1211", "1212", "1213", "1217"}))
            )
            for result in results
        )

    async def async_refresh_subscribe(self, now: datetime | None = None) -> None:
        """Update event subscribes."""
        _LOGGER.debug("async_refresh_subscribe: now=%s", now)
        if self.client is not None:
            try:
                await self.client.async_refresh_certificate()
            except (ThinQAPIException, ClientError, TimeoutError, OSError, ValueError):
                _LOGGER.warning("Could not renew LG MQTT certificate; retry at next renewal")

        tasks = [
            self.hass.async_create_task(
                self.thinq_api.async_post_event_subscribe(coordinator.device_id)
            )
            for coordinator in self.coordinators.values()
        ]
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            self.subscription_status = "subscription_request_failed" if self._get_failed_device_count(results) else "subscribed"
            self.subscription_checked = dt_util.now()
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
            self.subscription_status = "subscription_request_failed" if self._get_failed_device_count(results) else "subscribed"
            self.subscription_checked = dt_util.now()
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
            if (count := self._get_failed_device_count(results, ending=True)) > 0:
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
        try:
            message = json.loads(payload.decode())
        except (UnicodeDecodeError, ValueError):
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
            if push_type in {"DEVICE_REGISTERED", "DEVICE_UNREGISTERED", "DEVICE_ALIAS_CHANGED"}:
                self._schedule_inventory_check()
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
            _LOGGER.debug("Ignoring event for an unloaded LG device; checking inventory")
            self._schedule_inventory_check()
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

    def _schedule_inventory_check(self) -> None:
        """Coalesce bursts without dropping the final inventory change."""
        if self._closing:
            return
        self._inventory_check_pending = True
        if self._inventory_task is None:
            self._inventory_task = self.hass.async_create_task(self._async_check_device_inventory())

    async def _async_check_device_inventory(self) -> None:
        """Refresh authoritative inventory after LG app additions/removals."""
        try:
            while self._inventory_check_pending:
                await asyncio.sleep(max(2, 60 - (monotonic() - self._last_inventory_check)))
                self._inventory_check_pending = False
                self._last_inventory_check = monotonic()
                registered = await self.thinq_api.async_get_device_list()
                loaded = self._known_inventory
                if loaded is None:
                    loaded = {c.device_id: c.api.device.alias for c in self.coordinators.values()}
                if device_inventory_changed(registered, loaded):
                    current = parse_device_inventory(registered)
                    self._known_inventory = current
                    self.hass.bus.async_fire(DOMAIN + "_inventory_changed", {
                        "config_entry_id": self.entry_id,
                        "added": sorted(set(current)-set(loaded)),
                        "removed": sorted(set(loaded)-set(current)),
                        "renamed": sorted(k for k in current.keys() & loaded.keys() if current[k] != loaded[k]),
                        "managed_in": "LG ThinQ app"})
                    _LOGGER.info("LG app device inventory changed; refreshing integration")
                    # Unload must not cancel the task that requested its own reload.
                    self._inventory_task = None
                    await self.hass.config_entries.async_reload(self.entry_id)
                    return
        except (ThinQAPIException, ClientError, TimeoutError, ValueError):
            _LOGGER.warning("Could not refresh LG device inventory after notification")
        finally:
            self._inventory_task = None

    async def async_check_subscription_health(self):
        """Explicit audit; do not label a removed LG device as a broken appliance."""
        self.subscription_checked = dt_util.now()
        try:
            inventory = await self.thinq_api.async_get_device_list()
            current = parse_device_inventory(inventory)
            if current is None:
                raise ValueError("Invalid inventory")
            pushes = await self.thinq_api.async_get_push_list()
            events = await self.thinq_api.async_get_event_list()
            def ids(response):
                if not isinstance(response, list) or any(not isinstance(x, dict) or not isinstance(x.get("deviceId"), str) for x in response):
                    raise ValueError("Invalid subscription list")
                return {x["deviceId"] for x in response}
            expected = {c.device_id for c in self.coordinators.values()} & current.keys()
            self.subscription_status = "OK" if expected <= ids(pushes) and expected <= ids(events) else "missing_subscription"
            if self._known_inventory is not None and current != self._known_inventory:
                self._schedule_inventory_check()
        except (ThinQAPIException, ClientError, TimeoutError, ValueError) as exc:
            self.subscription_status = "check_failed:" + str(getattr(exc, "code", type(exc).__name__))
        for c in self.coordinators.values():
            c.monitoring.notify()
