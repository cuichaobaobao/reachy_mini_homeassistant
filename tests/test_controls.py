"""0.2.7 gating: app buttons, recorded moves, Startup app, errors and pose grace."""
import json
from pathlib import Path
from unittest.mock import AsyncMock, call, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.reachy_mini.button import (
    BUTTONS, PLAY_MOVE_BUTTONS, ReachyMiniButton, ReachyMiniGotoSleepButton,
    ReachyMiniPlayMoveButton,
)
from custom_components.reachy_mini.const import DANCES_DATASET
from custom_components.reachy_mini.number import ReachyMiniMotionNumber
from custom_components.reachy_mini.select import ReachyMiniAppSelect, ReachyMiniStartupAppSelect
from .conftest import BASE_URL
from .test_manual_control import ready

COMPONENT = Path(__file__).parents[1] / "custom_components" / "reachy_mini"


def button(coordinator, entry, key):
    return ReachyMiniButton(coordinator, entry, next(d for d in BUTTONS if d.key == key))


@pytest.mark.parametrize("key", ["stop_current_app", "restart_current_app"])
async def test_app_buttons_need_a_running_app(coordinator, config_entry, aioclient_mock, key):
    coordinator.async_set_updated_data(ready())
    entity = button(coordinator, config_entry, key)
    assert not entity.available
    with pytest.raises(HomeAssistantError, match="No app is currently running"):
        await entity.async_press()
    assert not aioclient_mock.mock_calls
    for state in ("starting", "running"):
        coordinator.data["app_state"] = state
        assert entity.available
    for state in ("stopping", "done", "error", None):
        coordinator.data["app_state"] = state
        assert not entity.available


async def test_daemon_error_detail_is_shown(coordinator, config_entry, aioclient_mock):
    coordinator.async_set_updated_data({**ready(), "app_state": "running"})
    aioclient_mock.post(BASE_URL + "/api/apps/stop-current-app", status=400,
                        json={"detail": "No app is currently running"})
    with pytest.raises(HomeAssistantError, match="No app is currently running"):
        await button(coordinator, config_entry, "stop_current_app").async_press()


async def test_other_buttons_keep_their_behavior(coordinator, config_entry):
    coordinator.async_set_updated_data({"daemon_state": "stopped"})
    assert button(coordinator, config_entry, "play_test_sound").available
    assert button(coordinator, config_entry, "restart_daemon").available


@pytest.fixture
def dance(coordinator, config_entry):
    coordinator.async_set_updated_data(ready())
    coordinator.async_request_refresh = AsyncMock()
    coordinator.move_lists[DANCES_DATASET] = ["simple_nod"]
    coordinator.selected_move[DANCES_DATASET] = "simple_nod"
    description = next(d for d in PLAY_MOVE_BUTTONS if d.key == "play_dance")
    return ReachyMiniPlayMoveButton(coordinator, config_entry, description)


@pytest.mark.parametrize("patch_data", [
    {"awake": False}, {"awake": None}, {"daemon_state": "stopped"},
])
async def test_play_buttons_wait_only_for_sleep(dance, aioclient_mock, patch_data):
    dance.coordinator.data.update(patch_data)
    assert not dance.available
    with pytest.raises(HomeAssistantError, match="asleep"):
        await dance.async_press()
    assert not aioclient_mock.mock_calls


@pytest.mark.parametrize("patch_data", [
    {"app_state": "running"}, {"active_app": "voice"}, {"remote_session_active": True},
    {"running_moves": [{"uuid": "u"}]},
])
async def test_play_buttons_allowed_while_awake(dance, patch_data):
    dance.coordinator.data.update(patch_data)
    assert dance.available


async def test_play_blocks_manual_controls_until_move_ends(dance, config_entry, aioclient_mock):
    c = dance.coordinator
    aioclient_mock.post(
        f"{BASE_URL}/api/move/play/recorded-move-dataset/{DANCES_DATASET}/simple_nod",
        json={"uuid": "u"})
    replies = [[{"uuid": "u"}], [{"uuid": "u"}], []]
    async def fetch(path):
        assert path == "/api/move/running"
        return replies.pop(0)
    slider = ReachyMiniMotionNumber(c, config_entry, "head_yaw")
    assert dance.available and slider.available
    with (
        patch.object(c, "_fetch_json", AsyncMock(side_effect=fetch)),
        patch("custom_components.reachy_mini.coordinator.MOVE_WATCH_INTERVAL", 0.01),
    ):
        await dance.async_press()
        assert c.move_playing
        assert dance.available and not slider.available
        await c._move_watch
    assert not replies
    assert not c.move_playing
    assert dance.available and slider.available


