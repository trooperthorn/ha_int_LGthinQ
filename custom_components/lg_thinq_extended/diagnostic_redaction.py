"""Remove account and network identifiers from LG API diagnostics."""

from collections.abc import Mapping
from hashlib import sha256
import re
from typing import Any

_SENSITIVE_KEYS = re.compile(
    r"^(?:authorization|access.?token|refresh.?token|token|secret|password|"
    r"csr|certificate|private.?key|public.?key|mac.?address|mac|ssid|alias|"
    r"nick.?name|email|user.?number|user.?list|account.?id|"
    r"serial(?:no|number)?|ip.?address|client.?id|service.?id)$",
    re.IGNORECASE,
)
_DEVICE_ID = re.compile(r"^device.?id$", re.IGNORECASE)
_GROUP_ID = re.compile(r"^group.?id$", re.IGNORECASE)
_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_MAC = re.compile(r"\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b", re.IGNORECASE)
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def device_ref(device_id: str) -> str:
    """Produce a stable local reference without exposing an LG device ID."""
    return f"device-{sha256(device_id.encode()).hexdigest()[:16]}"


def redact_api_data(value: Any, key: str = "") -> Any:
    """Recursively sanitize an LG API response for user-downloadable diagnostics."""
    if _DEVICE_ID.fullmatch(key):
        return device_ref(str(value)) if value is not None else None
    if _GROUP_ID.fullmatch(key):
        return f"group-{sha256(str(value).encode()).hexdigest()[:16]}" if value is not None else None
    if _SENSITIVE_KEYS.fullmatch(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(child_key): redact_api_data(item, str(child_key)) for child_key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_api_data(item) for item in value]
    if isinstance(value, str):
        if _EMAIL.search(value) or _MAC.search(value) or _IPV4.search(value):
            return "[REDACTED STRING]"
    return value

