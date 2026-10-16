# 0.2.3 — camera resource management

- Reuse a single-threaded bare MJPEG codec instead of constructing a container and encoder for every image.
- Share one in-flight JPEG conversion across viewers; cancellation of one viewer does not cancel shared work.
- Wait for in-flight conversion before releasing encoder resources.
- Consume and discard unused audio to avoid accumulating decoded audio frames, preserving robot SDP interoperability.
- Preserve existing reference-counted sessions and idle grace period.
- No changes to requirements, bundled wheels, HA core or other integrations.
- Cloud checks cover JPEG resource growth without cyclic GC, concurrent cancellation, real audio/video, multiple viewers and repeated connection teardown.
- Physical robot/mobile-app lifecycle and HAOS memory trends still need installation verification. No claim that these tests rule out every OOM cause.
