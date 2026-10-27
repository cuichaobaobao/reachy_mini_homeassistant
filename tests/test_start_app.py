"""App catalog loading and the App select / Start app button pair.

Mirrors the recorded-move (Emotion/Dance) select+button pattern: the
select is pick-only (no HTTP call), and the button reads that pick and
POSTs to the daemon's ``/api/apps/start-app/{app_name}`` endpoint.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockEntityPlatform

from custom_components.reachy_mini.button import ReachyMiniStartAppButton
from custom_components.reachy_mini.const import DOMAIN
from custom_components.reachy_mini.select import ReachyMiniAppSelect

from .conftest import BASE_URL


async def test_async_load_available_apps_populates_from_daemon(
    hass, coordinator, aioclient_mock
) -> None:
    """The catalog is built from the `name` field of each installed AppInfo."""
    aioclient_mock.get(
        f"{BASE_URL}/api/apps/list-available/installed",
        json=[
            {"name": "my_app", "source_kind": "local", "description": ""},
            {"name": "other_app", "source_kind": "local", "description": ""},
        ],
    )

    await coordinator.async_load_available_apps()

    assert coordinator.available_apps == ["my_app", "other_app"]
    assert coordinator.selected_app == "my_app"


async def test_async_load_available_apps_handles_empty_response(
    hass, coordinator, aioclient_mock
) -> None:
    """An empty/failing catalog leaves available_apps empty, no crash."""
    aioclient_mock.get(f"{BASE_URL}/api/apps/list-available/installed", status=404)

    await coordinator.async_load_available_apps()

    assert coordinator.available_apps == []
    assert coordinator.selected_app is None


async def test_app_select_stores_pick_without_http_call(
    hass, coordinator, config_entry, aioclient_mock
) -> None:
    """Selecting an app only mutates coordinator state, like Emotion/Dance."""
    coordinator.available_apps = ["my_app", "other_app"]
    select = ReachyMiniAppSelect(coordinator, config_entry)
    platform = MockEntityPlatform(hass, domain="select", platform_name=DOMAIN)
    await platform.async_add_entities([select])

    await select.async_select_option("other_app")

    assert coordinator.selected_app == "other_app"
    assert not aioclient_mock.mock_calls


async def test_start_app_button_posts_selected_app(
    hass, coordinator, config_entry, aioclient_mock
) -> None:
    """Pressing the button POSTs to start-app/{app_name} for the pick."""
    coordinator.available_apps = ["my_app"]
    coordinator.selected_app = "my_app"
    aioclient_mock.post(f"{BASE_URL}/api/apps/start-app/my_app", json={})
    button = ReachyMiniStartAppButton(coordinator, config_entry)

    with patch.object(coordinator, "async_request_refresh", AsyncMock()):
        await button.async_press()

    assert [
        (method, url.path) for method, url, *_ in aioclient_mock.mock_calls
    ] == [("POST", "/api/apps/start-app/my_app")]


async def test_start_app_button_errors_when_no_app_selected(
    hass, coordinator, config_entry, aioclient_mock
) -> None:
    """No pick yet (e.g. empty catalog) surfaces a friendly error, no HTTP."""
    coordinator.selected_app = None
    button = ReachyMiniStartAppButton(coordinator, config_entry)

    with pytest.raises(HomeAssistantError, match="No app selected"):
        await button.async_press()

    assert not aioclient_mock.mock_calls
