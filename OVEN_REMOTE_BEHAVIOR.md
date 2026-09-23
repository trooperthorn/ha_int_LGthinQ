# Oven remote behavior observed by owner

The owner reports that this oven's physical remote dial allows one remote start. Once the oven is turned off, the dial must be reset at the appliance before another remote start. Setting the target temperature or Bake mode can start the oven. Selecting `Start` or `Preheating` with no chosen settings starts Bake at 350 °F. These are observed behaviors for one oven, not general LG API guarantees.

The official state contains `remoteControlEnable.remoteControlEnabled` for the oven cavity. The integration already exposed this as a binary sensor; it is now labeled **Oven remote start enabled**. Both oven command selects use `INITIAL` plus this value to show **Off** or **Off (remote ready)** when idle, rather than displaying Unknown for their write-only command state. A running state is shown as **On** for the write-only operation select. These labels are display states, not API commands.

When the oven is idle and `remoteControlEnabled` is false, the oven command selects expose only their display state and reject direct control service calls. The oven target-temperature number becomes unavailable and its service call is blocked. An active cavity remains controllable when the remote-start flag is false: the owner's captured preheating state had that combination. Before any oven command, the integration fetches fresh state and checks the current run/remote conditions again. The owner should test that the flag becomes false after the oven is turned off and true after the dial is reset. No control POST was sent during implementation.

The refrigerator's physical range was rechecked by the owner: fridge 33–43 °F and freezer −7–5 °F. This matches the captured Fahrenheit profile; no range override is needed.

