# Maintained fork

Owner: cuichaobaobao. Upstream: pollen-robotics/reachy_mini_homeassistant.

## Planned release: 0.2.1

Compatibility target: Home Assistant's existing av 19.0.0.
The integration manifest remains at the upstream version until compatibility
checks pass. This branch is not yet a verified AV19 fix.

The AV19 compatibility workflow builds a reproducible candidate wheel from
the hash-verified upstream compatibility wheel. Only distribution metadata
and RECORD change; aiortc runtime code remains unchanged. The candidate is
tested with real H264/VP8 video, audio, WebRTC and JPEG encoding on GitHub-hosted
runners. No user host or Home Assistant installation is accessed.

Passing media tests does not establish Home Assistant discovery or physical
robot compatibility. Those checks must be reported separately before claiming
end-to-end success.

Future integration versions will use 0.2.1, 0.2.2, etc., with matching GitHub
release tags (v0.2.1, v0.2.2). Publish only integration releases, not wheel-only
releases, because HACS treats GitHub releases as integration versions.
