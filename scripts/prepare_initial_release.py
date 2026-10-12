"""Prepare the verified 0.2.1 fork release on a GitHub-hosted runner."""
import hashlib
import json
import os
from pathlib import Path
import shutil

REPOSITORY = "cuichaobaobao/reachy_mini_homeassistant"
VERSION = "0.2.1"
WHEEL = "aiortc-1.14.0+av19.1-py3-none-any.whl"
EXPECTED = "bc7b96ef1acca84d73bf2ea43fcc2d63575136e25c2cbd8136ddf3afb6033403"
assert os.environ["GITHUB_REPOSITORY"] == REPOSITORY
wheel = Path("dist") / WHEEL
assert hashlib.sha256(wheel.read_bytes()).hexdigest() == EXPECTED
shutil.copyfile(wheel, Path("wheels") / WHEEL)
manifest_path = Path("custom_components/reachy_mini/manifest.json")
manifest = json.loads(manifest_path.read_text())
assert manifest["version"] == "0.2.0", "Release only the reviewed upstream base"
manifest.update(
    version=VERSION,
    documentation=f"https://github.com/{REPOSITORY}",
    issue_tracker=f"https://github.com/{REPOSITORY}/issues",
    codeowners=["@cuichaobaobao"],
    requirements=[f"aiortc @ https://raw.githubusercontent.com/{REPOSITORY}/v{VERSION}/wheels/{WHEEL}#sha256={EXPECTED}"],
)
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
hacs_path = Path("hacs.json")
hacs = json.loads(hacs_path.read_text())
hacs["name"] = "Reachy Mini (cuichaobaobao)"
hacs_path.write_text(json.dumps(hacs, indent=2) + "\n")
readme_path = Path("README.md")
readme = readme_path.read_text()
readme = readme.replace(
    "https://github.com/pollen-robotics/reachy_mini_homeassistant",
    f"https://github.com/{REPOSITORY}",
)
readme_path.write_text(
    "# Reachy Mini — cuichaobaobao maintained fork\n\n"
    "Release **0.2.1** adapts the camera dependency to AV19 without downgrading "
    "Home Assistant's PyAV package. Based on "
    "[Pollen Robotics' original integration](https://github.com/pollen-robotics/reachy_mini_homeassistant).\n\n"
    "Cloud checks passed on Python 3.13/3.14 and Home Assistant 2026.10.1: "
    "dependency resolution, module imports, H264/VP8 WebRTC video, audio, "
    "and JPEG encoding. Physical robot discovery and video still need "
    "installation testing. See [fork notes](FORK_NOTES.md).\n\n"
    "Add this fork as an **Integration** custom repository in HACS. "
    "It uses the same reachy_mini domain as upstream; install only one.\n\n---\n\n" + readme
)
Path("FORK_NOTES.md").write_text(
    "# Maintained fork\n\n"
    "Owner: cuichaobaobao. Upstream: pollen-robotics/reachy_mini_homeassistant.\n\n"
    "## 0.2.1\n\n"
    "- Keep HA's existing av 19.0.0; use aiortc 1.14.0+av19.1.\n"
    "- Compatibility wheel is reproducibly generated from the SHA256-verified "
    "upstream wheel; only metadata and RECORD change, no runtime code changes.\n"
    "- The manifest pins an immutable release tag URL and SHA256 digest.\n"
    "- Python 3.13/3.14 media checks and HA 2026.10.1 dependency/import checks "
    "run in GitHub Actions. They include real ICE/DTLS/SRTP, H264/VP8 video, "
    "audio and JPEG round trips.\n"
    "- Physical robot discovery, GStreamer interoperability and dashboard "
    "behavior remain to be checked after HACS installation.\n\n"
    "## Future versions\n\n"
    "Use 0.2.2, 0.2.3, etc.; match manifest version to GitHub release tags "
    "(v0.2.2, v0.2.3). Document changes and test results per release. "
    "The automatic publish job is restricted to the initial 0.2.1 release; "
    "future versions require an explicit release change.\n\n"
    "No user host files, HA core files or shared dependency versions were "
    "changed by this cloud development process.\n"
)
Path("wheels/README.md").write_text(
    "# Compatibility wheels\n\n"
    "The active wheel is aiortc-1.14.0+av19.1-py3-none-any.whl. "
    "Run scripts/build_av19_wheel.py in CI to reproduce it.\n\n"
    "Source: the original aiortc-1.14.0+av17 wheel, retained for provenance "
    "and reproducibility. Its SHA256 is checked by the build script. "
    "The new wheel changes distribution version and the av upper bound to "
    "<20, then regenerates RECORD. Runtime code and licenses are preserved.\n\n"
    "AV19 support was tested with real media and HA 2026.10.1 dependencies "
    "before release. This does not claim all aiortc features or every older "
    "av version have been validated.\n\n"
    f"SHA256: {EXPECTED}\n"
)
