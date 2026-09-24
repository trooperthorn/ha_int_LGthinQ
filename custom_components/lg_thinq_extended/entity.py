"""Base class for ThinQ entities."""

from collections.abc import Callable, Coroutine
import logging
from typing import Any, override

from aiohttp import ClientError
from .client import ThinQAPIException
from .client.devices.const import Location
from .client.integration import PropertyState

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import COMPANY, DEVICE_UNIT_TO_HA, DOMAIN
from .coordinator import DeviceDataUpdateCoordinator
from .laundry_status import laundry_remote_ready
from .oven_control import oven_command_allowed, oven_control_state

_LOGGER = logging.getLogger(__name__)

EMPTY_STATE = PropertyState()


class ThinQEntity(CoordinatorEntity[DeviceDataUpdateCoordinator]):
    """The base implementation of all lg thinq entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DeviceDataUpdateCoordinator,
        entity_description: EntityDescription,
        property_id: str,
        postfix_id: str | None = None,
    ) -> None:
        """Initialize an entity."""
        super().__init__(coordinator)

        self.entity_description = entity_description
        self.property_id = property_id
        self.location = self.coordinator.api.get_location_for_idx(self.property_id)

        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, coordinator.unique_id)},
            connections={(dr.CONNECTION_NETWORK_MAC, coordinator.insights.mac)} if coordinator.insights.mac and coordinator.sub_id is None else set(),
            manufacturer=COMPANY,
            model=(
                f"{coordinator.api.device.model_name}"
                f" ({self.coordinator.api.device.device_type})"
            ),
            name=coordinator.device_name,
        )
        self._attr_unique_id = (
            f"{coordinator.unique_id}_{self.property_id}"
            if postfix_id is None
            else f"{coordinator.unique_id}_{self.property_id}_{postfix_id}"
        )
        if self.location is not None and self.location not in (
            Location.MAIN,
            Location.OVEN,
            coordinator.sub_id,
        ):
            self._attr_translation_placeholders = {"location": self.location}
            self._attr_translation_key = (
                f"{entity_description.translation_key}_for_location"
            )

    @property
    def data(self) -> PropertyState:
        """Return the state data of entity."""
        return self.coordinator.data.get(self.property_id, EMPTY_STATE)

    def _get_unit_of_measurement(self, unit: str | None) -> str | None:
        """Convert thinq unit string to HA unit string."""
        if unit is None:
            return None

        return DEVICE_UNIT_TO_HA.get(unit)

    def _update_status(self) -> None:
        """Update status itself.

        All inherited classes can update their own status in here.
        """

    @callback
    @override
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_status()
        self.async_write_ha_state()

    @override
    async def async_added_to_hass(self) -> None:
        """Call when entity is added to hass."""
        await super().async_added_to_hass()
        self._handle_coordinator_update()

    async def async_require_oven_remote_ready(self) -> None:
        """Refresh oven state and reject controls after remote start is disabled."""
        try:
            fresh = await self.coordinator.api.fetch_data()
        except (ThinQAPIException, ClientError, TimeoutError) as exc:
            raise ServiceValidationError(
                "Could not verify oven remote-start status"
            ) from exc
        if not isinstance(fresh, dict):
            raise ServiceValidationError("Could not verify oven remote-start status")
        self.coordinator.async_set_updated_data(fresh)
        run_state, remote_enabled = oven_control_state(fresh, self.location)
        if not oven_command_allowed(run_state, remote_enabled):
            raise ServiceValidationError(
                "Oven is off and remote start is disabled; enable it at the appliance"
            )

    async def async_require_laundry_remote_ready(self) -> None:
        """Read current state before START so a stale remote flag cannot start a load."""
        try:
            fresh = await self.coordinator.api.fetch_data()
        except (ThinQAPIException, ClientError, TimeoutError) as exc:
            raise ServiceValidationError(
                "Could not verify laundry remote-start status"
            ) from exc
        if not isinstance(fresh, dict):
            raise ServiceValidationError("Could not verify laundry remote-start status")
        self.coordinator.async_set_updated_data(fresh)
        if not laundry_remote_ready(fresh, self.location):
            raise ServiceValidationError(
                "Remote start is disabled; enable it at the appliance"
            )

    async def async_call_api(
        self,
        target: Coroutine[Any, Any, Any],
        on_fail_method: Callable[[], None] | None = None,
    ) -> None:
        """Call the given api and handle exception."""
        try:
            await target
        except ThinQAPIException as exc:
            if on_fail_method:
                on_fail_method()
            raise ServiceValidationError(exc.message) from exc
        except ValueError as exc:
            if on_fail_method:
                on_fail_method()
            raise ServiceValidationError(exc) from exc
        except (TimeoutError, ClientError) as exc:
            if on_fail_method:
                on_fail_method()
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="connection_error",
            ) from exc

