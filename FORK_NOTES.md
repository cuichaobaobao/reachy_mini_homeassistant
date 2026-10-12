# Maintained fork

Owner: cuichaobaobao. Upstream: pollen-robotics/reachy_mini_homeassistant.

## 0.2.1

- Keep HA's existing av 19.0.0; use aiortc 1.14.0+av19.1.
- Compatibility wheel is reproducibly generated from the SHA256-verified upstream wheel; only metadata and RECORD change, no runtime code changes.
- The manifest pins an immutable release tag URL and SHA256 digest.
- Python 3.13/3.14 media checks and HA 2026.10.1 dependency/import checks run in GitHub Actions. They include real ICE/DTLS/SRTP, H264/VP8 video, audio and JPEG round trips.
- Physical robot discovery, GStreamer interoperability and dashboard behavior remain to be checked after HACS installation.

## Future versions

Use 0.2.2, 0.2.3, etc.; match manifest version to GitHub release tags (v0.2.2, v0.2.3). Document changes and test results per release. The automatic publish job is restricted to the initial 0.2.1 release; future versions require an explicit release change.

No user host files, HA core files or shared dependency versions were changed by this cloud development process.
