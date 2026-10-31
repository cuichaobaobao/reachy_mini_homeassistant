"""Manual control contracts with real HA entities and an in-memory daemon."""
import asyncio
import copy
import math
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.reachy_mini.manual_control import (
    HEAD_KEYS, LIMITS, BODY_LIMIT, ManualControl, cached_ready,
    interpolate, make_target, pose_from_state, rotate_with_body, validate_target,
)
from custom_components.reachy_mini.number import ReachyMiniMotionNumber, ReachyMiniDurationNumber
from custom_components.reachy_mini.button import ReachyMiniManualButton
from custom_components.reachy_mini.switch import ReachyMiniHeadFollowsBody
from .conftest import BASE_URL

SLEEP = "custom_components.reachy_mini.manual_control.asyncio.sleep"


def ready():
    return dict(
        daemon_state="running", motor_mode="enabled", awake=True, app_state="done",
        active_app=None, remote_session_active=False, running_moves=[],
        full_state=dict(head_pose={k: 0.0 for k in HEAD_KEYS},
                        body_yaw=0.0, antennas_position=[-0.1745, 0.1745]),
    )


def daemon(control, post=None):
    """In-memory daemon: the pose GET returns the cached pose, POSTs answer ok."""
    async def request(method, path, body=None):
        if method == "GET" and path == "/api/state/full":
            return copy.deepcopy(control.coordinator.data["full_state"])
        if post is not None:
            return await post(method, path, body)
        return {"status": "ok"}
    return request


def posts(control):
    return [call.args for call in control.request.await_args_list if call.args[0] == "POST"]


@pytest.fixture
def manual(coordinator):
    coordinator.async_set_updated_data(ready())
    coordinator.async_request_refresh = AsyncMock()
    control = coordinator.manual_control
    control.request = AsyncMock(side_effect=daemon(control))
    control.duration = 0.1
    return control


@pytest.mark.parametrize("patch_data", [
    {"app_state": "running"}, {"app_state": "starting"}, {"app_state": "stopping"},
    {"app_state": None}, {"daemon_state": "stopped"}, {"awake": False},
    {"running_moves": [{"uuid": "other"}]}, {"running_moves": None},
    {"active_app": "voice"}, {"remote_session_active": True},
    {"hardware_error": "overload"}, {"full_state": None},
])
async def test_blocked_controls_do_not_send(manual, patch_data):
    manual.coordinator.data.update(patch_data)
    with pytest.raises(HomeAssistantError):
        await manual.move("head_yaw", 0.2)
    manual.request.assert_not_awaited()


async def test_recorded_move_from_ha_blocks_manual_control(manual):
    manual.coordinator.move_playing = True
    assert not manual.available()
    with pytest.raises(HomeAssistantError):
        await manual.move("head_yaw", 0.2)
    manual.request.assert_not_awaited()


async def test_one_fresh_pose_read_and_untouched_axes_kept(manual):
    data = manual.coordinator.data["full_state"]
    data["head_pose"].update(pitch=0.1, z=0.005)
    with patch(SLEEP, AsyncMock()):
        await manual.move("head_yaw", 0.3)
    calls = [call.args[:2] for call in manual.request.await_args_list]
    assert calls[0] == ("GET", "/api/state/full")
    assert calls[1:] and all(call == ("POST", "/api/move/set_target") for call in calls[1:])
    target = manual.request.await_args.args[2]
    assert target["target_head_pose"]["yaw"] == pytest.approx(0.3)
    assert target["target_head_pose"]["pitch"] == 0.1
    assert target["target_head_pose"]["z"] == 0.005
    assert target["target_antennas"] == [-0.1745, 0.1745]
    manual.coordinator.async_request_refresh.assert_awaited_once()
    assert not manual.busy


async def test_fresh_pose_wins_over_cached_pose(manual):
    cached = copy.deepcopy(manual.coordinator.data["full_state"])
    actual = copy.deepcopy(cached)
    actual["head_pose"]["pitch"] = 0.3
    async def request(method, path, body=None):
        return actual if method == "GET" else {"status": "ok"}
    manual.request.side_effect = request
    with patch(SLEEP, AsyncMock()):
        await manual.move("head_yaw", 0.1)
    assert posts(manual)[-1][2]["target_head_pose"]["pitch"] == 0.3


