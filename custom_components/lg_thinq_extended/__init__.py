"""Support for LG ThinQ Connect device."""

import asyncio
from dataclasses import dataclass, field
import logging

from aiohttp import ClientError
from .client import ThinQAPIException
from .client.integration import async_get_ha_bridge_list

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_ACCESS_TOKEN,
    CONF_COUNTRY,
    EVENT_HOMEASSISTANT_STOP,
    Platform,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval

from .const import CONF_CONNECT_CLIENT_ID, DOMAIN, MQTT_SUBSCRIPTION_INTERVAL
from .api import AUTH_ERROR_CODES, ThinQGuardedApi
from .coordinator import DeviceDataUpdateCoordinator, async_setup_device_coordinator
from .mqtt import ThinQMQTT
from .device_inventory import parse_device_inventory
from .services import register_services


@dataclass(kw_only=True)
class ThinqData:
    """A class that holds runtime data."""

    coordinators: dict[str, DeviceDataUpdateCoordinator] = field(default_factory=dict)
    mqtt_client: ThinQMQTT | None = None


type ThinqConfigEntry = ConfigEntry[ThinqData]

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.EVENT,
    Platform.FAN,
    Platform.HUMIDIFIER,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.VACUUM,
    Platform.WATER_HEATER,
]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ThinqConfigEntry) -> bool:
    """Set up an entry."""
    entry.runtime_data = ThinqData()

    access_token = entry.data[CONF_ACCESS_TOKEN]
    client_id = entry.data[CONF_CONNECT_CLIENT_ID]
    country_code = entry.data[CONF_COUNTRY]

    thinq_api = ThinQGuardedApi(
        session=async_get_clientsession(hass),
        access_token=access_token,
        country_code=country_code,
        client_id=client_id,
    )

    # Setup coordinators and register devices.
    await async_setup_coordinators(hass, entry, thinq_api)

    # Establish transport before creating platforms; failed setup must not leave entities active.
    await async_setup_mqtt(hass, entry, thinq_api, client_id)
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await entry.runtime_data.mqtt_client.async_disconnect()
        raise

    for coordinator in entry.runtime_data.coordinators.values():
        coordinator.monitoring.start()

    # Clean up devices they are no longer in use.
    await async_cleanup_device_registry(hass, entry, thinq_api)

    register_services(hass)
    return True


async def async_setup_coordinators(
    hass: HomeAssistant,
    entry: ThinqConfigEntry,
    thinq_api: ThinQGuardedApi,
) -> None:
    """Set up coordinators and register devices."""
    # Get a list of ha bridge.
    try:
        bridge_list = await async_get_ha_bridge_list(thinq_api)
    except ThinQAPIException as exc:
        if exc.code in AUTH_ERROR_CODES:
            raise ConfigEntryAuthFailed("LG ThinQ credentials rejected") from exc
        raise ConfigEntryNotReady(exc.message) from exc
    except (ClientError, TimeoutError, ValueError) as exc:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="connection_error",
        ) from exc

    if not bridge_list:
        _LOGGER.info("No supported devices loaded; add or remove appliances in the LG ThinQ app")
        return

    # Setup coordinator per device.
    task_list = [
        hass.async_create_task(async_setup_device_coordinator(hass, entry, bridge))
        for bridge in bridge_list
    ]
    task_result = await asyncio.gather(*task_list)
    for coordinator in task_result:
        entry.runtime_data.coordinators[coordinator.unique_id] = coordinator


async def async_cleanup_device_registry(hass, entry, thinq_api) -> None:
    """Remove only this entry's devices confirmed absent from LG inventory."""
    try:
        inventory = parse_device_inventory(await thinq_api.async_get_device_list())
    except (ThinQAPIException, ClientError, TimeoutError, ValueError):
        _LOGGER.debug("Deferring registry cleanup until LG inventory can be confirmed")
        return
    if inventory is None:
        return
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        identifiers = [identifier for domain, identifier in device.identifiers if domain == DOMAIN]
        # WashTower entities can have location suffixes on their cloud device ID.
        if identifiers and not any(
            identifier == cloud_id or identifier.startswith(cloud_id + "_")
            for identifier in identifiers for cloud_id in inventory
        ):
            registry.async_remove_device(device.id)
            _LOGGER.info("Detached an appliance removed through the LG ThinQ app")


async def async_setup_mqtt(
    hass: HomeAssistant, entry: ThinqConfigEntry, thinq_api: ThinQGuardedApi, client_id: str
) -> None:
    """Set up MQTT connection."""
    mqtt_client = ThinQMQTT(
        hass, thinq_api, client_id, entry.runtime_data.coordinators, entry.entry_id
    )
    entry.runtime_data.mqtt_client = mqtt_client

    # Try to connect.
    try:
        result = await mqtt_client.async_connect()
        if not result:
            raise ValueError("LG MQTT preparation failed")
        await mqtt_client.async_start_subscribes()
    except (AttributeError, ThinQAPIException, TypeError, ValueError, OSError) as exc:
        await mqtt_client.async_disconnect()
        if isinstance(exc, ThinQAPIException) and exc.code in AUTH_ERROR_CODES:
            raise ConfigEntryAuthFailed("LG ThinQ credentials rejected") from exc
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="failed_to_connect_mqtt",
            translation_placeholders={"error": str(exc)},
        ) from exc
    except (ClientError, TimeoutError, ValueError) as exc:
        await mqtt_client.async_disconnect()
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="connection_error",
        ) from exc

    entry.async_on_unload(
        async_track_time_interval(
            hass,
            mqtt_client.async_refresh_subscribe,
            MQTT_SUBSCRIPTION_INTERVAL,
            cancel_on_shutdown=True,
        )
    )
    entry.async_on_unload(
        hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP, mqtt_client.async_disconnect
        )
    )


async def async_unload_entry(hass: HomeAssistant, entry: ThinqConfigEntry) -> bool:
    """Unload the entry."""
    if entry.runtime_data.mqtt_client:
        await entry.runtime_data.mqtt_client.async_disconnect()

    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        for coordinator in entry.runtime_data.coordinators.values():
            await coordinator.monitoring.close()
    return unloaded

