"""App and backend lifecycle commands, separate from ordinary robot wake-up."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote

import aiohttp
from homeassistant.exceptions import HomeAssistantError

APP_LIST = "/api/apps/list-available/installed"
APP_STATUS = "/api/apps/current-app-status"
APP_SLOT = "/api/daemon/robot-app-lock-status"
DAEMON_STATUS = "/api/daemon/status"
STOP_APP = "/api/apps/stop-current-app"
START_BACKEND = "/api/daemon/start?wake_up=false"
SLEEP_BACKEND = "/api/daemon/stop?goto_sleep=true"
COMMAND_TIMEOUT = 35
TRANSITION_TIMEOUT = 90
POLL_INTERVAL = 0.5


class AppControl:
    """Use fresh robot state for commands; never infer idle from a failed read."""

    def __init__(self, session: aiohttp.ClientSession, base_url: str) -> None:
        self._session = session
        self._base_url = base_url

    async def _request(self, method: str, path: str) -> Any:
        try:
            async with self._session.request(
                method, self._base_url + path,
                timeout=aiohttp.ClientTimeout(total=COMMAND_TIMEOUT),
            ) as response:
                response.raise_for_status()
                return await response.json()
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise HomeAssistantError(
                f"Reachy Mini {method} {path} failed; state was not confirmed"
            ) from err

    async def installed_apps(self) -> list[str]:
        result = await self._request("GET", APP_LIST)
        if not isinstance(result, list) or any(
            not isinstance(item, dict)
            or not isinstance(item.get("name"), str)
            or not item["name"]
            for item in result
        ):
            raise HomeAssistantError("Invalid installed-app list from Reachy Mini")
        return sorted({item["name"] for item in result})

    async def _current(self) -> tuple[str | None, str]:
        result = await self._request("GET", APP_STATUS)
        if result is None:
            return None, "done"
        if not isinstance(result, dict):
            raise HomeAssistantError("Invalid app status from Reachy Mini")
        state = result.get("state")
        info = result.get("info")
        if state not in {"starting", "running", "stopping", "done", "error"}:
            raise HomeAssistantError("Unknown app state from Reachy Mini")
        if not isinstance(info, dict) or not isinstance(info.get("name"), str):
            raise HomeAssistantError("Missing app name from Reachy Mini")
        return info["name"], state

    async def _backend_state(self) -> str:
        result = await self._request("GET", DAEMON_STATUS)
        state = result.get("state") if isinstance(result, dict) else None
        if state not in {"not_initialized", "starting", "running", "stopping", "stopped", "error"}:
            raise HomeAssistantError("Unknown backend state from Reachy Mini")
        return state

    async def _require_free_slot(self) -> None:
        result = await self._request("GET", APP_SLOT)
        if not isinstance(result, dict) or result.get("state") != "free":
            raise HomeAssistantError(
                "Robot control is occupied or unknown; end the other session first"
            )

    async def _backend_job(self, path: str, expected_state: str) -> None:
        """A POST only accepts a job; wait for its completion and resulting state."""
        result = await self._request("POST", path)
        job_id = result.get("job_id") if isinstance(result, dict) else None
        if not isinstance(job_id, str) or not job_id:
            raise HomeAssistantError("Backend command returned no job ID")
        try:
            async with asyncio.timeout(TRANSITION_TIMEOUT):
                while True:
                    job = await self._request(
                        "GET", "/api/apps/job-status/" + quote(job_id, safe="")
                    )
                    status = job.get("status") if isinstance(job, dict) else None
                    if status == "failed":
                        raise HomeAssistantError("Reachy Mini backend command failed")
                    if status == "done":
                        if await self._backend_state() != expected_state:
                            raise HomeAssistantError("Backend did not reach the expected state")
                        return
                    if status not in {"pending", "in_progress"}:
                        raise HomeAssistantError("Unknown backend job status")
                    await asyncio.sleep(POLL_INTERVAL)
        except TimeoutError as err:
            raise HomeAssistantError(
                "Timed out waiting for the backend; it may still be changing state"
            ) from err

    async def start(self, name: str | None) -> None:
        if not name:
            raise HomeAssistantError("Select an App first")
        if name not in await self.installed_apps():
            raise HomeAssistantError("Selected app is no longer installed; select another App")
        current, state = await self._current()
        if state in {"starting", "running", "stopping"}:
            if current == name and state in {"starting", "running"}:
                return
            raise HomeAssistantError("An app is active; use Stop current app first")
        await self._require_free_slot()
        state = await self._backend_state()
        if state in {"stopped", "not_initialized"}:
            # Do not trigger a different Startup app by playing a wake animation.
            await self._backend_job(START_BACKEND, "running")
        elif state != "running":
            raise HomeAssistantError("Backend is busy or in error; try again when ready")

        # Recheck after a potentially slow backend start. The no-evict endpoint
        # also atomically refuses a remote session that wins the remaining race.
        current, state = await self._current()
        if state in {"starting", "running", "stopping"}:
            if current == name and state in {"starting", "running"}:
                return
            raise HomeAssistantError("Another app started; it has not been stopped")
        await self._require_free_slot()
        result = await self._request(
            "POST", "/api/apps/start-app/" + quote(name, safe="") + "/no-evict"
        )
        if not isinstance(result, dict) or result.get("state") not in {"starting", "running"}:
            raise HomeAssistantError("The selected app did not accept the start request")

    async def sleep(self) -> None:
        """Stop the app first; abort on uncertainty instead of disabling its backend."""
        _, state = await self._current()
        if state in {"starting", "running"}:
            await self._request("POST", STOP_APP)
        try:
            async with asyncio.timeout(TRANSITION_TIMEOUT):
                while True:
                    _, state = await self._current()
                    if state in {"done", "error"}:
                        break
                    await asyncio.sleep(POLL_INTERVAL)
        except TimeoutError as err:
            raise HomeAssistantError(
                "App did not stop; backend shutdown was not requested"
            ) from err

        # An exited process may leave an error status. A free control slot is
        # also required, so an error response alone is never enough to proceed.
        await self._require_free_slot()
        state = await self._backend_state()
        if state in {"stopped", "not_initialized"}:
            return
        if state != "running":
            raise HomeAssistantError("Backend is busy or in error; shutdown was not requested")
        await self._backend_job(SLEEP_BACKEND, "stopped")