@pytest.mark.parametrize("reply", [HomeAssistantError("Motor communication error"), {"status": "ok"}])
async def test_failed_fresh_pose_read_sends_nothing(manual, reply):
    async def request(method, path, body=None):
        if isinstance(reply, Exception):
            raise reply
        return reply
    manual.request.side_effect = request
    with pytest.raises(HomeAssistantError, match="current pose"):
        await manual.move("head_yaw", 0.2)
    assert manual.request.await_count == 1
    assert not manual.busy


@pytest.mark.parametrize("key,value", [
    ("head_x", 0.051), ("head_pitch", 0.81), ("head_yaw", 1.21),
    ("head_roll", 0.51), ("body_yaw", math.pi),
    ("left_antenna", math.pi), ("head_yaw", float("nan")),
    ("head_yaw", float("inf")), ("head_yaw", True),
])
async def test_invalid_targets_send_nothing(manual, key, value):
    with pytest.raises(HomeAssistantError):
        await manual.move(key, value)
    assert posts(manual) == []
    assert not manual.busy


def test_linked_rotation_preserves_body_relative_translation_and_orientation():
    start = pose_from_state(ready()["full_state"])
    start["target_body_yaw"] = 0.2
    start["target_head_pose"].update(x=0.01, y=0.005, pitch=0.2, roll=0.1, yaw=0.3)
    end = make_target(start, "body_yaw", 2.0, True)
    for t in (0, 0.1, 0.5, 0.9, 1):
        p = interpolate(start, end, t, linked_body=True)
        relative = rotate_with_body(p["target_head_pose"], -p["target_body_yaw"])
        expected = rotate_with_body(start["target_head_pose"], -start["target_body_yaw"])
        for key in HEAD_KEYS:
            assert relative[key] == pytest.approx(expected[key])
        validate_target(p, True)
    assert end["target_head_pose"]["yaw"] == pytest.approx(2.1)


def test_unlinked_body_keeps_world_head_pose():
    start = pose_from_state(ready()["full_state"])
    target = make_target(start, "body_yaw", 0.4, False)
    assert target["target_head_pose"] == start["target_head_pose"]


def test_relative_yaw_rejected_instead_of_silently_moving_body():
    start = pose_from_state(ready()["full_state"])
    with pytest.raises(HomeAssistantError, match="relative yaw"):
        make_target(start, "body_yaw", 2.0, False)


def test_linked_rotation_checks_translated_xy_limits():
    start = pose_from_state(ready()["full_state"])
    start["target_head_pose"].update(x=0.05, y=0.05)
    with pytest.raises(HomeAssistantError, match="Combined pose"):
        make_target(start, "body_yaw", math.pi / 4, True)


def test_center_contracts():
    start = pose_from_state(ready()["full_state"])
    start["target_body_yaw"] = 0.4
    start["target_head_pose"].update(yaw=0.6, pitch=0.2)
    head = make_target(start, "center_head", None, True)
    assert head["target_head_pose"]["yaw"] == pytest.approx(0.4)
    assert head["target_body_yaw"] == 0.4
    body = make_target(start, "center_body", None, True)
    assert body["target_head_pose"]["yaw"] == pytest.approx(0.2)
    assert body["target_head_pose"]["pitch"] == 0.2
    all_pose = make_target(start, "center_all", None, True)
    assert all(v == 0 for v in all_pose["target_head_pose"].values())
    assert all_pose["target_body_yaw"] == 0
    assert all_pose["target_antennas"] == [0, 0]


async def test_switch_only_changes_local_preference(manual, config_entry):
    switch = ReachyMiniHeadFollowsBody(manual.coordinator, config_entry)
    assert not switch.is_on
    await switch.async_turn_on()
    assert switch.is_on
    manual.request.assert_not_awaited()
    await switch.async_turn_off()
    assert not switch.is_on


async def test_ignored_set_target_reports_playing_move(manual):
    async def post(method, path, body):
        return {"status": "ignored", "reason": "move_running"}
    manual.request.side_effect = daemon(manual, post)
    with patch(SLEEP, AsyncMock()):
        with pytest.raises(HomeAssistantError, match="recorded move"):
            await manual.move("head_yaw", 0.2)
    assert len(posts(manual)) == 1
    assert not manual.busy


