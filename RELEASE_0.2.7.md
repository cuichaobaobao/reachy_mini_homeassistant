## Changes

- Manual controls no longer turn unavailable while the integration itself is moving the robot. A new command during a movement continues smoothly toward the combined target instead of failing.
- One or two failed pose reads no longer grey out manual controls. Each movement reads the current pose once and sends nothing if that read fails.
- Stop current app and Restart current app are available only while an app is running, like the desktop. Daemon error details are shown instead of "Bad Request".
- Play emotion and Play dance are unavailable while the robot is asleep, with a clear message instead of a backend error. Manual controls wait while a recorded move started from HA plays.
- Add Startup app: read and set the robot's Startup app (or None) with the same daemon API the desktop uses.
- Display names: Sleep and stop backend is now Go to sleep (the upstream name); App is now App to start. Entity IDs are unchanged.

## Impact

Normal polling also reads /api/apps/startup-app. A manual movement reads /api/state/full once before sending. The reachy_mini.play_recorded_move service is not restricted, so existing automations and blueprints keep working.

Wake up, Power Off, Start selected app, Go to sleep behavior, camera code, media dependencies and icons are unchanged.

## Notes

Update through HACS and restart Home Assistant. Cloud tests do not replace testing on the robot.
