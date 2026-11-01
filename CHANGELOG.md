# Changelog

All notable changes to this fork of the Reachy Mini Home Assistant integration are
documented here. Versions before 0.2.1 are the upstream integration by Pollen Robotics.
Each version's section is also published as its GitHub Release notes, which HACS
shows when updating.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.10] - 2026-11-01

### Changed

- Buttons are greyed out when pressing them would do nothing, following the desktop
  app and the daemon. What each button does when pressed is unchanged.
  - Wake up: only while the robot is asleep, like the desktop wake/sleep toggle.
  - Start selected app: unavailable while an app or remote session is active; stop
    the current app first, like the desktop.
  - Go to sleep: unavailable when the robot is already deep asleep (backend stopped).
  - Restart daemon: only while the backend is running or in error; the daemon does
    nothing when it is stopped.

## [0.2.9] - 2026-10-31

### Changed

- Manual controls follow the desktop controller:
  - Values outside a range are clamped into the desktop ranges instead of rejected.
  - The 65° head/body yaw limit is left to the daemon's automatic body yaw. Turning
    the head far may turn the body a little; turning the body far with Head follows
    body off may stop short.
  - A movement continues from the last target HA sent. The measured pose is used
    only after a larger change (the desktop's 0.1 threshold), so small measurement
    offsets no longer carry into the next movement.
  - Head X, Head pitch and Head yaw use the desktop display signs: positive is
    forward, up and right. Automations that set these values need the opposite sign.
- Manual control values are shown with three decimals, like the desktop.

## [0.2.8] - 2026-10-31

### Fixed

- Manual controls no longer get stuck when the measured pose sits slightly past a
  limit (e.g. Head roll measured at 0.53 rad after a 0.5 rad target made every
  slider and center button fail with "Combined pose exceeds Head roll range"). The
  next movement pulls such an axis back onto the limit, and its path never goes
  beyond where the robot already is.

## [0.2.7] - 2026-10-31

### Added

- Startup app select: read and set the robot's Startup app (or None) with the same
  daemon API as the desktop.

### Changed

- Stop current app and Restart current app are available only while an app is
  running, like the desktop.
- Play emotion and Play dance are unavailable while the robot is asleep. The
  `reachy_mini.play_recorded_move` service is not restricted.
- Manual controls wait while a recorded move started from HA plays.
- Display names: Sleep and stop backend is now Go to sleep (the upstream name), and
  App is now App to start. Entity IDs are unchanged.

### Fixed

- Manual controls no longer turn unavailable while the integration itself moves the
  robot; a new command during a movement continues toward the combined target
  instead of failing.
- One or two failed pose reads no longer grey out manual controls. Each movement
  reads the pose once and sends nothing if that read fails.
- Daemon error details are shown instead of "Bad Request", e.g. for Stop current app
  with no app running.

## [0.2.6] - 2026-10-29

### Added

- Manual head, body and antenna controls, Center head/body/all buttons and Movement
  duration. See [docs/MANUAL_CONTROLS.md](docs/MANUAL_CONTROLS.md).
- Head follows body switch: turning the body keeps the head's pose relative to it.
- Power Off, like the desktop: sleep and motors off; the backend keeps running when a
  Startup app is set (antenna wake), otherwise it stops. It is not a Linux shutdown.

## [0.2.5] - 2026-10-28

### Added

- App select and Start selected app to start an installed robot app from HA
  (requires daemon 1.12.0 or the same API).

### Changed

- Go to sleep is renamed Sleep and stop backend and now stops the running app first;
  if stopping fails, the backend keeps running. Entity IDs are unchanged.

## [0.2.4] - 2026-10-16

### Fixed

- Camera image quality: the encoder reused since 0.2.3 inherited a 200 kbps target and
  blurred images over time. It now uses a fixed JPEG quality (QP 8) with no bitrate
  target, still single-threaded with bounded work.

## [0.2.3] - 2026-10-16

### Fixed

- Camera resource growth: one single-threaded MJPEG encoder is reused instead of a
  container and encoder per image.
- Viewers share one in-flight JPEG conversion. Cancelling one viewer does not cancel
  the shared work, and encoder resources are released only after it ends.
- Unused audio is consumed and discarded so decoded audio frames do not accumulate.

## [0.2.2] - 2026-10-13

### Added

- Local Reachy Mini icon and logo (Home Assistant 2026.3+ local brand support), from
  the official Pollen Robotics desktop app; no external brands CDN is needed. Refresh
  the browser after updating.

## [0.2.1] - 2026-10-12

### Fixed

- Compatibility with Home Assistant's av 19.0.0: use the aiortc 1.14.0+av19.1
  compatibility wheel, reproducibly built from the SHA256-verified upstream wheel
  (only its metadata and RECORD change). The manifest pins its URL and SHA256.

[Unreleased]: https://github.com/cuichaobaobao/reachy_mini_homeassistant/compare/v0.2.10...HEAD
[0.2.10]: https://github.com/cuichaobaobao/reachy_mini_homeassistant/compare/v0.2.9...v0.2.10
[0.2.9]: https://github.com/cuichaobaobao/reachy_mini_homeassistant/compare/v0.2.8...v0.2.9
[0.2.8]: https://github.com/cuichaobaobao/reachy_mini_homeassistant/compare/v0.2.7...v0.2.8
[0.2.7]: https://github.com/cuichaobaobao/reachy_mini_homeassistant/compare/v0.2.6...v0.2.7
[0.2.6]: https://github.com/cuichaobaobao/reachy_mini_homeassistant/compare/v0.2.5...v0.2.6
[0.2.5]: https://github.com/cuichaobaobao/reachy_mini_homeassistant/compare/v0.2.4...v0.2.5
[0.2.4]: https://github.com/cuichaobaobao/reachy_mini_homeassistant/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/cuichaobaobao/reachy_mini_homeassistant/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/cuichaobaobao/reachy_mini_homeassistant/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/cuichaobaobao/reachy_mini_homeassistant/releases/tag/v0.2.1