async def test_failed_play_clears_the_flag(dance, aioclient_mock):
    aioclient_mock.post(
        f"{BASE_URL}/api/move/play/recorded-move-dataset/{DANCES_DATASET}/simple_nod",
        status=503, json={"detail": "Backend not running"})
    with pytest.raises(HomeAssistantError, match="Backend not running"):
        await dance.async_press()
    assert not dance.coordinator.move_playing


async def test_startup_app_select_reads_and_writes(coordinator, config_entry):
    coordinator.installed_apps = ["reachy_mini_ha_voice", "other"]
    coordinator.async_set_updated_data(
        {"startup_app_known": True, "startup_app": "reachy_mini_ha_voice"})
    select = ReachyMiniStartupAppSelect(coordinator, config_entry)
    assert select.available
    assert select.options == ["None", "reachy_mini_ha_voice", "other"]
    assert select.current_option == "reachy_mini_ha_voice"
    with patch.object(coordinator, "async_post", AsyncMock()) as post:
        await select.async_select_option("None")
        await select.async_select_option("other")
        with pytest.raises(HomeAssistantError):
            await select.async_select_option("missing")
    assert post.await_args_list == [
        call("/api/apps/startup-app", method="PUT", body={"startup_app": None}),
        call("/api/apps/startup-app", method="PUT", body={"startup_app": "other"}),
    ]
    coordinator.data["startup_app"] = None
    assert select.current_option == "None"
    coordinator.data["startup_app"] = "removed_app"
    assert "removed_app" in select.options
    coordinator.data["startup_app_known"] = False
    assert not select.available and select.current_option is None


def mock_poll(aioclient_mock, *, startup, full_status=200, state="running"):
    aioclient_mock.get(BASE_URL + "/api/daemon/status", json={
        "state": state, "backend_status": {"motor_control_mode": "enabled"}})
    aioclient_mock.get(BASE_URL + "/api/daemon/robot-app-lock-status", json={"state": "free"})
    aioclient_mock.get(BASE_URL + "/api/apps/list-available/installed", json=[])
    for path in ("/api/state/doa", "/api/volume/current", "/api/volume/microphone/current"):
        aioclient_mock.get(BASE_URL + path, status=503)
    aioclient_mock.get(BASE_URL + "/api/apps/current-app-status", text="null")
    aioclient_mock.get(BASE_URL + "/api/move/running", json=[])
    aioclient_mock.get(BASE_URL + "/api/apps/startup-app", **startup)
    if full_status == 200:
        aioclient_mock.get(BASE_URL + "/api/state/full", json=ready()["full_state"])
    else:
        aioclient_mock.get(BASE_URL + "/api/state/full", status=full_status)


@pytest.mark.parametrize("reply,known,value", [
    ({"json": {"startup_app": "voice"}}, True, "voice"),
    ({"json": {"startup_app": None}}, True, None),
    ({"json": {}}, False, None),
    ({"json": {"startup_app": 3}}, False, None),
    ({"status": 503}, False, None),
])
async def test_poll_reads_startup_app(coordinator, aioclient_mock, reply, known, value):
    mock_poll(aioclient_mock, startup=reply)
    data = await coordinator._async_update_data()
    assert (data["startup_app_known"], data["startup_app"]) == (known, value)


async def test_pose_survives_two_failed_reads_only(coordinator, aioclient_mock):
    mock_poll(aioclient_mock, startup={"status": 503})
    coordinator.async_set_updated_data(await coordinator._async_update_data())
    assert coordinator.data["full_state"] is not None
    for kept in (True, True, False):
        aioclient_mock.clear_requests()
        mock_poll(aioclient_mock, startup={"status": 503}, full_status=500)
        coordinator.async_set_updated_data(await coordinator._async_update_data())
        assert (coordinator.data["full_state"] is not None) is kept


async def test_stopped_backend_never_keeps_a_stale_pose(coordinator, aioclient_mock):
    mock_poll(aioclient_mock, startup={"status": 503})
    coordinator.async_set_updated_data(await coordinator._async_update_data())
    aioclient_mock.clear_requests()
    mock_poll(aioclient_mock, startup={"status": 503}, full_status=503, state="stopped")
    assert (await coordinator._async_update_data())["full_state"] is None


def test_display_names(coordinator, config_entry):
    assert ReachyMiniGotoSleepButton(coordinator, config_entry).entity_description.name == "Go to sleep"
    assert ReachyMiniAppSelect(coordinator, config_entry).entity_description.name == "App to start"
    strings = json.loads((COMPONENT / "strings.json").read_text())["entity"]
    assert strings["button"]["goto_sleep"]["name"] == "Go to sleep"
    assert strings["select"]["app"]["name"] == "App to start"
    assert strings["select"]["startup_app"]["name"] == "Startup app"
