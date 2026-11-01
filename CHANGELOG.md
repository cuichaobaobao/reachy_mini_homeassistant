# Changelog

Release notes for this fork of the Reachy Mini Home Assistant integration, newest first.
The same notes are on the GitHub Releases page, which HACS shows when updating.
Versions before 0.2.1 are the upstream integration by Pollen Robotics.

## [0.2.10] - 2026-11-01

Button availability like the desktop.

### Changes

Buttons are greyed out when pressing them would do nothing, following the desktop app and the daemon:

- Wake up is available only while the robot is asleep, like the desktop wake/sleep toggle.
- Start selected app is unavailable while an app or remote session is active; stop the current app first, like the desktop.
- Go to sleep is unavailable when the robot is already deep asleep (backend stopped).
- Restart daemon is available only while the backend is running or in error. The daemon does nothing when it is stopped. In error it stays available, which is when it helps.

What each button does when pressed is unchanged.

### Impact

Only button availability changes. Manual controls, polling, camera code, media dependencies and icons are unchanged. The reachy_mini.play_recorded_move service and Motor mode are unchanged.

### Notes

Update through HACS and restart Home Assistant.

## [0.2.9] - 2026-10-31

Manual controls aligned with the desktop.

### Changes

Manual controls now follow the desktop controller:

