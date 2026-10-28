"""App lifecycle safety: fresh reads, stopped backend, errors and concurrent actions."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.core import State

from custom_components.reachy_mini.app_control import (
    AppControl, APP_LIST, APP_STATUS, APP_SLOT, DAEMON_STATUS,
    STOP_APP, START_BACKEND, SLEEP_BACKEND,
)
from custom_components.reachy_mini.button import ReachyMiniStartAppButton
from custom_components.reachy_mini.select import ReachyMiniAppSelect

from .conftest import BASE_URL

APP = "reachy_mini_ha_voice"
START_APP = "/api/apps/start-app/" + APP + "/no-evict"


def status(state="running", name=APP):
    return {"state": state, "info": {"name": name}}


class Robot:
    """An in-memory daemon double with ordered state transitions."""

    def __init__(self, current=None, backend="running", slot="free"):
        self.current = current
        self.backend = backend
        self.slot = slot
        self.apps = [{"name": APP}]
        self.calls = []
        self.fail_stop = False
        self.keep_running = False
        self.job_status = "done"
        self.started_during_backend = None

    async def request(self, method, path):
        self.calls.append((method, path))
        if method == "GET":
            if path == APP_LIST:
                return self.apps
            if path == APP_STATUS:
                return self.current
            if path == APP_SLOT:
                return {"state": self.slot}
            if path == DAEMON_STATUS:
                return {"state": self.backend}
            if path == "/api/apps/job-status/job":
                return {"status": self.job_status}
        if method == "POST":
            if path == STOP_APP:
                if self.fail_stop:
                    raise HomeAssistantError("stop failed")
                if not self.keep_running:
                    self.current = None
                    self.slot = "free"
                return None
            if path == START_BACKEND:
                self.backend = "running"
                if self.started_during_backend:
                    self.current = status(name=self.started_during_backend)
                    self.slot = "local_app"
                return {"job_id": "job"}
            if path == SLEEP_BACKEND:
                self.backend = "stopped"
                return {"job_id": "job"}
            if path == START_APP:
                self.current = status()
                return self.current
        raise AssertionError((method, path))

    @property
    def posts(self):
        return [path for method, path in self.calls if method == "POST"]


def control(robot):
    client = AppControl(None, BASE_URL)
    client._request = robot.request
    return client


async def test_start_running_backend():
    robot = Robot()
    await control(robot).start(APP)
    assert robot.posts == [START_APP]


async def test_start_waits_for_backend_before_app():
    robot = Robot(backend="stopped")
    await control(robot).start(APP)
    assert robot.posts == [START_BACKEND, START_APP]
    assert robot.calls.index(("GET", "/api/apps/job-status/job")) < robot.calls.index(("POST", START_APP))


async def test_start_same_app_is_noop():
    robot = Robot(current=status(), slot="local_app")
    await control(robot).start(APP)
    assert robot.posts == []


@pytest.mark.parametrize("current", [status(name="other"), status("stopping")])
async def test_start_does_not_switch_or_restart(current):
    robot = Robot(current=current, slot="local_app")
    with pytest.raises(HomeAssistantError):
        await control(robot).start(APP)
    assert robot.posts == []


@pytest.mark.parametrize("name", [None, "removed"])
async def test_start_requires_installed_selection(name):
    robot = Robot()
    with pytest.raises(HomeAssistantError):
        await control(robot).start(name)
    assert robot.posts == []


async def test_start_refuses_remote_session():
    robot = Robot(slot="remote_session")
    with pytest.raises(HomeAssistantError):
        await control(robot).start(APP)
    assert robot.posts == []


async def test_start_rechecks_after_backend_start():
    robot = Robot(backend="stopped")
    robot.started_during_backend = "other"
    with pytest.raises(HomeAssistantError):
        await control(robot).start(APP)
    assert robot.posts == [START_BACKEND]


async def test_failed_backend_job_does_not_start_app():
    robot = Robot(backend="stopped")
    robot.job_status = "failed"
    with pytest.raises(HomeAssistantError):
        await control(robot).start(APP)
    assert robot.posts == [START_BACKEND]


async def test_sleep_stops_app_and_confirms_before_backend():
    robot = Robot(current=status(), slot="local_app")
    await control(robot).sleep()
    assert robot.posts == [STOP_APP, SLEEP_BACKEND]
    stop_index = robot.calls.index(("POST", STOP_APP))
    sleep_index = robot.calls.index(("POST", SLEEP_BACKEND))
    assert ("GET", APP_STATUS) in robot.calls[stop_index + 1:sleep_index]
    assert ("GET", APP_SLOT) in robot.calls[stop_index + 1:sleep_index]


async def test_stop_failure_never_requests_backend_shutdown():
    robot = Robot(current=status(), slot="local_app")
    robot.fail_stop = True
    with pytest.raises(HomeAssistantError):
        await control(robot).sleep()
    assert robot.posts == [STOP_APP]


async def test_stop_timeout_never_requests_backend_shutdown():
    robot = Robot(current=status(), slot="local_app")
    robot.keep_running = True
    with (
        patch("custom_components.reachy_mini.app_control.TRANSITION_TIMEOUT", 0.01),
        pytest.raises(HomeAssistantError, match="did not stop"),
    ):
        await control(robot).sleep()
    assert robot.posts == [STOP_APP]


@pytest.mark.parametrize("current", [{"state": "unknown"}, [], {"state": "running"}])
async def test_invalid_app_status_is_not_treated_as_idle(current):
    robot = Robot(current=current)
    with pytest.raises(HomeAssistantError):
        await control(robot).sleep()
    assert robot.posts == []


async def test_sleep_refuses_remote_session():
    robot = Robot(slot="remote_session")
    with pytest.raises(HomeAssistantError):
        await control(robot).sleep()
    assert robot.posts == []


async def test_sleep_already_stopped_still_stops_orphan_app():
    robot = Robot(current=status(), backend="stopped", slot="local_app")
    await control(robot).sleep()
    assert robot.posts == [STOP_APP]


async def test_sleep_with_no_app_stops_only_backend():
    robot = Robot()
    await control(robot).sleep()
    assert robot.posts == [SLEEP_BACKEND]


async def test_sleep_already_stopped_is_noop():
    robot = Robot(backend="stopped")
    await control(robot).sleep()
    assert robot.posts == []


@pytest.mark.parametrize("http_status", [404, 500])
async def test_failed_status_http_is_not_idle(coordinator, aioclient_mock, http_status):
    aioclient_mock.get(BASE_URL + APP_STATUS, status=http_status)
    with pytest.raises(HomeAssistantError):
        await coordinator.app_control.sleep()
    assert all(method == "GET" for method, *_ in aioclient_mock.mock_calls)


async def test_http_null_app_status_is_idle(coordinator, aioclient_mock):
    aioclient_mock.get(BASE_URL + APP_STATUS, json=None)
    assert await coordinator.app_control._current() == (None, "done")


async def test_start_button_uses_selection(coordinator, config_entry):
    coordinator.selected_app = APP
    button = ReachyMiniStartAppButton(coordinator, config_entry)
    with (
        patch.object(coordinator.app_control, "start", AsyncMock()) as start,
        patch.object(coordinator, "async_request_refresh", AsyncMock()),
    ):
        await button.async_press()
    start.assert_awaited_once_with(APP)


async def test_selector_restores_and_never_changes_startup_app(hass, coordinator, config_entry):
    coordinator.installed_apps = [APP, "other"]
    select = ReachyMiniAppSelect(coordinator, config_entry)
    select.hass = hass
    select.entity_id = "select.reachy_app"
    with patch.object(select, "async_get_last_state", AsyncMock(return_value=State(select.entity_id, APP))):
        await select.async_added_to_hass()
    assert select.current_option == APP
    with patch.object(select, "async_write_ha_state"):
        await select.async_select_option("other")
    assert coordinator.selected_app == "other"
    await select.async_will_remove_from_hass()


async def test_removed_selection_is_not_exposed(coordinator, config_entry):
    coordinator.installed_apps = [APP]
    coordinator.selected_app = "removed"
    assert ReachyMiniAppSelect(coordinator, config_entry).current_option is None


async def test_start_is_serialized_with_other_commands(coordinator, config_entry):
    import asyncio
    coordinator.selected_app = APP
    button = ReachyMiniStartAppButton(coordinator, config_entry)
    with (
        patch.object(coordinator.app_control, "start", AsyncMock()) as start,
        patch.object(coordinator, "async_request_refresh", AsyncMock()),
    ):
        async with coordinator.app_command_lock:
            task = asyncio.create_task(button.async_press())
            await asyncio.sleep(0)
            start.assert_not_awaited()
        await task
        start.assert_awaited_once()
