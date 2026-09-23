# LG ThinQ Extended for Home Assistant

An independent, Apache-2.0 licensed development fork of Home Assistant's built-in LG ThinQ integration. The repository focuses first on refrigerators, ovens, washers, and dryers using **LG's official ThinQ Connect API** and the `thinqconnect` Python library. It does not use the legacy WideQ API.

## Current state

This is a **development build**, not a release. The copied integration has been renamed to the `lg_thinq_extended` domain so Home Assistant will not replace its built-in `lg_thinq` files. User-initiated, redacted diagnostics show model capabilities. A [Windows ThinQ Connect probe](tools/README.md) collects GET responses and supports a separately confirmed control POST. [Five owner probe runs](OBSERVED_RUNS.md) inform authentication handling and state behavior. The owner reports working refrigerator and oven controls, but a WM6998HBA remote START began washing despite Dry being selected at the dial; its observed official profile has no writable Dry-only course field. The fork pins `thinqconnect==1.0.13` because SDK 1.0.14's cryptography requirement conflicts with the owner's Home Assistant installation. See [UPSTREAM.md](UPSTREAM.md) for source provenance and [PLAN.md](PLAN.md) for phases and acceptance gates.

This remains a development build. Running both integrations against the same account may create duplicate devices and API traffic. The custom domain also means entities and automations from built-in `lg_thinq` will not migrate automatically. See [migration guidance](MIGRATION.md) and the [observed model support matrix](MODEL_SUPPORT.md).

## Goals

- Expose all *documented, model-advertised* ThinQ Connect data and controls that are useful for the priority devices.
- Make read versus write capability visible per model; never present a control merely because another model supports it.
- Use explicit, validated Home Assistant controls for refrigerator and oven commands and washer/dryer operations.
- Cover the official API's device, event, push, client, route, and energy calls through the underlying library or integration lifecycle where appropriate. [API_COVERAGE.md](API_COVERAGE.md) records the current gaps.
- Keep device-profile and state diagnostics redacted before sharing them.

## Official references

- [ThinQ API](https://smartsolution.developer.lge.com/en/apiManage/thinq_connect)
- [Device profiles](https://smartsolution.developer.lge.com/en/apiManage/device_profile)
- [Home Assistant built-in LG ThinQ](https://www.home-assistant.io/integrations/lg_thinq)
- [ThinQ Connect Python SDK](https://github.com/thinq-connect/pythinqconnect)

LG's PAT documentation limits the token to personal, non-commercial use. Developers of additional services should review LG's stated consent terms before distribution or commercial use.

## Development

The source is under `custom_components/lg_thinq_extended`. The copied upstream code is preserved as a baseline, with domain and manifest metadata adjusted. [Initial runtime validation](RUNTIME_VALIDATION.md) records successful setup and reload on one owner's Home Assistant instance. User-initiated diagnostics include a capability summary from the existing per-device GETs and now query four additional account-level read-only endpoints; that newer change needs a runtime retest. LG's SDK DEBUG logs can include device IDs and certificate response data; review and redact them before sharing.

For a supervised appliance command trial, use the [live control POST checklist](CONTROL_TEST.md). Installation and diagnostics do not send control POSTs.

