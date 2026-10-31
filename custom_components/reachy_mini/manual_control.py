"""Manual controls using cached state and the desktop's set_target REST fallback.

No SDK dependency, control-slot acquisition or app/slot/motor preflight GETs.
Aligned with the desktop controller: targets are clamped into its ranges, the
head/body yaw limit is left to the daemon's automatic body yaw, a movement
continues from the last target HA sent unless the robot was moved elsewhere,
and Head X, pitch and yaw use the desktop's display signs. A single writer
sends a short, paced trajectory; a newer command during it is folded into the
same trajectory.
"""
from __future__ import annotations

import asyncio
import copy
import math
from typing import Any

import aiohttp
from homeassistant.exceptions import HomeAssistantError

HEAD_KEYS = ("x", "y", "z", "roll", "pitch", "yaw")
BODY_LIMIT = math.radians(160)
LIMITS = {
    "head_x": (-0.05, 0.05, 0.001, "m"),
    "head_y": (-0.05, 0.05, 0.001, "m"),
    "head_z": (-0.05, 0.05, 0.001, "m"),
    "head_roll": (-0.5, 0.5, 0.01, "rad"),
    "head_pitch": (-0.8, 0.8, 0.01, "rad"),
    "head_yaw": (-1.2, 1.2, 0.01, "rad"),
    "body_yaw": (-BODY_LIMIT, BODY_LIMIT, 0.01, "rad"),
    "left_antenna": (-BODY_LIMIT, BODY_LIMIT, 0.01, "rad"),
    "right_antenna": (-BODY_LIMIT, BODY_LIMIT, 0.01, "rad"),
}
NAMES = {
    "head_x": "Head X", "head_y": "Head Y", "head_z": "Head Z",
    "head_roll": "Head roll", "head_pitch": "Head pitch", "head_yaw": "Head yaw",
    "body_yaw": "Body yaw", "left_antenna": "Left antenna",
    "right_antenna": "Right antenna",
}
# The desktop shows these axes with the API sign inverted (ROBOT_TO_API_MAPPINGS):
# positive is forward, up and right on screen.
DISPLAY_SIGN = {"head_x": -1.0, "head_pitch": -1.0, "head_yaw": -1.0}
# Desktop INPUT_THRESHOLDS.MAJOR_CHANGE: a larger gap means the robot moved elsewhere.
MAJOR_CHANGE = 0.1
FULL_STATE = "/api/state/full"
APP_STATUS = "/api/apps/current-app-status"
RUNNING_MOVES = "/api/move/running"
SET_TARGET = "/api/move/set_target"
NOT_READY = "Robot is not ready for manual control; check its state and active app"
POSE_ERROR = "Cannot read the current pose; nothing was sent"


def finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def wrap(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def pose_from_state(state: Any) -> dict | None:
    if not isinstance(state, dict):
        return None
    head, body, antennas = state.get("head_pose"), state.get("body_yaw"), state.get("antennas_position")
    if (not isinstance(head, dict) or not all(finite(head.get(k)) for k in HEAD_KEYS)
            or not finite(body) or not isinstance(antennas, (tuple, list))
            or len(antennas) != 2 or not all(finite(a) for a in antennas)):
        return None
    return {"target_head_pose": {k: float(head[k]) for k in HEAD_KEYS},
            "target_body_yaw": float(body), "target_antennas": list(antennas)}


def cached_ready(data: dict, *, power_off: bool = False) -> bool:
    """Use normal coordinator updates; do not query or acquire the app slot."""
    return (
        data.get("daemon_state") == "running"
        and data.get("app_state") in ("done", "error")
        and data.get("active_app") is None
        and data.get("remote_session_active") is False
        and data.get("running_moves") == []
        and not data.get("hardware_error")
        and (power_off or data.get("awake") is True)
    )


def value_of(pose: dict, key: str) -> float:
    """The value shown in HA: the API value with the desktop's display sign."""
    if key.startswith("head_"):
        value = pose["target_head_pose"][key[5:]]
    elif key == "body_yaw":
        value = pose["target_body_yaw"]
    else:
        value = pose["target_antennas"][0 if key == "left_antenna" else 1]
    return DISPLAY_SIGN.get(key, 1.0) * value


def pose_distance(a: dict, b: dict) -> float:
    """Sum of absolute differences, like the desktop's poseSnapshotDistance."""
    return (
        sum(abs(a["target_head_pose"][k] - b["target_head_pose"][k]) for k in HEAD_KEYS)
        + abs(a["target_body_yaw"] - b["target_body_yaw"])
        + sum(abs(x - y) for x, y in zip(a["target_antennas"], b["target_antennas"]))
    )


def rotate_with_body(head: dict, delta: float) -> dict:
    """Rz(delta) * world head transform: preserve the complete body-relative pose."""
    result = dict(head)
    c, s = math.cos(delta), math.sin(delta)
    result["x"] = c * head["x"] - s * head["y"]
    result["y"] = s * head["x"] + c * head["y"]
    result["yaw"] = wrap(head["yaw"] + delta)
    return result


def clamp_into_limits(pose: dict, follows: bool, around: dict | None = None) -> dict:
    """Clamp into the desktop ranges, widened only to ``around`` (where the robot already is)."""
    result = copy.deepcopy(pose)
    head = result["target_head_pose"]
    near = around["target_head_pose"] if around is not None else None
    for key in HEAD_KEYS:
        low, high, _, _ = LIMITS["head_" + key]
        if key == "yaw" and follows:
            low, high = -math.pi, math.pi
        if near is not None:
            low, high = min(low, near[key]), max(high, near[key])
        head[key] = min(max(head[key], low), high)
    body = BODY_LIMIT if around is None else max(BODY_LIMIT, abs(around["target_body_yaw"]))
    result["target_body_yaw"] = min(max(result["target_body_yaw"], -body), body)
    limits = ([BODY_LIMIT, BODY_LIMIT] if around is None
              else [max(BODY_LIMIT, abs(a)) for a in around["target_antennas"]])
    result["target_antennas"] = [min(max(a, -limit), limit)
                                 for a, limit in zip(result["target_antennas"], limits)]
    return result


def make_target(start: dict, key: str, value: float | None, follows: bool) -> dict:
    """Like the desktop: values outside a range are clamped, not rejected."""
    target = copy.deepcopy(start)
    head = target["target_head_pose"]
    if key in LIMITS:
        if not finite(value):
            raise HomeAssistantError(f"{NAMES[key]} must be a number")
        value = DISPLAY_SIGN.get(key, 1.0) * value
        if key.startswith("head_"):
            head[key[5:]] = value
        elif key == "body_yaw":
            value = min(max(value, -BODY_LIMIT), BODY_LIMIT)
            target["target_body_yaw"] = value
            if follows:
                target["target_head_pose"] = rotate_with_body(head, value - start["target_body_yaw"])
        else:
            target["target_antennas"][0 if key == "left_antenna" else 1] = value
    elif key in ("center_head", "center_body", "center_all"):
        if key in ("center_body", "center_all"):
            target["target_body_yaw"] = 0.0
            if follows:
                target["target_head_pose"] = rotate_with_body(head, -start["target_body_yaw"])
        if key in ("center_head", "center_all"):
            target["target_head_pose"] = {k: 0.0 for k in HEAD_KEYS}
            if follows and key == "center_head":
                target["target_head_pose"]["yaw"] = target["target_body_yaw"]
        if key == "center_all":
            # Match the desktop reset, not the sleep pose.
            target["target_antennas"] = [0.0, 0.0]
    else:
        raise HomeAssistantError("Unknown manual control")
    # The head/body relative yaw is left to the daemon's automatic body yaw.
    return clamp_into_limits(target, follows)


def interpolate(start: dict, end: dict, t: float, *, linked_body: bool = False) -> dict:
    """Smoothstep in one coordinated frame; link remains exact along the path."""
    b = t * t * (3.0 - 2.0 * t)
    result = copy.deepcopy(start)
    body = start["target_body_yaw"] + b * (end["target_body_yaw"] - start["target_body_yaw"])
    result["target_body_yaw"] = body
    if linked_body:
        result["target_head_pose"] = rotate_with_body(
            start["target_head_pose"], body - start["target_body_yaw"])
    else:
        for key in HEAD_KEYS:
            a, z = start["target_head_pose"][key], end["target_head_pose"][key]
            delta = wrap(z - a) if key == "yaw" else z - a
            result["target_head_pose"][key] = wrap(a + b * delta) if key == "yaw" else a + b * delta
    result["target_antennas"] = [
        a + b * (z - a) for a, z in zip(start["target_antennas"], end["target_antennas"])
    ]
    return result


class ManualControl:
    def __init__(self, coordinator) -> None:
        self.coordinator = coordinator
        self.follows = False
        self.duration = 1.0
        self._powering = False
        self._task: asyncio.Task | None = None
        # One writer per robot. A newer command replaces its frames in place.
        self._worker: asyncio.Task | None = None
        self._frames: list[dict] | None = None
        self._goal: dict | None = None
        self._sent: dict | None = None
        self._done: asyncio.Future | None = None
        # Last target the daemon accepted from HA; the next movement starts here.
        self._last: dict | None = None

    @property
    def busy(self) -> bool:
        return self._powering or self._worker is not None

    def available(self, *, power_off: bool = False) -> bool:
        c = self.coordinator
        # Our own movement holds the command lock but must not grey out the controls.
        if self._worker is not None:
            lock_ok = not power_off
        else:
            lock_ok = not c.app_command_lock.locked()
        return (
            c.last_update_success and lock_ok and not self._powering and not c.move_playing
            and cached_ready(c.data or {}, power_off=power_off)
            and (power_off or pose_from_state((c.data or {}).get("full_state")) is not None)
        )

    async def request(self, method: str, path: str, body: dict | None = None) -> Any:
        c = self.coordinator
        try:
            async with c._session.request(
                method, c.base_url + path, json=body,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as response:
                response.raise_for_status()
                return await response.json()
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise HomeAssistantError(f"Reachy Mini {path} failed") from err

    def _begin(self) -> None:
        if not self.available(power_off=True):
            raise HomeAssistantError(NOT_READY)
        self._powering = True
        self._task = asyncio.current_task()
        self.coordinator.async_update_listeners()

    async def _finish(self) -> None:
        self._powering = False
        self._task = None
        self.coordinator.async_update_listeners()
        await self.coordinator.async_request_refresh()

    async def move(self, key: str, value: float | None = None) -> None:
        if not self.available():
            raise HomeAssistantError(NOT_READY)
        origin = None
        if self._worker is None:
            try:
                measured = pose_from_state(await self.request("GET", FULL_STATE))
            except HomeAssistantError as err:
                raise HomeAssistantError(POSE_ERROR) from err
            if measured is None:
                raise HomeAssistantError(POSE_ERROR)
            if not self.available():
                raise HomeAssistantError(NOT_READY)
            # Like the desktop, continue from our last target; only a larger gap
            # means something else moved the robot (an app, a move, sleep).
            last = self._last
            if last is not None and pose_distance(measured, last) <= MAJOR_CHANGE:
                origin = last
            else:
                origin = measured
        merging = self._worker is not None
        # While moving, continue from the frame being sent toward the combined goal.
        # A measured pose may sit slightly past a limit (e.g. roll 0.53 after a
        # 0.5 target); the new goal pulls such an axis back onto the limit.
        if merging:
            start, base = self._sent, self._goal
        else:
            start, base = origin, clamp_into_limits(origin, self.follows)
        end = make_target(base, key, value, self.follows)
        linked = (not merging and base == start and self.follows
                  and key in ("body_yaw", "center_body"))
        steps = max(1, math.ceil(self.duration / 0.05))
        # Every sampled frame is clamped; it may stay where the robot already is
        # but never goes further out.
        frames = [clamp_into_limits(interpolate(start, end, i / steps, linked_body=linked),
                                    self.follows, around=start)
                  for i in range(1, steps + 1)]
        if self._done is not None and not self._done.done():
            self._done.set_result(None)  # the earlier goal is part of this one
        self._goal, self._frames = end, frames
        self._done = done = asyncio.get_running_loop().create_future()
        if not merging:
            self._sent = start
            self._worker = asyncio.create_task(self._run())
            self.coordinator.async_update_listeners()
        await asyncio.shield(done)

    async def _run(self) -> None:
        c = self.coordinator
        loop = asyncio.get_running_loop()
        error: BaseException | None = None
        try:
            async with c.app_command_lock:
                while True:
                    frames = self._frames
                    step = self.duration / len(frames)
                    began = loop.time()
                    for i, frame in enumerate(frames, 1):
                        await asyncio.sleep(max(0, began + i * step - loop.time()))
                        if self._frames is not frames:
                            break
                        # Cached changes (e.g. a normal poll observes an app start)
                        # can stop a sequence, without per-command preflight GETs.
                        if (not c.last_update_success or c.move_playing
                                or not cached_ready(c.data or {})):
                            raise HomeAssistantError("Robot state changed during manual movement")
                        self._sent = frame
                        result = await self.request("POST", SET_TARGET, frame)
                        if isinstance(result, dict) and result.get("status") == "ignored":
                            raise HomeAssistantError(
                                "A recorded move is playing; try again when it finishes")
                        if not isinstance(result, dict) or result.get("status") != "ok":
                            raise HomeAssistantError("Daemon did not accept the manual target")
                        self._last = frame
                        # Do not burst delayed frames after a slow network request.
                        began = max(began, loop.time() - i * step)
                    else:
                        if self._frames is frames:
                            break
        except asyncio.CancelledError as err:
            error = err
            raise
        except Exception as err:  # reported to the waiting caller
            error = err
        finally:
            done = self._done
            self._worker = self._frames = self._goal = self._sent = self._done = None
            c.async_update_listeners()
            if isinstance(error, asyncio.CancelledError) and done is not None and not done.done():
                done.cancel()
        await c.async_request_refresh()
        if done is not None and not done.done():
            if error is None:
                done.set_result(None)
            else:
                done.set_exception(error)

    async def power_off(self) -> None:
        self._begin()
        try:
            async with self.coordinator.app_command_lock:
                # Configuration lookup, not an app/slot/motor preflight.
                config = await self.request("GET", "/api/apps/startup-app")
                if not isinstance(config, dict) or "startup_app" not in config:
                    raise HomeAssistantError("Cannot determine Startup app configuration")
                startup = config["startup_app"]
                if startup is not None and (not isinstance(startup, str) or not startup):
                    raise HomeAssistantError("Invalid Startup app configuration")
                result = await self.request("POST", "/api/move/play/goto_sleep")
                await asyncio.sleep(6 if isinstance(result, dict) and result.get("uuid") else 4)
                await self.request("POST", "/api/motors/set_mode/disabled")
                await asyncio.sleep(0.3)
                if not startup:
                    await self.coordinator.app_control._backend_job(
                        "/api/daemon/stop?goto_sleep=false", "stopped")
        finally:
            await self._finish()

    async def close(self) -> None:
        """Stop in-flight HA sequences on unload; never leave a writer running."""
        for task in (self._worker, self._task):
            if task is not None and task is not asyncio.current_task():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
