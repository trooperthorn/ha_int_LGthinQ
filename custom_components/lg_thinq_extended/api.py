"""Integration aliases for the internal direct HTTP client."""
from .client import ThinQApi, ThinQAPIErrorCodes
from .device_inventory import parse_device_inventory
AUTH_ERROR_CODES = frozenset({ThinQAPIErrorCodes.INVALID_TOKEN,
    ThinQAPIErrorCodes.INVALID_TOKEN_AGAIN, ThinQAPIErrorCodes.NOT_FOUND_TOKEN})


class ThinQGuardedApi(ThinQApi):
    """Retain successful GETs for HA response actions and inventory reconciliation."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.inventory = None
        self.device_metadata = {}
        self.profiles = {}
        self.states = {}
        self.command_listeners = {}

    async def async_get_device_list(self, *args, **kwargs):
        result = await super().async_get_device_list(*args, **kwargs)
        parsed = parse_device_inventory(result)
        if parsed is None:
            raise ValueError("Invalid LG device inventory")
        self.inventory = parsed
        self.device_metadata = {d["deviceId"]: d["deviceInfo"] for d in result}
        return result

    async def async_get_device_profile(self, device_id, *args, **kwargs):
        result = await super().async_get_device_profile(device_id, *args, **kwargs)
        if not isinstance(result, dict):
            raise ValueError("Invalid LG profile")
        self.profiles[device_id] = result
        return result

    async def async_get_device_status(self, device_id, *args, **kwargs):
        result = await super().async_get_device_status(device_id, *args, **kwargs)
        self.states[device_id] = result
        return result

    async def async_post_device_control(self, device_id, payload, *args, **kwargs):
        # Observe existing platform commands as well as the explicit combo action.
        listeners = tuple(self.command_listeners.get(device_id, ()))
        for listener in listeners:
            listener("sending", payload, None)
        try:
            result = await super().async_post_device_control(device_id, payload, *args, **kwargs)
        except Exception as exc:
            for listener in listeners:
                listener("failed", payload, str(getattr(exc, "code", type(exc).__name__)))
            raise
        for listener in listeners:
            listener("accepted", payload, None)
        return result
