# LG ThinQ Extended for Home Assistant

An independent, Apache-2.0 licensed development fork of Home Assistant's built-in LG ThinQ integration. The repository focuses first on refrigerators, ovens, washers, and dryers using **LG's official ThinQ Connect API** and the `thinqconnect` Python library. It does not use the legacy WideQ API.

## Current state

This is a **source baseline and implementation plan**, not a tested release. The copied integration has been renamed to the `lg_thinq_extended` domain so Home Assistant will not replace its built-in `lg_thinq` files. No additional appliance feature has been implemented or validated on hardware yet. The integration pins the same `thinqconnect==1.0.14` dependency as the upstream snapshot. See [UPSTREAM.md](UPSTREAM.md) for source provenance and [PLAN.md](PLAN.md) for phases and acceptance gates.

Do not install this as a replacement for a working LG setup yet. Running both integrations against the same account may create duplicate devices and API traffic. The custom domain also means entities and automations from built-in `lg_thinq` will not migrate automatically.

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

The source is under `custom_components/lg_thinq_extended`. The copied upstream code is preserved as a baseline, with domain and manifest metadata adjusted. Phased changes should retain a testable mapping from an LG profile property to a library method, entity, and device-specific acceptance test.

