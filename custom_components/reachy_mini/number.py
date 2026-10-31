"""Controllable number entities for Reachy Mini — speaker + mic volume.

Render as 0-100 % sliders in the HA UI. Reads come from the
coordinator's cached state (same as the read-only path used to);
writes POST to the daemon's existing volume routes and immediately
trigger a coordinator refresh so the slider snaps to the value the
robot actually applied (the daemon may clamp / round).
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    ENDPOINT_VOLUME_MIC_SET,
    ENDPOINT_VOLUME_SPEAKER_SET,
)
from .coordinator import ReachyMiniCoordinator
from .entity import ReachyMiniEntity
from .manual_control import LIMITS, NAMES, pose_from_state, value_of


@dataclass(frozen=True, kw_only=True)
class ReachyMiniVolumeDescription(NumberEntityDescription):
    """Describe a Reachy Mini volume slider and where it reads/writes."""

    # Key in the coordinator's data dict that holds the current value.
    json_key: str
    # SDK POST path for setting the value (relative to base_url).
    set_path: str


NUMBERS: tuple[ReachyMiniVolumeDescription, ...] = (
    ReachyMiniVolumeDescription(
        key="speaker_volume",
        translation_key="speaker_volume",
        json_key="speaker_volume",
        set_path=ENDPOINT_VOLUME_SPEAKER_SET,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
        icon="mdi:volume-high",
    ),
    ReachyMiniVolumeDescription(
        key="mic_volume",
        translation_key="mic_volume",
        json_key="mic_volume",
        set_path=ENDPOINT_VOLUME_MIC_SET,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
        icon="mdi:microphone",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one ReachyMiniVolumeNumber per entry in :data:`NUMBERS`."""
    coordinator: ReachyMiniCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [*(ReachyMiniVolumeNumber(coordinator, entry, desc) for desc in NUMBERS),
         *(ReachyMiniMotionNumber(coordinator, entry, key) for key in LIMITS),
         ReachyMiniDurationNumber(coordinator, entry)]
    )


class ReachyMiniVolumeNumber(ReachyMiniEntity, NumberEntity):
    """A 0-100 % volume slider backed by an SDK POST endpoint."""

    entity_description: ReachyMiniVolumeDescription

    def __init__(
        self,
        coordinator: ReachyMiniCoordinator,
        entry: ConfigEntry,
        description: ReachyMiniVolumeDescription,
    ) -> None:
        """Wire the entity to its coordinator key + write path."""
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        """Read the cached volume from the coordinator dict."""
        if self.coordinator.data is None:
            return None
        value = self.coordinator.data.get(self.entity_description.json_key)
        return float(value) if value is not None else None

    async def async_set_native_value(self, value: float) -> None:
        """POST the new volume to the daemon; coordinator handles refresh."""
        await self.coordinator.async_post(
            self.entity_description.set_path,
            body={"volume": int(value)},
        )


class ReachyMiniMotionNumber(ReachyMiniEntity, NumberEntity):
    """A manual target, displaying measured feedback from the normal poll."""

    def __init__(self, coordinator, entry, key):
        super().__init__(coordinator, entry, key)
        self.key = key
        low, high, step, unit = LIMITS[key]
        self.entity_description = NumberEntityDescription(
            key=key, name=NAMES[key], translation_key=key,
            native_min_value=low, native_max_value=high, native_step=step,
            native_unit_of_measurement=unit, mode=NumberMode.SLIDER,
            icon="mdi:axis-arrow",
        )

    @property
    def available(self):
        return super().available and self.coordinator.manual_control.available()

    @property
    def native_min_value(self):
        if self.key == "head_yaw" and self.coordinator.manual_control.follows:
            return -3.141592653589793
        return self.entity_description.native_min_value

    @property
    def native_max_value(self):
        if self.key == "head_yaw" and self.coordinator.manual_control.follows:
            return 3.141592653589793
        return self.entity_description.native_max_value

    @property
    def native_value(self):
        pose = pose_from_state((self.coordinator.data or {}).get("full_state"))
        # Three decimals, like the desktop slider labels.
        return round(value_of(pose, self.key), 3) + 0.0 if pose is not None else None

    async def async_set_native_value(self, value):
        await self.coordinator.manual_control.move(self.key, value)


class ReachyMiniDurationNumber(ReachyMiniEntity, NumberEntity):
    """Integration-local movement preference; never sends a motor command."""

    entity_description = NumberEntityDescription(
        key="movement_duration", name="Movement duration", translation_key="movement_duration",
        native_min_value=0.5, native_max_value=5.0, native_step=0.1,
        native_unit_of_measurement="s", mode=NumberMode.SLIDER, icon="mdi:timer-outline",
    )

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "movement_duration")

    @property
    def native_value(self):
        return self.coordinator.manual_control.duration

    async def async_set_native_value(self, value):
        from .manual_control import finite
        from homeassistant.exceptions import HomeAssistantError
        if not finite(value) or not 0.5 <= value <= 5.0:
            raise HomeAssistantError("Movement duration must be between 0.5 and 5 seconds")
        if self.coordinator.manual_control.busy:
            raise HomeAssistantError("Wait for the current movement to finish")
        self.coordinator.manual_control.duration = value
        self.coordinator.async_update_listeners()
