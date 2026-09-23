# Direct LG API client migration

Version 0.2.0 removes the external `thinqconnect` requirement and all runtime imports. Existing profile and Home Assistant mappings are adapted into `custom_components/lg_thinq_extended/client` with Apache-2.0 attribution. Keeping those mappings preserves entity unique IDs, property names, model coverage and automation references.

## Transport and dependencies

- HTTP: Home Assistant's shared aiohttp session calls LG directly. The 19 operations in the supplied OpenAPI export are covered by request-contract tests.
- MQTT: Paho MQTT 2.1.0 connects directly to LG's TLS MQTT broker. It subscribes to all certificate-provided topics, resubscribes after reconnect, and uses exponential reconnect delay from 1 to 120 seconds.
- Certificates: cryptography generates a 2048-bit RSA key and SHA-512 CSR. Keys are never logged; temporary PEM files are removed immediately after loading the TLS context. Renewals prepare a new certificate before disconnecting the existing session.
- Home Assistant 2026.9.0 itself supplies aiohttp 3.14.3 and cryptography 48.0.1. The only additional declared requirement is paho-mqtt 2.1.0. This migration does not upgrade Home Assistant's cryptography pin.
- No pyOpenSSL, AWS CRT, AWS IoT SDK, or thinqconnect imports remain in this integration. Packages installed for other integrations may remain in Home Assistant's environment.

## LG OpenAPI findings

The owner's supplied export is stored as `docs/lg-openapi.json`; its SHA-256 is `49623c37d068eb42b4a0e6345a98213e6897f777f7c27e638367b99c0c0e0cab`. Its OpenAPI format is 3.1.0; its API version field is blank.

Event subscriptions explicitly allow 1–24 hours. Requests now use 24 hours and renew every 12 hours, replacing the SDK's 4464-hour request and daily renewal. The export has inconsistent client-body nesting and places energy query parameters inside a path string. The existing accepted top-level client payload shape is retained, and energy query values are encoded through aiohttp parameters. The existing `property` energy selector remains for compatibility although the export omits its declaration.

Invalid credentials stop later requests through the same client. HTTP 429 / LG 1306 / LG 1314 activate a bounded cooldown. No control request is automatically retried, including after timeout. Errors preserve LG codes without retaining authorization headers or raw server messages. Redirects are disabled so PATs cannot be forwarded to a different host.

## Verification and rollout

Tests replay 16 sanitized profile/state pairs from the owner's four appliance runs. They verify state mappings, remote-enable semantics, refrigerator and washer command payload construction, all OpenAPI operations, invalid credentials, rejected control responses, throttling, certificate signatures, and MQTT connection cleanup. Tests send no appliance commands.

The replay uncovered an existing laundry START guard defect: normalized remote state is a string, so comparing `.value is True` rejected valid remote-enabled devices. The guard now reads the mapping's boolean `is_on` property.

Install this development build and restart Home Assistant. First validate setup, MQTT updates, reload and diagnostics. Then perform supervised appliance actions. Confirm event updates continue across a 12-hour renewal and MQTT reconnect. The WM6998HBA Dry-only limitation is unchanged because its current LG profile does not expose a writable dry-cycle selection.

Live certificate issuance, LG MQTT connectivity and physical control under the new transport remain owner acceptance checks. To roll back, reinstall the preceding integration build and restart; config-entry credentials and entity IDs are preserved.
