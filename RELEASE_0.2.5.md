# 0.2.5 — app controls and orderly sleep

- Added **App** and **Start selected app**. Choices come from the robot's installed apps and refresh with the normal poll. HA remembers the selection; the robot's Startup app setting is not changed.
- Starting an app brings up a stopped backend without playing a wake animation, waits for the backend job to finish, then starts the selected app. The official conversation app and reachy_mini_ha_voice perform their own wake-up. Other apps determine their own posture.
- An already-starting/running selected app is left alone. Another active app or remote control session is not displaced.
- Renamed **Go to sleep** to **Sleep and stop backend**, keeping its entity unique ID. It now stops the current app, confirms that it exited and the control slot is free, then requests sleep/backend shutdown and checks completion. A failed or uncertain stop prevents shutdown.
- **Stop current app** still only stops the app; daemon 1.12.0 handles idle sleep and can keep antenna wake available with Startup app configured.
- **Wake up** still controls the robot/backend; it is not an app start button.
- App/backend commands from this integration are serialized. Other clients are not locked out; avoid issuing conflicting commands from the desktop app while HA is shutting down the backend.
- App start uses the daemon's no-evict endpoint (verified against daemon 1.12.0). Older daemons missing it report an error rather than falling back to evicting another session.

All names remain English. Existing custom entity names are preserved by HA; remove a custom name if you want the new default displayed. Existing automations targeting the sleep button keep their entity ID but now also stop the app before backend shutdown.

Python dependencies, camera quality, video transport and robot applications are unchanged. Validation runs in GitHub Actions with HA 2026.10.1. Physical wake, speech, motor release and antenna restart still require verification on the robot after installation.
