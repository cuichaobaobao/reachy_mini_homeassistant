## Changes

Buttons are greyed out when pressing them would do nothing, following the desktop app and the daemon:

- Wake up is available only while the robot is asleep, like the desktop wake/sleep toggle.
- Start selected app is unavailable while an app or remote session is active; stop the current app first, like the desktop.
- Go to sleep is unavailable when the robot is already deep asleep (backend stopped).
- Restart daemon is available only while the backend is running or in error. The daemon does nothing when it is stopped. In error it stays available, which is when it helps.

What each button does when pressed is unchanged.

## Impact

Only button availability changes. Manual controls, polling, camera code, media dependencies and icons are unchanged. The reachy_mini.play_recorded_move service and Motor mode are unchanged.

## Notes

Update through HACS and restart Home Assistant.
