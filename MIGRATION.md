# Moving from other LG integrations

`lg_thinq_extended` is a separate Home Assistant domain. Installing it alongside Home Assistant's built-in `lg_thinq` or the legacy SmartThinQ custom integration may create duplicate entities for the same physical appliance. Record current entity IDs and automation references before moving. Add the fork, verify its device and entity states, then disable the older integration's duplicate entities if desired. Home Assistant does not automatically transfer entity IDs, history, or automation references between domains.

Keep the API key in Home Assistant's config entry. The Windows probe and diagnostics should be shared only after redaction. Check the device-specific [support matrix](MODEL_SUPPORT.md) before using controls; profile visibility alone does not establish a successful control POST.

