# Compatibility wheels

The active wheel is aiortc-1.14.0+av19.1-py3-none-any.whl. Run scripts/build_av19_wheel.py in CI to reproduce it.

Source: the original aiortc-1.14.0+av17 wheel, retained for provenance and reproducibility. Its SHA256 is checked by the build script. The new wheel changes distribution version and the av upper bound to <20, then regenerates RECORD. Runtime code and licenses are preserved.

AV19 support was tested with real media and HA 2026.10.1 dependencies before release. This does not claim all aiortc features or every older av version have been validated.

SHA256: bc7b96ef1acca84d73bf2ea43fcc2d63575136e25c2cbd8136ddf3afb6033403
