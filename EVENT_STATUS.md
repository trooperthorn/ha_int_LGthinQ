# Event status

Home Assistant event entities show the timestamp of their last event. They show Unknown before the first event; emitting a fabricated OK event would create a misleading timestamp and could trigger automations. The integration therefore retains the event entities and adds Error status and Notification status sensors for device fields exposed by the LG profile.

Each status sensor shows OK when its current LG event field is empty and the actual event code when one is present. OK means no current event value was reported; it does not certify that the appliance is fault free. Device unavailability remains unavailable. The event entity still records genuine notifications and errors with their timestamps.