async def test_rejected_set_target_is_not_success(manual):
    async def post(method, path, body):
        return {"status": "error"}
    manual.request.side_effect = daemon(manual, post)
    with patch(SLEEP, AsyncMock()):
        with pytest.raises(HomeAssistantError, match="did not accept"):
            await manual.move("head_yaw", 0.2)
    assert len(posts(manual)) == 1
    assert not manual.busy


async def test_normal_poll_can_interrupt_sequence(manual):
    async def post(method, path, body):
        manual.coordinator.data["app_state"] = "running"
        return {"status": "ok"}
    manual.request.side_effect = daemon(manual, post)
    with patch(SLEEP, AsyncMock()):
        with pytest.raises(HomeAssistantError, match="state changed"):
            await manual.move("head_yaw", 0.2)
    assert len(posts(manual)) == 1


async def test_unload_cancels_writer(manual):
    entered = asyncio.Event()
    async def post(method, path, body):
        entered.set()
        await asyncio.Event().wait()
    manual.request.side_effect = daemon(manual, post)
    task = asyncio.create_task(manual.move("head_yaw", 0.2))
    await entered.wait()
    await manual.close()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()
    assert not manual.busy
    assert not manual.coordinator.app_command_lock.locked()


async def test_own_movement_keeps_controls_available_and_merges(manual, config_entry):
    gate = asyncio.Event()
    async def post(method, path, body):
        await gate.wait()
        return {"status": "ok"}
    manual.request.side_effect = daemon(manual, post)
    manual.duration = 0.2
    first = asyncio.create_task(manual.move("head_yaw", 0.3))
    while not posts(manual):
        await asyncio.sleep(0)
    slider = ReachyMiniMotionNumber(manual.coordinator, config_entry, "head_pitch")
    center = ReachyMiniManualButton(manual.coordinator, config_entry, "center_head", "Center head")
    power = ReachyMiniManualButton(manual.coordinator, config_entry, "power_off", "Power Off")
    assert slider.available and center.available
    assert not power.available
    second = asyncio.create_task(manual.move("head_pitch", 0.2))
    await asyncio.sleep(0)
    gate.set()
    await asyncio.wait_for(asyncio.gather(first, second), 5)
    final = posts(manual)[-1][2]["target_head_pose"]
    assert final["yaw"] == pytest.approx(0.3)
    assert final["pitch"] == pytest.approx(0.2)
    assert [c.args[0] for c in manual.request.await_args_list].count("GET") == 1
    assert not manual.busy and slider.available


async def test_power_off_is_refused_during_movement(manual):
    gate = asyncio.Event()
    async def post(method, path, body):
        await gate.wait()
        return {"status": "ok"}
    manual.request.side_effect = daemon(manual, post)
    task = asyncio.create_task(manual.move("head_yaw", 0.2))
    while not posts(manual):
        await asyncio.sleep(0)
    with pytest.raises(HomeAssistantError):
        await manual.power_off()
    gate.set()
    await asyncio.wait_for(task, 5)
    assert all(call[1] == "/api/move/set_target" for call in posts(manual))


async def test_existing_lifecycle_lock_blocks_new_motion(manual):
    async with manual.coordinator.app_command_lock:
        with pytest.raises(HomeAssistantError):
            await manual.move("head_yaw", 0.2)
    manual.request.assert_not_awaited()


@pytest.mark.parametrize("startup", [None, "reachy_mini_ha_voice"])
async def test_power_off_startup_app_branch(manual, startup):
    manual.coordinator.data.update(awake=False, motor_mode="disabled")
    async def request(method, path, body=None):
        if path == "/api/apps/startup-app":
            return {"startup_app": startup}
        if path == "/api/move/play/goto_sleep":
            return {"uuid": "sleep"}
        return {}
    manual.request.side_effect = request
    with (
        patch(SLEEP, AsyncMock()),
        patch.object(manual.coordinator.app_control, "_backend_job", AsyncMock()) as stop,
    ):
        await manual.power_off()
        if startup:
            stop.assert_not_awaited()
        else:
            stop.assert_awaited_once_with("/api/daemon/stop?goto_sleep=false", "stopped")
    assert [call.args[:2] for call in manual.request.await_args_list] == [
        ("GET", "/api/apps/startup-app"),
        ("POST", "/api/move/play/goto_sleep"),
        ("POST", "/api/motors/set_mode/disabled"),
    ]


