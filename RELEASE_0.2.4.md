# 0.2.4 — preserve camera image quality

Fix a 0.2.3 regression: the reusable MJPEG encoder inherited a 200 kbps target and progressively increased compression. Use fixed JPEG quality (QP 8) with no bitrate target while retaining single-thread encoding and bounded work.

Add comparisons against the original encoder using fine detail, checkerboard and gradient images, including 60 identical frames to detect quality drift. Retain the camera resource and lifecycle checks.

No dependency changes. Physical camera appearance, network use and HAOS resource trends still require installation verification.
