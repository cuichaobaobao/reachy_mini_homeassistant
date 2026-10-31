"""DataUpdateCoordinator for Reachy Mini.

Fans out to several SDK endpoints in parallel and assembles a
unified, HA-shaped dict the entity platforms read by key:

- ``/api/daemon/status``           — daemon health, motor_control_mode,
                                     firmware version, hardware_id.
- ``/api/daemon/robot-app-lock-status`` — managed app slot owner.
- ``/api/state/doa``               — mic-array direction of arrival.
- ``/api/volume/current``          — speaker volume.
- ``/api/volume/microphone/current`` — microphone volume.

Each fetch is independent: an individual 404 / network error /
malformed response produces ``None`` for that endpoint's contribution
to the dict but does **not** mark the whole coordinator as
``UpdateFailed``. The whole coordinator only fails when *every*
endpoint is unreachable (no network, daemon down) — at which point
HA marks all entities unavailable, which is the correct UX.

HA-shaped derivations live here (not in the SDK):

- ``awake`` = motor_mode in {"enabled", "gravity_compensation"}.
- ``active_app``, ``active_app_transport``, ``remote_session_active``
  derived from the app-lock state + holder name. "Remote session" means
  a remote client (mobile/desktop app over WebRTC) holds the robot app
  slot — deliberately not named after WebRTC itself, since camera-feed
  consumption also uses WebRTC but never takes the slot.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .app_control import APP_LIST, AppControl
from .manual_control import ManualControl, FULL_STATE, APP_STATUS, RUNNING_MOVES
from .const import (
    DAEMON_STATE_RUNNING,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DOMAIN,
    ENDPOINT_APP_LOCK,
    ENDPOINT_APP_STARTUP,
    ENDPOINT_DOA,
    ENDPOINT_MOVE_LIST,
    ENDPOINT_MOVE_PLAY,
    ENDPOINT_STATUS,
    ENDPOINT_VOLUME_MIC,
    ENDPOINT_VOLUME_SPEAKER,
    RECORDED_MOVE_DATASETS,
)

_LOGGER = logging.getLogger(__name__)

# How often and how long to watch a recorded move started from HA.
MOVE_WATCH_INTERVAL = 1.0
MOVE_WATCH_LIMIT = 180


def _derive_awake(motor_mode: str | None, daemon_state: str | None) -> bool | None:
    """`enabled` and `gravity_compensation` both count as awake.

    A backend that isn't running at all (the Wireless unit's normal
    asleep state — it reports no motor mode) is definitively asleep,
    not unknown.
    """
    if daemon_state is not None and daemon_state != DAEMON_STATE_RUNNING:
        return False
    if motor_mode is None:
        return None
    return motor_mode in ("enabled", "gravity_compensation")


def _derive_app_slot(state: str | None, holder: str | None) -> dict[str, Any]:
    """Expand the raw app-lock fields into HA-shaped values."""
    if state == "local_app":
        return {
            "active_app": holder,
            "active_app_transport": "local",
            "remote_session_active": False,
        }
    if state == "remote_session":
        return {
            "active_app": holder,
            "active_app_transport": "webrtc",
            "remote_session_active": True,
        }
    if state == "free":
        return {
            "active_app": None,
            "active_app_transport": None,
            "remote_session_active": False,
        }
    return {
        "active_app": None,
        "active_app_transport": None,
        "remote_session_active": None,
    }


class ReachyMiniCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fan-out poller for the SDK's individual REST endpoints."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Bind the coordinator to a config entry."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.data[CONF_HOST]}",
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self._entry = entry
        self._session = async_get_clientsession(hass)
        self.app_control = AppControl(self._session, self.base_url)
        self.app_command_lock = asyncio.Lock()
        self.manual_control = ManualControl(self)
        self.installed_apps: list[str] = []
        self.selected_app: str | None = None
        # Recorded-move catalogs. Populated once at setup-time via
        # async_load_move_lists. Stable at runtime — not in the per-tick
        # fan-out poll. Keyed by full HF dataset path.
        self.move_lists: dict[str, list[str]] = {}
        # User's last pick per dataset. Mutated by the select entities'
        # async_select_option; read by the matching play buttons.
        self.selected_move: dict[str, str | None] = {
            ds: None for ds in RECORDED_MOVE_DATASETS
        }
        # A recorded move HA started, until the daemon reports none running;
        # manual controls and play buttons wait for it like the desktop.
        self.move_playing = False
        self._move_watch: asyncio.Task | None = None
        self._missed_poses = 0

    @property
    def host(self) -> str:
        """Configured hostname or IP of the daemon."""
        return self._entry.data[CONF_HOST]

    @property
    def port(self) -> int:
        """Configured TCP port of the daemon (default 8000)."""
        return self._entry.data.get(CONF_PORT, DEFAULT_PORT)

    @property
    def base_url(self) -> str:
        """``http://<host>:<port>`` — root for all endpoint paths."""
        return f"http://{self.host}:{self.port}"

    async def _fetch_json(self, path: str) -> Any | None:
        """Fetch one endpoint; return parsed JSON or None on any failure."""
        url = f"{self.base_url}{path}"
        try:
            async with self._session.get(
                url, timeout=aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT)
            ) as resp:
                if resp.status != 200:
                    _LOGGER.debug("Reachy Mini %s returned %s", path, resp.status)
                    return None
                return await resp.json()
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            _LOGGER.debug("Reachy Mini fetch %s failed: %s", path, err)
            return None

    async def async_post(
        self, path: str, *, body: dict[str, Any] | None = None,
        timeout: float = DEFAULT_TIMEOUT, method: str = "POST",
    ) -> None:
        """POST (or ``method``) to a daemon endpoint and refresh coordinator state.

        Shared helper for the integration's writable entities
        (number sliders, select dropdowns, action buttons). Logs and
        re-raises on failure so HA surfaces the action as failed in
        the UI. Triggers an immediate coordinator refresh on success
        so the state snaps to whatever the daemon actually applied —
        users don't have to wait up to 30 s for the next poll.
        Daemon errors carry its ``detail`` text instead of "Bad Request".
        """
        url = f"{self.base_url}{path}"
        try:
            async with self._session.request(
                method,
                url,
                json=body,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status >= 400:
                    detail = None
                    with suppress(aiohttp.ClientError, ValueError):
                        payload = await resp.json(content_type=None)
                        if isinstance(payload, dict):
                            detail = payload.get("detail")
                    reason = detail if isinstance(detail, str) and detail else (
                        getattr(resp, "reason", None) or "request failed")
                    _LOGGER.warning(
                        "Reachy Mini %s %s failed: %s %s", method, path, resp.status, reason)
                    raise HomeAssistantError(f"Reachy Mini: {reason} ({resp.status})")
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.warning("Reachy Mini %s %s failed: %s", method, path, err)
            raise HomeAssistantError(f"Reachy Mini {path} failed: {err}") from err
        await self.async_request_refresh()

    async def _async_update_data(self) -> dict[str, Any]:
        """Poll all endpoints in parallel and assemble the unified dict."""
        (status, app_lock, doa, vol_speaker, vol_mic, apps, startup,
         controls) = await asyncio.gather(
            self._fetch_json(ENDPOINT_STATUS),
            self._fetch_json(ENDPOINT_APP_LOCK),
            self._fetch_json(ENDPOINT_DOA),
            self._fetch_json(ENDPOINT_VOLUME_SPEAKER),
            self._fetch_json(ENDPOINT_VOLUME_MIC),
            self._fetch_json(APP_LIST),
            self._fetch_json(ENDPOINT_APP_STARTUP),
            self._poll_controls(),
        )

        # If *every* endpoint is None, the daemon is completely
        # unreachable — propagate as UpdateFailed so HA marks the
        # device unavailable. Otherwise, surface what we have.
        if all(x is None for x in (status, app_lock, doa, vol_speaker, vol_mic)):
            raise UpdateFailed(f"Cannot reach Reachy Mini at {self.base_url}")

        if isinstance(apps, list) and all(
            isinstance(app, dict) and isinstance(app.get("name"), str) and app["name"]
            for app in apps
        ):
            self.installed_apps = sorted({app["name"] for app in apps})

        data: dict[str, Any] = {
            # Identity / health from /api/daemon/status
            "firmware_version": None,
            "hardware_id": None,
            "robot_name": None,
            "daemon_state": None,
            "motor_mode": None,
            "awake": None,
            # App slot from /api/daemon/robot-app-lock-status
            "active_app": None,
            "active_app_transport": None,
            "remote_session_active": None,
            # DoA from /api/state/doa (null when audio disabled)
            "doa_angle_rad": None,
            "doa_speech_detected": None,
            # Audio mixer
            "speaker_volume": None,
            "mic_volume": None,
            # Robot's own Startup app setting from /api/apps/startup-app
            "startup_app": None,
            "startup_app_known": False,
        }

        data.update(controls)

        if isinstance(status, dict):
            data["firmware_version"] = status.get("version")
            data["hardware_id"] = status.get("hardware_id")
            data["robot_name"] = status.get("robot_name")
            daemon_state = status.get("state")
            data["daemon_state"] = daemon_state
            backend = status.get("backend_status") or {}
            motor_mode = backend.get("motor_control_mode")
            data["hardware_error"] = backend.get("error") or status.get("error")
            data["motor_mode"] = motor_mode
            data["awake"] = _derive_awake(motor_mode, daemon_state)

        if isinstance(app_lock, dict):
            data.update(
                _derive_app_slot(app_lock.get("state"), app_lock.get("holder_name"))
            )

        if isinstance(doa, dict):
            data["doa_angle_rad"] = doa.get("angle")
            data["doa_speech_detected"] = doa.get("speech_detected")

        if isinstance(vol_speaker, dict):
            v = vol_speaker.get("volume")
            data["speaker_volume"] = v if isinstance(v, int) and v >= 0 else None

        if isinstance(vol_mic, dict):
            v = vol_mic.get("volume")
            data["mic_volume"] = v if isinstance(v, int) and v >= 0 else None

        if isinstance(startup, dict) and "startup_app" in startup:
            value = startup["startup_app"]
            if value is None or isinstance(value, str):
                data["startup_app"] = value or None
                data["startup_app_known"] = True

        # Keep the last pose through one or two failed reads (e.g. a transient
        # motor bus error) while the backend runs; a move reads a fresh pose.
        if data["full_state"] is not None or data["daemon_state"] != DAEMON_STATE_RUNNING:
            self._missed_poses = 0
        elif self.data and self.data.get("full_state") is not None and self._missed_poses < 2:
            self._missed_poses += 1
            data["full_state"] = self.data["full_state"]

        return data

    async def _poll_controls(self) -> dict[str, Any]:
        """Sample manual-control state on the existing poll, not before each write."""
        from homeassistant.exceptions import HomeAssistantError

        async def read(path):
            try:
                return True, await self.manual_control.request("GET", path)
            except HomeAssistantError:
                return False, None

        app, full, moves = await asyncio.gather(
            read(APP_STATUS), read(FULL_STATE), read(RUNNING_MOVES)
        )
        app_ok, app_value = app
        app_state = None
        if app_ok:
            if app_value is None:
                app_state = "done"
            elif isinstance(app_value, dict):
                candidate = app_value.get("state")
                if candidate in {"starting", "running", "stopping", "done", "error"}:
                    app_state = candidate
        return {
            "app_state": app_state,
            "full_state": full[1] if full[0] and isinstance(full[1], dict) else None,
            "running_moves": moves[1] if moves[0] and isinstance(moves[1], list) else None,
        }

    async def async_load_move_lists(self) -> None:
        """Fetch the move name list for each known dataset (best-effort).

        Called once during ``async_setup_entry`` after the first
        coordinator refresh. Failures (404 from older daemons, network
        blip) leave that dataset absent from ``move_lists`` — the
        matching entities are then simply not created downstream.
        """
        for dataset in RECORDED_MOVE_DATASETS:
            path = ENDPOINT_MOVE_LIST.format(dataset=dataset)
            result = await self._fetch_json(path)
            if isinstance(result, list) and result:
                moves = [str(m) for m in result]
                self.move_lists[dataset] = moves
                # Default the selection so a fresh-install button press
                # works without forcing the user to pick first.
                if self.selected_move.get(dataset) is None:
                    self.selected_move[dataset] = moves[0]
            else:
                _LOGGER.info(
                    "Reachy Mini: no recorded moves available for dataset %s",
                    dataset,
                )

    async def async_play_recorded_move(self, dataset: str, move: str) -> None:
        """POST to the play endpoint; re-raises on HTTP failure.

        Marks a move as playing until the daemon reports none running.
        """
        self.move_playing = True
        self.async_update_listeners()
        try:
            await self.async_post(
                ENDPOINT_MOVE_PLAY.format(dataset=dataset, move=move)
            )
        except BaseException:
            self.move_playing = False
            self.async_update_listeners()
            raise
        if self._move_watch is None or self._move_watch.done():
            self._move_watch = self._entry.async_create_background_task(
                self.hass, self._watch_move(), "reachy_mini_move_watch"
            )

    async def _watch_move(self) -> None:
        """Clear ``move_playing`` once the daemon reports no running move."""
        try:
            for _ in range(MOVE_WATCH_LIMIT):
                await asyncio.sleep(MOVE_WATCH_INTERVAL)
                if await self._fetch_json(RUNNING_MOVES) == []:
                    break
        finally:
            self.move_playing = False
            self.async_update_listeners()
        await self.async_request_refresh()

    async def async_load_apps(self) -> None:
        """Refresh installed choices without changing the robot's Startup app."""
        self.installed_apps = await self.app_control.installed_apps()