async def test_power_off_never_stops_running_app(manual):
    manual.coordinator.data["app_state"] = "running"
    with pytest.raises(HomeAssistantError):
        await manual.power_off()
    manual.request.assert_not_awaited()


async def test_unknown_startup_config_aborts_without_motion(manual):
    async def request(method, path, body=None):
        return {}
    manual.request.side_effect = request
    with pytest.raises(HomeAssistantError):
        await manual.power_off()
    assert manual.request.await_count == 1


async def test_duration_validation_and_entity_units(manual, config_entry):
    duration = ReachyMiniDurationNumber(manual.coordinator, config_entry)
    for bad in (0, 6, float("nan"), True):
        with pytest.raises(HomeAssistantError):
            await duration.async_set_native_value(bad)
    await duration.async_set_native_value(1.5)
    assert duration.native_value == 1.5
    for key, (_, _, _, unit) in LIMITS.items():
        entity = ReachyMiniMotionNumber(manual.coordinator, config_entry, key)
        assert entity.native_unit_of_measurement == unit
        assert entity.available
    button = ReachyMiniManualButton(manual.coordinator, config_entry, "power_off", "Power Off")
    assert button.available
    manual.request.assert_not_awaited()


async def test_normal_poll_distinguishes_idle_from_failed_query(coordinator, aioclient_mock):
    aioclient_mock.get(BASE_URL + "/api/apps/current-app-status", text="null")
    aioclient_mock.get(BASE_URL + "/api/state/full", json=ready()["full_state"])
    aioclient_mock.get(BASE_URL + "/api/move/running", json=[])
    controls = await coordinator._poll_controls()
    assert controls["app_state"] == "done"
    assert controls["running_moves"] == []
    assert pose_from_state(controls["full_state"]) is not None


async def test_failed_control_poll_does_not_make_other_entities_unavailable(coordinator, aioclient_mock):
    aioclient_mock.get(BASE_URL + "/api/apps/current-app-status", status=503)
    aioclient_mock.get(BASE_URL + "/api/state/full", status=503)
    aioclient_mock.get(BASE_URL + "/api/move/running", status=503)
    assert await coordinator._poll_controls() == {
        "app_state": None, "full_state": None, "running_moves": None}


@pytest.mark.parametrize("failed_path", ["/api/move/play/goto_sleep", "/api/motors/set_mode/disabled"])
async def test_power_off_failure_is_reported_before_backend_stop(manual, failed_path):
    async def request(method, path, body=None):
        if path == "/api/apps/startup-app":
            return {"startup_app": None}
        if path == failed_path:
            raise HomeAssistantError("failed")
        return {"uuid": "sleep"}
    manual.request.side_effect = request
    with (
        patch(SLEEP, AsyncMock()),
        patch.object(manual.coordinator.app_control, "_backend_job", AsyncMock()) as stop,
        pytest.raises(HomeAssistantError),
    ):
        await manual.power_off()
    stop.assert_not_awaited()
    assert not manual.busy


async def test_poll_handles_running_and_stopping_app(coordinator):
    client = coordinator.manual_control
    for state in ("starting", "running", "stopping"):
        async def request(method, path, body=None):
            if path.endswith("current-app-status"):
                return {"state": state, "info": {"name": "voice"}}
            if path.endswith("/full"):
                return ready()["full_state"]
            return []
        with patch.object(client, "request", AsyncMock(side_effect=request)):
            data = ready()
            data.update(await coordinator._poll_controls())
            assert not cached_ready(data)


def test_wrap_boundary_keeps_linked_head_body_offset():
    start = pose_from_state(ready()["full_state"])
    start["target_body_yaw"] = 2.4
    start["target_head_pose"]["yaw"] = 3.1
    end = make_target(start, "body_yaw", 2.7, True)
    assert end["target_head_pose"]["yaw"] < 0
    for t in (0.1, 0.5, 1):
        p = interpolate(start, end, t, linked_body=True)
        validate_target(p, True)
        relative = rotate_with_body(p["target_head_pose"], -p["target_body_yaw"])
        assert relative["yaw"] == pytest.approx(0.7)
