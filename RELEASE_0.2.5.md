## Changes
- Added **App** and **Start selected app** to start an installed robot app from HA.
- Renamed **Go to sleep** to **Sleep and stop backend**. It now stops the app first. If stopping fails, it leaves the backend running.
- **Wake up** and **Stop current app** keep their existing behavior.

## Impact
Dependencies and camera code are unchanged. Existing entity IDs are kept, but automations using the sleep button will now also stop the running app.

## Notes
Use **Start selected app** to start voice conversations; **Wake up** alone does not start an app. Backend shutdown disables antenna wake until the backend is started again.

App startup requires daemon 1.12.0 or a version with the same API. Update through HACS and restart HA. Robot behavior still needs checking after installation.
