# Internal LG client provenance

Device models, profile parsing, country routing, error constants, endpoint wrapper signatures, and Home Assistant property mappings are adapted from LG Electronics pythinqconnect tag 1.0.14 (commit 2617a12e6cc8e7fec0f1c831211216970d870b3f), Apache License 2.0. Original copyright headers and LICENSE are retained.

The integration owns and ships these files. There is no thinqconnect package dependency or import. HTTP request execution and MQTT transport are independently implemented here using aiohttp, cryptography and Paho MQTT. Future upstream mapping changes require review and deliberate adoption.