- Values outside a range are clamped into the desktop ranges instead of rejected.
- The 65° head/body yaw limit is left to the daemon's automatic body yaw, as on the desktop. Turning the head far may turn the body a little; turning the body far with Head follows body off may stop short.
- A movement continues from the last target HA sent. Only a larger difference (the desktop's 0.1 major-change threshold) means the robot was moved elsewhere, and then the measured pose is used. Small measurement offsets no longer leak into the next movement.
- Head X, Head pitch and Head yaw use the desktop's display signs: positive is forward, up and right. Automations that set these three values need the opposite sign.
- Manual control values are shown with three decimals, like the desktop.

Head follows body, Center head, Center body and Movement duration are unchanged.

### Impact

Only manual-control target calculation and number display change. Other entities, polling, camera code, media dependencies and icons are unchanged.

### Notes

Update through HACS and restart Home Assistant. Please check on the robot that dragging Head yaw to the right turns the head right.

## [0.2.8] - 2026-10-31

Manual control limit fix.

### Changes

- Manual controls no longer get stuck when the robot's measured pose sits slightly past a limit (seen on the robot: Head roll measured at 0.53 rad after a 0.5 rad target, which made every slider and center button fail with "Combined pose exceeds Head roll range"). The next movement pulls such an axis back onto the limit, and its path never goes beyond where the robot already is. Requests beyond a limit are still rejected.

### Impact

Only the manual-control target calculation changes. Other entities, polling, camera code, media dependencies and icons are unchanged.

### Notes

Update through HACS and restart Home Assistant.

## [0.2.7] - 2026-10-31

Control fixes and Startup app.

### Changes

- Manual controls no longer turn unavailable while the integration itself is moving the robot. A new command during a movement continues smoothly toward the combined target instead of failing.
- One or two failed pose reads no longer grey out manual controls. Each movement reads the current pose once and sends nothing if that read fails.
- Stop current app and Restart current app are available only while an app is running, like the desktop. Daemon error details are shown instead of "Bad Request".
- Play emotion and Play dance are unavailable while the robot is asleep, with a clear message instead of a backend error. Manual controls wait while a recorded move started from HA plays.
- Add Startup app: read and set the robot's Startup app (or None) with the same daemon API the desktop uses.
- Display names: Sleep and stop backend is now Go to sleep (the upstream name); App is now App to start. Entity IDs are unchanged.

### Impact

Normal polling also reads /api/apps/startup-app. A manual movement reads /api/state/full once before sending. The reachy_mini.play_recorded_move service is not restricted, so existing automations and blueprints keep working.

Wake up, Power Off, Start selected app, Go to sleep behavior, camera code, media dependencies and icons are unchanged.

### Notes

Update through HACS and restart Home Assistant. Cloud tests do not replace testing on the robot.

## [0.2.6] - 2026-10-29

Manual controls and Power Off.

### Changes

- Add manual head, body and antenna controls, center buttons and movement duration.
- Add Head follows body. Turning the body can preserve the head's relative pose.
- Add Power Off. A configured Startup app keeps the backend available for antenna wake; otherwise the backend stops.

### Impact

Manual controls send commands directly to the robot when the cached state is ready and no app is active. There are no app/slot/motor preflight requests before each movement. Normal polling now also reads the current app, pose and running moves.

Camera code, media dependencies, icons and existing app controls are unchanged. No voice-app or daemon update is included.

### Notes

Update through HACS and restart Home Assistant. Test small movements first. Cloud tests do not replace testing on the robot.

Power Off is not a Linux shutdown. Sleep and stop backend still explicitly stops the backend. See docs/MANUAL_CONTROLS.md for limits and the differences from the desktop.

## [0.2.5] - 2026-10-28

App controls and orderly sleep.

### Changes
- Added **App** and **Start selected app** to start an installed robot app from HA.
- Renamed **Go to sleep** to **Sleep and stop backend**. It now stops the app first. If stopping fails, it leaves the backend running.
- **Wake up** and **Stop current app** keep their existing behavior.

### Impact
Dependencies and camera code are unchanged. Existing entity IDs are kept, but automations using the sleep button will now also stop the running app.

### Notes
Use **Start selected app** to start voice conversations; **Wake up** alone does not start an app. Backend shutdown disables antenna wake until the backend is started again.

App startup requires daemon 1.12.0 or a version with the same API. Update through HACS and restart HA. Robot behavior still needs checking after installation.

## [0.2.4] - 2026-10-16

Preserve camera image quality.

# 0.2.4 — preserve camera image quality

Fix a 0.2.3 regression: the reusable MJPEG encoder inherited a 200 kbps target and progressively increased compression. Use fixed JPEG quality (QP 8) with no bitrate target while retaining single-thread encoding and bounded work.

Add comparisons against the original encoder using fine detail, checkerboard and gradient images, including 60 identical frames to detect quality drift. Retain the camera resource and lifecycle checks.

No dependency changes. Physical camera appearance, network use and HAOS resource trends still require installation verification.

## [0.2.3] - 2026-10-16

Camera resource management.

# 0.2.3 — camera resource management

- Reuse a single-threaded bare MJPEG codec instead of constructing a container and encoder for every image.
- Share one in-flight JPEG conversion across viewers; cancellation of one viewer does not cancel shared work.
- Wait for in-flight conversion before releasing encoder resources.
- Consume and discard unused audio to avoid accumulating decoded audio frames, preserving robot SDP interoperability.
- Preserve existing reference-counted sessions and idle grace period.
- No changes to requirements, bundled wheels, HA core or other integrations.
- Cloud checks cover JPEG resource growth without cyclic GC, concurrent cancellation, real audio/video, multiple viewers and repeated connection teardown.
- Physical robot/mobile-app lifecycle and HAOS memory trends still need installation verification. No claim that these tests rule out every OOM cause.

## [0.2.2] - 2026-10-13

Local Reachy Mini icon.

### 0.2.2
- Add bundled Reachy Mini icon and logo using Home Assistant 2026.3+ local brand support.
- Include 256px and 512px transparent PNGs from the official Pollen Robotics desktop app.
- Images live under custom_components/reachy_mini/brand and work without the external brands CDN.
- No changes to robot behavior, Python runtime code or dependency requirements from 0.2.1.

Update in HACS, restart Home Assistant and refresh the browser to load the local images.

## [0.2.1] - 2026-10-12

AV19 compatibility.

# Maintained fork

Owner: cuichaobaobao. Upstream: pollen-robotics/reachy_mini_homeassistant.

### 0.2.1

- Keep HA's existing av 19.0.0; use aiortc 1.14.0+av19.1.
- Compatibility wheel is reproducibly generated from the SHA256-verified upstream wheel; only metadata and RECORD change, no runtime code changes.
- The manifest pins an immutable release tag URL and SHA256 digest.
- Python 3.13/3.14 media checks and HA 2026.10.1 dependency/import checks run in GitHub Actions. They include real ICE/DTLS/SRTP, H264/VP8 video, audio and JPEG round trips.
- Physical robot discovery, GStreamer interoperability and dashboard behavior remain to be checked after HACS installation.

### Future versions

Use 0.2.2, 0.2.3, etc.; match manifest version to GitHub release tags (v0.2.2, v0.2.3). Document changes and test results per release. The automatic publish job is restricted to the initial 0.2.1 release; future versions require an explicit release change.

No user host files, HA core files or shared dependency versions were changed by this cloud development process.
